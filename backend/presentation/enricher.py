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
    cleaned = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
    return json.loads(cleaned)


def apply_plan_refinement(original: PresentationPlan, data: Dict[str, Any]) -> PresentationPlan:
    """Safely apply LLM-refined text fields without altering structural bindings."""
    if not isinstance(data, dict) or "slides" not in data or not isinstance(data["slides"], list):
        return original

    refined_slides_data = data["slides"]
    if len(refined_slides_data) != len(original.slides):
        return original

    updated_slides: List[SlidePlan] = []
    for orig_slide, ref_data in zip(original.slides, refined_slides_data):
        if not isinstance(ref_data, dict):
            updated_slides.append(orig_slide)
            continue

        # Preserve structural properties, update wording if valid
        new_title = str(ref_data.get("title", orig_slide.title)).strip() or orig_slide.title
        new_obj = str(ref_data.get("objective", orig_slide.objective)).strip() or orig_slide.objective
        new_keys = ref_data.get("key_messages")
        if isinstance(new_keys, list) and all(isinstance(k, str) for k in new_keys) and len(new_keys) > 0:
            cleaned_keys = [k.strip() for k in new_keys if k.strip()]
        else:
            cleaned_keys = orig_slide.key_messages

        updated_slides.append(
            orig_slide.model_copy(
                update={
                    "title": new_title,
                    "objective": new_obj,
                    "key_messages": cleaned_keys,
                }
            )
        )

    return original.model_copy(update={"slides": updated_slides})
