"""Replay determinism of randomness and workflow identity.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS asserts that a workflow's non-durable readings are stable across recovery
-- the same workflow ID, and randomness that does not change under replay.
Cleat makes the same claim: `h.Random()` is drawn from the session so a replay
reproduces it, and identity is answered from the instance row.

The mechanism does most of the asserting. `SideEffect` VALIDATES rather than
caches: on replay it recomputes the closure and compares against history,
failing the workflow on a mismatch. So a reading that is not stable never
reaches `done`, and the run completing is itself the determinism assertion.

What the mechanism cannot tell us is whether the reading was ever meaningful,
and that is the half these tests are shaped around. `h.NewUUID()` returned a
constant zero UUID in every compiled workflow until cleat#786, and a constant
survives replay perfectly. A determinism test built on one passes no matter
what the engine does -- which is how an earlier version of the replay test in
this suite passed while asserting nothing.
"""

import json

import pytest

SLEEP_MS = 3000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


@pytest.fixture(scope="module")
def run(cleat, determinism_workflow):
    """One run, shared: every assertion below reads the same execution.

    Separate runs would let a defect that makes randomness constant WITHIN a
    run but varying between runs slip past the distinctness check.
    """
    status, started = cleat.start(determinism_workflow, {"ms": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", (
        f"the workflow did not complete: {final!r}. Every reading it captures goes "
        "through SideEffect, which fails the run on a replay mismatch, so a "
        "non-terminal run here IS the determinism failure."
    )
    return started["id"], _body(final)


def test_randomness_survives_the_replay(run):
    """Implied by the run completing; asserted so the reason is on the record."""
    _, body = run
    assert body["r1"] and body["r2"], f"a draw came back empty: {body!r}"


def test_two_draws_are_not_the_same_value(run):
    """The check that makes the one above mean something.

    An unwired Random returning 0 every time is perfectly stable across replay
    and perfectly useless. This is the assertion that separates "deterministic"
    from "constant", and it is the one that would have caught cleat#786's zero
    UUID.
    """
    _, body = run
    assert body["r1"] != body["r2"], (
        f"two separate draws both returned {body['r1']!r}. Randomness that never "
        "varies passes every replay check trivially, so the determinism "
        "assertions here would be measuring nothing."
    )
    assert body["r1"] != "0" or body["r2"] != "0", (
        "both draws are zero, which is what an unwired host call returns"
    )


def test_identity_is_the_same_before_and_after_a_suspension(run):
    """Identity is answered by the session, not served from history.

    So unlike the readings above, nothing in the replay machinery would object
    if a resumed workflow reported a different ID -- there is no recorded value
    to compare against. It has to be checked directly.
    """
    run_id, body = run

    assert body["wfBefore"] == body["wfAfter"], (
        f"workflow ID changed across the suspension: {body['wfBefore']!r} -> "
        f"{body['wfAfter']!r}. A workflow that wakes up as a different workflow "
        "has lost the identity every durable guarantee is keyed on."
    )
    assert body["runBefore"] == body["runAfter"], (
        f"run ID changed across the suspension: {body['runBefore']!r} -> "
        f"{body['runAfter']!r}"
    )


def test_the_reported_identity_is_the_one_the_caller_was_given(run):
    """Otherwise both halves could be internally consistent and wrong.

    A workflow that consistently reports an ID unrelated to the run the caller
    started passes every assertion above.
    """
    run_id, body = run
    assert body["runBefore"] == run_id, (
        f"the workflow reports run ID {body['runBefore']!r} but the caller started "
        f"{run_id!r}"
    )
    assert body["wfBefore"], "the workflow reports an empty workflow ID"
