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

from conftest import wait_until

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
    wait_until(
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


def test_an_idempotency_key_survives_the_loss_of_its_worker(
    cleat, recovery_workflow, fixture_calls, worker
):
    """Deduplication and recovery are tested separately; this is the interaction.

    test_the_same_idempotency_key_starts_one_run proves a repeat start is
    deduplicated. test_a_workflow_survives_the_loss_of_its_worker proves an
    interrupted run resumes without repeating completed work. Neither says what
    happens when a caller retries a submission whose worker died mid-run --
    which is not a contrived case but the ordinary one, because a client that
    sees no response is exactly a client that will retry.

    The failure that costs money is specific: if the key does not survive, the
    retry starts a SECOND run, and the durable call in front of the crash
    executes twice. That is the same charge-taken-twice failure the recovery
    test exists for, reached by a different route -- and neither existing test
    can see it, because one never crashes and the other never retries.

    Asserted on the call counts rather than on the ids, for the reason given in
    the dedup test: returning the original id while executing the body twice is
    the failure that matters, and the id alone cannot see it.
    """
    key = f"dedup-recover-{uuid.uuid4().hex[:8]}"
    idem = f"idem-recover-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(
        recovery_workflow, {"key": key, "sleepMs": SLEEP_MS}, idempotency_key=idem
    )
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # The crash must land AFTER the first durable call, or there is nothing in
    # front of the interruption and the central assertion holds vacuously --
    # the same precondition the plain recovery test makes explicit.
    wait_until(
        lambda: fixture_calls(f"{key}-before") == 1,
        timeout=60.0,
        what="the pre-crash durable call to reach the fixture",
    )
    assert fixture_calls(f"{key}-after") == 0, (
        "the post-crash call happened before the crash; the sleep is too short "
        "to hold the workflow open and this test would prove nothing"
    )

    worker.crash()
    worker.restart()

    # Retry the submission while the original is still owned by a dead worker.
    # This is the window that matters: the run exists, is not finished, and its
    # owner is gone. A key that is cleaned up with the claim rather than with
    # the run would be absent exactly here.
    status_retry, retried = cleat.start(
        recovery_workflow, {"key": key, "sleepMs": SLEEP_MS}, idempotency_key=idem
    )

    assert retried.get("workflow_id") == run_id, (
        f"the retry created a different run: original={run_id!r} retry={retried!r}.\n"
        f"The idempotency key did not survive the loss of the worker, so a client "
        f"that retried after a timeout has started the job a second time. The "
        f"durable call in front of the crash will now run twice."
    )
    assert status_retry == 200, (
        f"the retry answered {status_retry}, not 200. 201 would mean 'created', "
        f"which is the failure above: {retried!r}"
    )

    final = cleat.await_terminal(run_id, timeout=RECOVERY_TIMEOUT)
    assert final["status"] == "done", (
        f"the run did not complete after its worker was killed and the "
        f"submission was retried: {final!r}"
    )

    assert fixture_calls(f"{key}-before") == 1, (
        f"the pre-crash call ran {fixture_calls(f'{key}-before')} times. Once is "
        f"the durable-execution guarantee; more than once means the retry "
        f"re-executed work that was already complete."
    )
    assert fixture_calls(f"{key}-after") == 1, (
        f"the post-crash call ran {fixture_calls(f'{key}-after')} times, not once. "
        f"More than one means two runs reached the end of the workflow, so the "
        f"deduplication reported above was not real."
    )
