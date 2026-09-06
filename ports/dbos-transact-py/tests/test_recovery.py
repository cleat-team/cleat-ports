"""Recovery after a worker dies mid-workflow.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS asserts that a workflow interrupted by the loss of its executor resumes
and that already-completed steps are not run again — the `recovery_count`
assertions in its failure and management tests. That is the same promise cleat
makes, so the assertions port directly.

This is the property the whole engine exists for, and it is the one a test
suite can most easily *appear* to cover without covering: a workflow that
finishes after a restart proves resumption, and says nothing about whether the
work in front of the interruption was repeated. Repeating it is the failure
that costs money — the charge taken twice, the mail sent twice — so the call
count, not the final status, is the assertion that matters.

Cleat's mechanism: a worker heartbeats the workflows it owns, and a reaper
reclaims instances whose heartbeat has gone stale. With default settings the
reaper runs every 10s and treats a heartbeat older than 10s as stale, so
recovery here is on the order of 10-30s rather than instant. The timeouts
below are sized for that and are not arbitrary.
"""

import json
import time
import uuid

import pytest

# Long enough that the crash lands inside it AND the reaper has time to notice
# the dead worker before the sleep would have ended on its own. If the sleep
# finished first, a workflow could complete without ever being recovered and
# the test would pass while testing nothing.
SLEEP_MS = 45_000

# The reaper needs the heartbeat to go stale (10s) and then to run (every 10s),
# then the reclaimed workflow has to be picked up and replayed.
RECOVERY_TIMEOUT = 180.0


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _wait_until(predicate, timeout: float, what: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


def test_a_workflow_survives_the_loss_of_its_worker(
    cleat, recovery_workflow, fixture_calls, worker
):
    """The workflow completes, and the step before the crash is not repeated.

    Both halves are asserted because either alone is satisfiable by a broken
    engine: an engine that never recovers passes the "not repeated" half
    trivially, and an engine that recovers by re-running everything from the
    start passes the "completes" half.
    """
    key = f"recovery-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(recovery_workflow, {"key": key, "sleepMs": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # Wait for the first call to actually land, so the crash is known to happen
    # AFTER it. Crashing before it would leave nothing to be repeated and the
    # central assertion would hold vacuously.
    _wait_until(
        lambda: fixture_calls(f"{key}-before") == 1,
        timeout=60.0,
        what="the pre-crash durable call to reach the fixture",
    )
    assert fixture_calls(f"{key}-after") == 0, (
        "the post-crash call happened before the crash; the sleep is too short "
        "to hold the workflow open, and this test would prove nothing"
    )

    worker.crash()
    worker.restart()

    final = cleat.await_terminal(run_id, timeout=RECOVERY_TIMEOUT)
    assert final["status"] == "done", (
        f"the workflow did not complete after its worker was killed: {final!r}. "
        "It was mid-sleep and owned by a worker that never came back, which is "
        "the state the reaper exists to resolve."
    )

    assert fixture_calls(f"{key}-before") == 1, (
        f"the durable call before the crash was made "
        f"{fixture_calls(f'{key}-before')} times. Recovery replays the workflow "
        "body from step 0, and a completed call must be served from history "
        "rather than made again -- otherwise every crash duplicates whatever "
        "the workflow had already done."
    )
    assert fixture_calls(f"{key}-after") == 1, (
        "the durable call after the crash was not made exactly once; the "
        "workflow reported done without doing the work in front of it"
    )

    body = _body(final)
    assert "before" in body and "after" in body, (
        f"the recovered run returned {body!r}; the result of the pre-crash call "
        "must survive the crash too, not just the fact that it happened"
    )
