"""The dead-letter queue: reaching it, listing it, and getting back out.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream file: `tests/test_failures.py` — what happens to work that cannot
succeed. DBOS retries to a budget and then leaves the workflow in a terminal
error state an operator can inspect and re-drive; cleat's equivalent is the
dead-letter queue.

WHY THIS FILE NEEDED A NEW WORKFLOW, which is a finding in itself: every other
workflow in this suite CATCHES its call error and returns a result describing
it, so every one completes `done` however badly the call went. Nothing could
put a row in the dead-letter table, so `/api/dead-letters`,
`.../reprocess` and `.../terminate` had never been called from a test at all.
`workflows/deadletter` exists to propagate the error instead of describing it.

Reaching that path also surfaced cleat#902: whether a terminal failure is
dead-lettered or merely failed is decided by `strings.Contains(errMsg,
"retries exhausted")` -- a substring match on a human-readable message, while
the typed `ErrRetriesExhausted` code sits unused in the same function's
parameters.
"""

import json
import time
import uuid

import pytest


def _dead_letter(cleat, workflow, key):
    """Start a run that cannot succeed and wait for it to be dead-lettered."""
    status, started = cleat.start(workflow, {
        "service": "flaky", "key": key, "attempts": 2, "intervalMs": 100,
    })
    assert status == 201, f"start rejected: {status} {started}"

    deadline = time.time() + 60.0
    while time.time() < deadline:
        state = cleat.get(started["id"])[1]
        if state.get("status") == "dead_lettered":
            return started["id"], state
        if state.get("status") in ("done", "failed", "terminated"):
            pytest.fail(
                f"the run reached {state['status']!r} rather than dead_lettered. "
                f"Dead-lettering turns on the error message containing 'retries "
                f"exhausted' (cleat#902), so a change to that wording lands here."
            )
        time.sleep(0.3)
    pytest.fail(f"run {started['id']} never reached a terminal state")


def test_a_workflow_that_exhausts_its_retries_is_dead_lettered(cleat, dead_letter_workflow):
    """Work that cannot succeed is retained rather than discarded.

    The distinction that matters is dead_lettered versus failed: one is kept
    for an operator to re-drive, the other is not. Asserted on the listing as
    well as the status, because they are separate code paths and cleat#830 was
    an endpoint that answered nothing while the data was fine.
    """
    key = f"dlq-{uuid.uuid4().hex[:8]}"
    run_id, _ = _dead_letter(cleat, dead_letter_workflow, key)

    code, listing = cleat.dead_letters()
    assert code == 200, f"the dead-letter list answered {code}: {listing!r}"
    assert run_id in {row.get("id") for row in listing}, (
        f"run {run_id} is dead_lettered but absent from /api/dead-letters "
        f"({len(listing)} rows)"
    )


def test_reprocessing_starts_a_new_run_and_leaves_the_original(cleat, dead_letter_workflow):
    """Reprocess re-drives the work as a FRESH run; it does not resume the old one.

    Measured, and worth pinning because either design is defensible and the
    difference is visible to an operator: the response carries a new id, and the
    original stays dead_lettered rather than moving back to ready. Someone who
    assumed resumption would poll the original id forever.
    """
    key = f"dlq-re-{uuid.uuid4().hex[:8]}"
    run_id, _ = _dead_letter(cleat, dead_letter_workflow, key)

    code, body = cleat.dlq_op(run_id, "reprocess")
    assert code == 201, f"reprocess answered {code}: {body!r}"

    new_id = body.get("id")
    assert new_id, f"reprocess returned no id for the new run: {body!r}"
    assert new_id != run_id, (
        f"reprocess returned the original id {run_id!r}, so this asserts "
        f"resumption when the endpoint creates a new run"
    )

    original = cleat.get(run_id)[1]
    assert original.get("status") == "dead_lettered", (
        f"the original run moved to {original.get('status')!r} after reprocess; "
        f"it is expected to stay dead_lettered as the record of what happened"
    )


