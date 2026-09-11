"""The executor must freeze its planning stamp BEFORE awaiting the LLM.

Otherwise a plan derived from revision N gets labeled with the live revision
N+1, and the stale-plan guard can no longer detect that the deck moved on.
"""

import asyncio
import json

from backend.agent.subagents.executor import ExecutorSubagent
from backend.ir.models import PresentationIR, SlideIR
from backend.session.session import PPTSession


class _ConcurrentEditLLM:
    """A live-looking LLM whose await advances the document revision."""

    api_key = "test-live-key"

    def __init__(self, pres):
        self.pres = pres
        self.seen_versions = []

    async def chat_completion(self, messages=None, tools=None, role=None):
        # Record the version serialized into the prompt (the snapshot).
        for m in messages or []:
            if m.get("role") == "system":
                self.seen_versions.append(self.pres.version)
        # A concurrent GUI mutation lands during the await.
        self.pres.version += 1
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_frozen",
                        "function": {
                            "name": "update_element",
                            "arguments": json.dumps({"element_id": "e1", "x": 42.0}),
                        },
                    }]
                }
            }]
        }


def _pres(version=5):
    pres = PresentationIR(title="Frozen Plan", version=version)
    slide = SlideIR(id="slide_1", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def test_executor_plan_stamp_is_frozen_before_llm_await():
    async def _run():
        pres = _pres(version=5)
        session = PPTSession(session_id="sess_exec_freeze", pres=pres)
        epoch_before = session.document_epoch
        llm = _ConcurrentEditLLM(pres)

        plan = await ExecutorSubagent.plan_task(
            intent="modify_elements",
            user_query="把标题改小",
            plan_desc="",
            pres=pres,
            memory=None,
            llm_client=llm,
            session=session,
        )

        # The document advanced during the await...
        assert pres.version == 6
        # ...but the plan is stamped with the version it actually planned from.
        assert plan.base_revision == 5
        assert plan.document_epoch == epoch_before

    asyncio.run(_run())


def test_executor_plan_uses_snapshot_not_live_object():
    async def _run():
        pres = _pres(version=5)
        session = PPTSession(session_id="sess_exec_snapshot", pres=pres)
        llm = _ConcurrentEditLLM(pres)

        # Mutate the live document before planning; the snapshot must reflect the
        # state at plan time, not later mutations.
        plan = await ExecutorSubagent.plan_task(
            intent="modify_elements",
            user_query="把标题改小",
            plan_desc="",
            pres=pres,
            memory=None,
            llm_client=llm,
            session=session,
        )
        assert plan.tool_calls
        assert plan.base_revision == 5

    asyncio.run(_run())
