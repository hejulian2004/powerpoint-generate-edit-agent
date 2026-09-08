"""Optional LLM semantic enrichment for PaperIR.

The deterministic extractor only fills structural fields (metadata / abstract /
sections / figures / tables). The semantic fields that require understanding
(contributions / methodology / experiments / limitations) are filled here with a
structured-output LLM call whenever a live API key is configured.

Guarantees:
- Never raises on a missing / mock key: the PaperIR is returned unchanged with
  ``semantic_status='extracted'``.
- LLM output is schema-validated by ``apply_enrichment``; any parse / validation
  failure is downgraded to ``semantic_status='enrichment_failed'`` without crashing.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List

from ..config import settings
from .schema import ExtractionMeta, PaperIR

_SYSTEM_PROMPT = (
    "You are a computer-science paper reading assistant. Given the structured "
    "content of an academic paper (title, abstract, sections, figure/table captions), "
    "extract concise, faithful bullet points grounded ONLY in the provided text.\n"
    'Respond with a single JSON object using exactly these keys:\n'
    '  "contributions": string[]   - the paper\'s key technical contributions\n'
    '  "methodology": string[]     - core method / framework ideas\n'
    '  "experiments": string[]     - main experimental claims and results\n'
    '  "limitations": string[]     - stated or evident limitations\n'
    "Each bullet must be short (<= 140 chars), factual, and not hallucinated. "
    "If a category has no evidence, return an empty array."
)

_LIVE_KEY_REQUIRED = object()  # sentinel to detect "no real key" without raising


def enrich_paper(paper: PaperIR) -> PaperIR:
    """Synchronous wrapper over the async enrichment (safe to call from CLI/scripts)."""
    if _no_live_key():
        return paper
    return asyncio.run(_enrich_paper_async(paper))


async def aenrich_paper(paper: PaperIR) -> PaperIR:
    """Async enrichment; returns the paper unchanged when no live API key is set."""
    if _no_live_key():
        return paper
    return await _enrich_paper_async(paper)


def _no_live_key() -> bool:
    key = (settings.openai_api_key or "").strip()
    return not key or key.startswith("mock_")


async def _enrich_paper_async(paper: PaperIR) -> PaperIR:
    from ..agent.llm import LLMClient

    client = LLMClient()
    payload = _build_prompt_payload(paper)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": payload},
    ]
    try:
        resp = await client.chat_completion(
            messages=messages,
            role="reasoning",
            temperature=0.0,
            max_tokens=2048,
        )
        content = resp["choices"][0]["message"].get("content", "")
        data = _parse_json_object(content)
        return apply_enrichment(paper, data)
    except Exception:
        return paper.model_copy(
            update={
                "extraction": paper.extraction.model_copy(
                    update={"semantic_status": "enrichment_failed"}
                )
            }
        )


def apply_enrichment(paper: PaperIR, data: Dict[str, Any]) -> PaperIR:
    """Validate raw LLM mapping and produce an enriched PaperIR (pure, deterministic).

    Exported for offline unit testing of the schema-merge behaviour.
    """
    clean = _sanitize_bullets(data)
    return paper.model_copy(
        update={
            "contributions": clean["contributions"],
            "methodology": clean["methodology"],
            "experiments": clean["experiments"],
            "limitations": clean["limitations"],
            "extraction": paper.extraction.model_copy(update={"semantic_status": "enriched"}),
        }
    )


def _build_prompt_payload(paper: PaperIR) -> str:
    sections = []
    for sec in paper.sections:
        head = f"{sec.number + '. ' if sec.number else ''}{sec.title}"
        sections.append(head)
        sections.extend(sec.paragraphs)
    figures = [
        f"{f.xref_label}: {f.caption} (page {f.page})" for f in paper.figures
    ]
    tables = [
        f"{t.xref_label}: {t.caption} (page {t.page})" for t in paper.tables
    ]
    doc = {
        "title": paper.metadata.title,
        "abstract": paper.abstract,
        "body": sections,
        "figures": figures,
        "tables": tables,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def _sanitize_bullets(data: Any) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {
        "contributions": [],
        "methodology": [],
        "experiments": [],
        "limitations": [],
    }
    if not isinstance(data, dict):
        return out
    for key in out:
        raw = data.get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        items: List[str] = []
        for it in raw:
            if not isinstance(it, str):
                continue
            item = " ".join(it.split()).strip()
            if item and len(item) <= 500 and item not in items:
                items.append(item)
        out[key] = items
    return out


def _parse_json_object(content: str) -> Dict[str, Any]:
    """Extract the first JSON object from model output (tolerates code fences)."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM output")
        return json.loads(match.group(0))