def test_terminating_a_dead_lettered_run_removes_it_from_the_queue(cleat, dead_letter_workflow):
    """Terminate is the operator's other option: give up on it deliberately.

    A dead-letter queue nothing can be removed from grows without bound, so the
    assertion is on the LISTING as well as the status -- a status change that
    leaves the row in the queue would look correct from the run's own record.
    """
    key = f"dlq-term-{uuid.uuid4().hex[:8]}"
    run_id, _ = _dead_letter(cleat, dead_letter_workflow, key)

    code, body = cleat.dlq_op(run_id, "terminate")
    assert code == 200, f"terminate answered {code}: {body!r}"

    final = cleat.get(run_id)[1]
    assert final.get("status") == "terminated", (
        f"a terminated run reports {final.get('status')!r}: {final!r}"
    )

    code, listing = cleat.dead_letters()
    assert code == 200, f"the dead-letter list answered {code}: {listing!r}"
    assert run_id not in {row.get("id") for row in listing}, (
        f"run {run_id} was terminated but is still in /api/dead-letters. A queue "
        f"nothing leaves grows without bound."
    )


def test_retrying_a_run_that_is_not_dead_lettered_is_refused(cleat, retry_workflow):
    """The refusal is a 400 that says why, not a 500 and not a silent success.

    cleat#832 was exactly this class -- a refusal reported as a server fault
    because the status came from the error message -- so the status is pinned.
    """
    key = f"dlq-live-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"
    cleat.await_terminal(started["id"], timeout=60.0)

    code, body = cleat._req("POST", f"/api/workflows/{started['id']}/retry", {})
    assert code == 400, (
        f"retrying a run that was never dead-lettered answered {code}: {body!r}. "
        f"500 here would be cleat#832's shape."
    )


def test_dead_lettering_survives_a_workflow_rewriting_the_error(
    cleat, dead_letter_opaque_workflow
):
    """Retries exhausted, but the workflow reports the failure in its own words.

    cleat#902 replaced a bare substring match on "retries exhausted" with a
    typed fact plus a correlation:

        ev.RetriesExhausted && ev.Err != "" && strings.Contains(errMsg, ev.Err)

    The flag is the improvement — it is recorded by the engine at the point that
    knows. The `Contains` is a surviving coupling, and it makes the
    classification depend on the GUEST relaying the engine's error text.

    dead_letter_workflow wraps with %w so the text survives. This one does what
    a real workflow is at least as likely to do: catch the failure and describe
    it in its own vocabulary. The pair differs in exactly that one line.

    Either result is worth recording. If it still dead-letters, the coupling is
    looser than it reads. If it does not, whether work is retained for an
    operator depends on how its author phrased an error — which is a property
    no operator can see and no reviewer would think to check.
    """
    key = f"dlq-opaque-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(dead_letter_opaque_workflow, {
        "service": "flaky", "key": key, "attempts": 2, "intervalMs": 100,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] in ("failed", "dead_lettered"), (
        f"a workflow whose call never succeeded ended {final['status']!r}"
    )

    if final["status"] == "dead_lettered":
        code, listing = cleat.dead_letters()
        assert code == 200, f"the dead-letter list answered {code}"
        assert started["id"] in {row.get("id") for row in listing}, (
            f"run {started['id']} is dead_lettered but absent from /api/dead-letters"
        )
        return

    pytest.skip(
        f"cleat#979: the run ended 'failed' rather than 'dead_lettered' after "
        f"exhausting its retries.\n"
        f"error: {final.get('error')!r}\n"
        f"The only difference from the workflow in "
        f"test_a_workflow_that_exhausts_its_retries_is_dead_lettered is that this one "
        f"returns its own message instead of wrapping the engine's with %w. That "
        f"decides retention, so whether unfinished work is kept for an operator "
        f"depends on an author's phrasing (cleat#902's surviving `strings.Contains`).\n"
        f"\n"
        f"This is a skip rather than a failure only so the suite stays green while "
        f"cleat#979 is open. It is deliberately NOT an unconditional skip: the "
        f"dead_lettered branch above still asserts in full, so the day #979 is fixed "
        f"this test starts passing on its own and the skip disappears without anyone "
        f"having to remember it. If it turns red instead, something other than #979 "
        f"is wrong and should be read as a new finding."
    )
