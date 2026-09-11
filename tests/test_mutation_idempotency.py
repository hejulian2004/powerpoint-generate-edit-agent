"""PR22 / Fix B: mutation_id idempotency + session result cache.

Exactly-once semantics for the single-flight transport: a caller-supplied
`mutation_id` that has already produced a terminal outcome (success, atomic
success, undo/redo success, or an acknowledged empty undo/redo no-op) must
return that outcome on replay instead of executing again.
"""

import asyncio

from backend.agent.mutation_gateway import (
    DOCUMENT_EPOCH_MISMATCH,
    MutationBatchResult,
    MutationGateway,
)
from backend.session.manager import session_manager
from backend.state.store import create_default_demo_presentation


def _session(session_id: str):
    return session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )


def test_mutation_cache_is_bounded_lru():
    session = _session("idem_lru")
    for i in range(257):
        session.remember_mutation_result(f"m{i}", MutationBatchResult(mutation_id=f"m{i}"))

    assert len(session.completed_mutations) == 256
    assert session.get_cached_mutation_result("m0") is None  # oldest evicted
    assert session.get_cached_mutation_result("m1") is not None

    # Access m1 above moved it to the MRU end, so the next insert evicts m2.
    session.remember_mutation_result("m257", MutationBatchResult(mutation_id="m257"))
    assert len(session.completed_mutations) == 256
    assert session.get_cached_mutation_result("m2") is None
    assert session.get_cached_mutation_result("m1") is not None


def test_mutation_cache_cleared_on_epoch_rotation():
    session = _session("idem_epoch")
    session.remember_mutation_result("m1", MutationBatchResult(mutation_id="m1"))
    assert session.get_cached_mutation_result("m1") is not None

    session.replace_presentation(create_default_demo_presentation())

    assert len(session.completed_mutations) == 0
    assert session.get_cached_mutation_result("m1") is None


def test_mutation_cache_key_binds_document_epoch():
    session = _session("idem_key")
    epoch = session.document_epoch
    session.remember_mutation_result("m1", MutationBatchResult(mutation_id="m1"))

    assert session.get_cached_mutation_result("m1", document_epoch=epoch) is not None
    assert session.get_cached_mutation_result("m1", document_epoch="other_epoch") is None


def test_gateway_replays_cached_result_and_skips_cas():
    session = _session("idem_gateway")
    slide_id = session.pres.slides[0].id
    element = session.pres.slides[0].elements[0]
    call = {
        "name": "update_element",
        "arguments": {"slide_id": slide_id, "element_id": element.id, "x": 321.0},
        "id": "call_1",
    }

    first = asyncio.run(MutationGateway.execute_tool_calls(
        [call], session.pres, session.history, session=session,
        bypass_confirmation=True, mutation_id="mut_g1",
    ))
    assert first.success
    version_after_first = session.pres.version

    # A replay may carry a now-stale expected_revision (its ACK was lost); the
    # cache must short-circuit *before* CAS and return the original outcome.
    replay = asyncio.run(MutationGateway.execute_tool_calls(
        [call], session.pres, session.history, session=session,
        bypass_confirmation=True, mutation_id="mut_g1", expected_revision=version_after_first - 5,
    ))
    assert replay.success
    assert session.pres.version == version_after_first


def test_gateway_cache_is_namespaced_by_request_epoch():
    """A replay carrying a different request epoch must miss the cache and hit CAS."""
    session = _session("idem_gateway_epoch")
    slide_id = session.pres.slides[0].id
    element = session.pres.slides[0].elements[0]
    call = {
        "name": "update_element",
        "arguments": {"slide_id": slide_id, "element_id": element.id, "x": 77.0},
        "id": "call_1",
    }

    first = asyncio.run(MutationGateway.execute_tool_calls(
        [call], session.pres, session.history, session=session,
        bypass_confirmation=True, mutation_id="mut_X",
    ))
    assert first.success

    # Same id, but the request claims a different document epoch: the cache is
    # namespaced by (document_epoch, mutation_id), so this must NOT be a hit.
    replay = asyncio.run(MutationGateway.execute_tool_calls(
        [call], session.pres, session.history, session=session,
        bypass_confirmation=True, mutation_id="mut_X", document_epoch="wrong_epoch",
    ))
    assert replay.error == DOCUMENT_EPOCH_MISMATCH


def test_gateway_generated_ids_are_not_cached():
    session = _session("idem_generated")
    slide_id = session.pres.slides[0].id
    element = session.pres.slides[0].elements[0]
    call = {
        "name": "update_element",
        "arguments": {"slide_id": slide_id, "element_id": element.id, "x": 50.0},
        "id": "call_1",
    }

    first = asyncio.run(MutationGateway.execute_tool_calls(
        [call], session.pres, session.history, session=session, bypass_confirmation=True,
    ))
    assert first.success
    version_after_first = session.pres.version

    second = asyncio.run(MutationGateway.execute_tool_calls(
        [call], session.pres, session.history, session=session, bypass_confirmation=True,
    ))
    assert second.success
    assert second.mutation_id != first.mutation_id
    assert session.pres.version == version_after_first + 1
