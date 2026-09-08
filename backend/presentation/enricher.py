"""Optional LLM semantic refinement for PresentationPlan (PR7.2).

Refines slide titles, communicative objectives, and generates crisp academic key messages.
Follows the rule-first architecture:
- Presentation structure (slide count, slide types, figure bindings) is completely DETERMINISTIC.
- LLM is only called to polish text fields if a live API key is present.
- Safe zero-network degradation: immediately returns the candidate plan untouched if
  no live key is present or if the network/model call fails.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List

from ..config import settings
from .schema import PresentationPlan, SlidePlan

_SYSTEM_PROMPT = (
    "You are an expert academic presentation coach for top computer science conferences "
    "(CVPR, NeurIPS, ICML, ICLR). You will be given a candidate PresentationPlan and paper context.\n"
    "Your goal is to refine the slide titles, objectives, and key_messages to be crisp, scholarly, "
    "and highly persuasive for an academic audience.\n\n"
    "STRICT CONSTRAINTS:\n"
    "1. Keep EXACTLY the same number of slides.\n"
    "2. Keep EXACTLY the same index and slide_type for each slide.\n"
    "3. Keep the exact source_sections, source_figures, and source_tables intact.\n"
    "4. For each slide, provide 2 to 4 concise, high-impact key_messages (<= 140 chars each).\n"
    "5. Return a valid JSON object matching the PresentationPlan schema.\n"
)


def enrich_presentation_plan(plan: PresentationPlan) -> PresentationPlan:
    """Synchronous entry point for refining a presentation plan."""
    if _no_live_key():
        return plan
    return asyncio.run(_enrich_plan_async(plan))


async def aenrich_presentation_plan(plan: PresentationPlan) -> PresentationPlan:
    """Asynchronous entry point for refining a presentation plan."""
    if _no_live_key():
        return plan
    return await _enrich_plan_async(plan)


def _no_live_key() -> bool:
    key = (settings.openai_api_key or "").strip()
    return not key or key.startswith("mock_")


async def _enrich_plan_async(plan: PresentationPlan) -> PresentationPlan:
    from ..agent.llm import LLMClient

    client = LLMClient()
    payload = json.dumps(plan.to_dict(), indent=2)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Please refine the wording of this presentation plan:\n\n{payload}",
        },
    ]

    try:
        resp = await client.chat_completion(
            messages=messages,
            role="reasoning",
            temperature=0.0,
            max_tokens=4096,
        )
        content = resp["choices"][0]["message"].get("content", "")
        data = _parse_json_object(content)
        return apply_plan_refinement(plan, data)
    except Exception:
        # Fallback cleanly to the deterministic candidate plan on any failure
        return plan


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """Robust JSON extraction from LLM completion text.

    Resilient to:
    - Direct JSON string output.
    - Markdown code fences (```json ... ```).
    - Arbitrary prefix/suffix chatter by locating outer-most braces.
    - Nested JSON objects (does not truncate prematurely).
    """
    cleaned = raw.strip()

    # 1. Direct parse attempt
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Extract from markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1).strip())
            if isinstance(data, dict):
                return data
        except Exception:
            cleaned = fence_match.group(1).strip()

    # 3. Locate outermost { ... }
    first_idx = cleaned.find("{")
    last_idx = cleaned.rfind("}")
    if first_idx != -1 and last_idx != -1 and last_idx > first_idx:
        candidate = cleaned[first_idx : last_idx + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    raise ValueError("Could not parse valid JSON object from LLM response")


def apply_plan_refinement(original: PresentationPlan, data: Dict[str, Any]) -> PresentationPlan:
    """Safely apply LLM-refined text fields without altering structural bindings.

    Strict Invariant Guards:
    - Rejects refinement entirely (fail-closed) if:
      1. Slide count does not match original.
      2. Slide index does not match original.
      3. An explicit slide_type is returned and differs from original.
      4. Explicit source_figures / source_tables / source_sections differ from original.
      5. key_messages violates constraints (must have 2 to 4 items, <= 140 chars each).
    - Only permits updating title, objective, key_messages, and notes.
    """
    if not isinstance(data, dict) or "slides" not in data or not isinstance(data["slides"], list):
        return original

    refined_slides_data = data["slides"]
    if len(refined_slides_data) != len(original.slides):
        return original

    # Invariant pass 1: validate that every slide honors structural and length invariants
    for orig_slide, ref_data in zip(original.slides, refined_slides_data):
        if not isinstance(ref_data, dict):
            return original

        # Check index invariant if present
        ref_idx = ref_data.get("index")
        if ref_idx is not None and ref_idx != orig_slide.index:
            return original

        # Check slide_type invariant if present
        ref_type = ref_data.get("slide_type")
        if ref_type is not None and ref_type != orig_slide.slide_type:
            return original

        # Check source bindings invariants if present
        if "source_figures" in ref_data and ref_data["source_figures"] != orig_slide.source_figures:
            return original
        if "source_tables" in ref_data and ref_data["source_tables"] != orig_slide.source_tables:
            return original
        if "source_sections" in ref_data and ref_data["source_sections"] != orig_slide.source_sections:
            return original

        # Check key_messages constraints if provided
        if "key_messages" in ref_data:
            ref_keys = ref_data["key_messages"]
            if not isinstance(ref_keys, list):
                return original
            # Must be between 2 and 4 messages
            if len(ref_keys) < 2 or len(ref_keys) > 4:
                return original
            for k in ref_keys:
                if not isinstance(k, str):
                    return original
                k_clean = k.strip()
                if not k_clean or len(k_clean) > 140:
                    return original

    # Invariant pass 2: construct refined slides safely
    updated_slides: List[SlidePlan] = []
    for orig_slide, ref_data in zip(original.slides, refined_slides_data):
        new_title = str(ref_data.get("title", orig_slide.title)).strip() or orig_slide.title
        new_obj = str(ref_data.get("objective", orig_slide.objective)).strip() or orig_slide.objective
        new_notes = ref_data.get("notes")
        notes_val = str(new_notes).strip() if isinstance(new_notes, str) and new_notes.strip() else orig_slide.notes

        if "key_messages" in ref_data and isinstance(ref_data["key_messages"], list):
            cleaned_keys = [k.strip() for k in ref_data["key_messages"] if isinstance(k, str) and k.strip()]
        else:
            cleaned_keys = orig_slide.key_messages

        updated_slides.append(
            orig_slide.model_copy(
                update={
                    "title": new_title,
                    "objective": new_obj,
                    "key_messages": cleaned_keys,
                    "notes": notes_val,
                }
            )
        )

    return original.model_copy(update={"slides": updated_slides})
