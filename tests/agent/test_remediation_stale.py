"""A visual remediation proposed against an older revision must be discarded.

The vision critic reviews a specific deck revision. If the user (or another
writer) edits the deck before auto_correct runs, applying the old repair would
move the document backwards / fight the user. `auto_correct_node` must drop it.
"""

import asyncio

from backend.agent.graph import auto_correct_node
from backend.agent.remediation_runner import RemediationRunner
from backend.ir.models import PresentationIR, SlideIR
from backend.session.session import PPTSession


def _pres(version=4):
    pres = PresentationIR(title="Remediation", version=version)
    pres.slides.append(SlideIR(id="slide_1", slide_num=1))
    pres.active_slide_id = "slide_1"
    return pres


def test_stale_visual_review_discards_remediation(monkeypatch):
    pres = _pres(version=4)
    session = PPTSession(session_id="sess_remediation_stale", pres=pres)
    review_epoch = session.document_epoch
    review_revision = pres.version

    calls = {"n": 0}

    def fake_apply(*args, **kwargs):
        calls["n"] += 1
        return {"applied_records": [], "rolled_back": False, "message": "applied"}

    monkeypatch.setattr(RemediationRunner, "apply_plan", staticmethod(fake_apply))

    async def _run():
        # The deck moves on after the review but before auto_correct.
        pres.version = review_revision + 1

        visual_review = {
            "slides": {
                "slide_1": {
                    "needs_auto_correction": True,
                    "has_critical_defects": True,
                    "remediation_plan": {
                        "has_critical": True,
                        "actions": [{
                            "action_type": "move_element",
                            "category": "geometry",
                            "target_ids": ["e1"],
                            "parameters": {"x": 10.0, "y": 10.0},
                        }],
                    },
                }
            },
            "review_document_epoch": review_epoch,
            "review_revision": review_revision,
        }

        out = await auto_correct_node(
            {"visual_review": visual_review, "tool_results": [], "active_slide_id": "slide_1"},
            {"configurable": {
                "pres": pres,
                "history": session.history,
                "session": session,
                "on_event": None,
            }},
        )

        assert calls["n"] == 0
        assert out["tool_results"] == []

    asyncio.run(_run())
