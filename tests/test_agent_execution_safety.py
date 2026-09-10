"""End-to-end execution safety gates for the agent control plane.

These tests pin the merge-blocking invariants introduced by the hardening round:

1. The Executor subagent has no tool execution authority (static guard).
2. The agent graph routes every mutation through `mutation_node` -> MutationGateway.
3. A dangerous unresolved mutation proposed during `run_turn` MUST NOT mutate the
   deck and MUST register a pending confirmation.
4. The gateway rolls back partial mutations when a handler fails.
"""

import asyncio
import inspect
from pathlib import Path

from backend.agent import graph as graph_module
from backend.agent.graph import build_ppt_agent_graph
from backend.agent.mutation_gateway import MutationGateway
from backend.agent.runtime import AgentRuntime
from backend.agent.tools import tools
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pres_with_title():
    pres = PresentationIR(title="Safety Gate")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title_node", name="Main Title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


# =====================================================================
# Static architecture guards
# =====================================================================

def test_executor_subagent_has_no_tool_execution_authority():
    """The Executor may plan, but it must never call the tool dispatcher itself."""
    from backend.agent.subagents import executor as executor_module

    source = inspect.getsource(executor_module)
    assert "tools.execute" not in source
    assert "tools.handlers" not in source


def test_executor_module_is_the_only_planned_writer():
    """No production module except the gateway may call tools.execute directly."""
    backend_dir = REPO_ROOT / "backend"
    offenders = []
    for path in backend_dir.rglob("*.py"):
        if path.name == "mutation_gateway.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "tools.execute" in source:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_graph_routes_execution_through_mutation_node():
    compiled = build_ppt_agent_graph()
    nodes = set(compiled.get_graph().nodes.keys())
    assert "mutation_node" in nodes
    assert "tools_node" not in nodes
    assert "executor_node" in nodes
    assert not hasattr(graph_module, "tools_node")


# =====================================================================
# End-to-end run_turn safety
# =====================================================================

class GhostDeleteLLM:
    """Live LLM stub that proposes deleting an unresolved element."""

    api_key = "live_test_key"

    async def chat_completion(self, messages, role="reasoning", tools=None, **kwargs):
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        if "策划架构评审总监" in sys_msg:
            return {"choices": [{"message": {"content": "【评审结论】: 通过\n【规划健康分: 95/100】"}}]}
        if "内容与叙事结构总监" in sys_msg:
            return {"choices": [{"message": {"content": "【内容评审结论】: 通过\n【内容健康分: 90/100】"}}]}
        if role == "vision":
            return {"choices": [{"message": {"content": "【美学评分: 92/100】"}}]}
        if tools:
            return {"choices": [{"message": {"tool_calls": [{
                "id": "call_ghost_delete",
                "type": "function",
                "function": {"name": "delete_element", "arguments": '{"element_id": "ghost_element"}'},
            }]}}]}
        return {"choices": [{"message": {"content": "ok"}}]}


class ExactDeleteLLM(GhostDeleteLLM):
    """Live LLM stub that proposes deleting a real, exact element."""

    async def chat_completion(self, messages, role="reasoning", tools=None, **kwargs):
        if tools:
            return {"choices": [{"message": {"tool_calls": [{
                "id": "call_exact_delete",
                "type": "function",
                "function": {"name": "delete_element", "arguments": '{"element_id": "title_node"}'},
            }]}}]}
        return await super().chat_completion(messages, role=role, tools=tools, **kwargs)


def test_run_turn_blocks_unresolved_dangerous_mutation():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_safety", pres=pres)
        runtime = AgentRuntime(llm_client=GhostDeleteLLM())
        events = []

        async def on_event(payload):
            events.append(payload)

        result = await runtime.run_turn(
            "删除那个元素",
            pres,
            history,
            session=session,
            on_event=on_event,
        )

        assert result.get("error") is None
        # Mutation must NOT have happened.
        assert pres.slides[0].get_element("title_node") is not None
        # Pending confirmation registered for the exact original call.
        pending = session.get_pending_confirmation("call_ghost_delete")
        assert pending is not None
        assert pending["tool"] == "delete_element"
        assert pending["arguments"] == {"element_id": "ghost_element"}
        assert pending["document_epoch"] == session.document_epoch
        assert any(
            e.get("type") == "confirmation_required"
            and e.get("call_id") == "call_ghost_delete"
            for e in events
        )

    asyncio.run(_run())


def test_run_turn_executes_resolved_mutation():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_safety_ok", pres=pres)
        runtime = AgentRuntime(llm_client=ExactDeleteLLM())

        await runtime.run_turn("删除标题元素", pres, history, session=session)

        # Exact element resolution clears the risk gate and the mutation commits.
        assert pres.slides[0].get_element("title_node") is None
        assert not session.pending_confirmations

    asyncio.run(_run())


def test_gateway_rolls_back_partial_mutation_on_handler_failure():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        original_x = pres.slides[0].elements[0].x

        def _bad_handler(pres, history, **kwargs):
            # Mutate first, then fail: the gateway must restore the snapshot.
            pres.slides[0].elements[0].x = 999.0
            raise RuntimeError("boom")

        tools.handlers["__test_bad_handler__"] = _bad_handler
        try:
            res = MutationGateway.execute_one_sync(
                "__test_bad_handler__", {}, pres, history
            )
        finally:
            del tools.handlers["__test_bad_handler__"]

        assert res["success"] is False
        assert pres.slides[0].elements[0].x == original_x

    asyncio.run(_run())
