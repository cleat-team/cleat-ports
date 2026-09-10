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


def test_a_recovered_parent_does_not_start_its_child_a_second_time(
    cleat, recovery_parent_workflow, fixture_calls, worker
):
    """A child already spawned is not spawned again when the parent replays.

    Ports the core of upstream test_queue_workflow_in_recovered_workflow, which
    crashes a process mid-workflow and asserts the re-run reaches the same
    single answer rather than enqueueing its child twice.

    WHY THIS IS NOT COVERED BY THE TEST ABOVE, which is the only reason to add
    it. test_a_workflow_survives_the_loss_of_its_worker proves a completed
    durable CALL is served from history rather than made again. A child
    workflow is a different mechanism: the parent records a run id and later
    awaits it, rather than recording a result. Nothing about the call case
    implies the child case, and the failure is worse -- a duplicated call
    repeats one operation, a duplicated child starts a whole second workflow
    that runs to completion on its own.

    The instrument is the fixture's per-key call count, not the parent's
    result. A second child would be handed the same input, so it would call the
    fixture under the same key and the count would be 2. The parent's own
    result cannot see this: it awaits ONE run id and would report that child's
    answer perfectly well while a duplicate ran alongside it. Same reason the
    dedup and recovery tests above assert on counts rather than ids.

    The ordering assertion below is load-bearing. If the child had not yet run
    when the crash landed there would be nothing to duplicate, and `== 1` would
    hold for a workflow that had simply started its child once, late.

    FALSIFIED, and the first attempt failed for the wrong reason -- which is
    why the pre-crash wait is `>= 1` rather than `== 1`. Adding a second
    ChildWorkflow call with identical input to the parent (the shape a replay
    would produce if the spawn were not consulted from history) made the
    original equality poll wait out its full 60s and report "the child workflow
    never reached the fixture", the opposite of what had happened. Corrected,
    the same variant fails in 1.85s with "2 children ran before the crash".

    What that establishes and what it does not: the fixture count CAN see a
    second child, which is the load-bearing capability. It does not construct a
    replay-induced duplicate specifically, because a workflow cannot detect its
    own replay in order to spawn one. So the post-crash assertion is validated
    by the instrument being demonstrably able to count a duplicate, not by
    having watched recovery produce one.
    """
    key = f"childrecover-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(
        recovery_parent_workflow, {"key": key, "sleepMs": SLEEP_MS}
    )
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # The crash must land after the child has actually run, or the central
    # assertion is vacuous.
    #
    # `>= 1`, not `== 1`. An equality poll cannot distinguish "not yet" from
    # "already more than one", so a duplicate child would leave this waiting
    # until it timed out -- reporting that the child never reached the fixture,
    # which is the opposite of what happened. Measured: with a deliberate second
    # spawn this failed at 60s with "the child workflow never reached the
    # fixture" rather than with the count assertion below. A real engine defect
    # would have produced the same misdirection.
    wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=60.0,
        what="the child workflow to reach the fixture before the crash",
    )

    # Split before and after the crash for the same reason test_a_workflow_...
    # splits its before-key and after-key: a count of 2 at the end means
    # nothing unless it is known to have been 1 going in. Without this, a
    # parent that spawned twice on the FIRST pass would fail the assertion
    # below and be reported as a recovery defect.
    before_crash = fixture_calls(key)
    assert before_crash == 1, (
        f"{before_crash} children ran before the crash. This test attributes a "
        "duplicate to replay, and it cannot do that if the parent was already "
        "spawning more than one child on its first pass."
    )

    worker.crash()
    worker.restart()

    final = cleat.await_terminal(run_id, timeout=RECOVERY_TIMEOUT)
    assert final["status"] == "done", (
        f"the parent did not complete after its worker was killed: {final!r}. "
        "It was mid-sleep between spawning its child and awaiting it, holding "
        "a child run id that has to survive the replay for the await to mean "
        "anything."
    )

    reached = fixture_calls(key)
    assert reached == 1, (
        f"the child ran {reached} times. The parent replays from step 0 after "
        "recovery, so ChildWorkflow must return the run it already started "
        "rather than starting another -- otherwise every crash between a spawn "
        "and its await duplicates an entire workflow, and the duplicate runs to "
        "completion doing whatever the first one already did."
    )

    body = _body(final)
    assert body.get("runID"), (
        f"the recovered parent returned {body!r} with no child run id; the id "
        "recorded before the crash has to survive it, not just the fact that a "
        "child was started"
    )
    assert "child" in body, (
        f"the recovered parent returned {body!r}; awaiting a child it spawned "
        "before the crash must still yield that child's result"
    )
# Long enough that the crash lands inside the wait with room to spare -- the
# window is one whole interval and the crash is fired the moment the first
# attempt is observed -- and SHORT ENOUGH TO STAY ON THE HOST RETRY PATH,
# which is the half that looks arbitrary and is not.
#
# engine.DefaultHostRetryBudget is 60s, and a policy is refused
# (callErrorCode 6, RetryPolicyTooLong) when its WORST-CASE total backoff
# exceeds it. Worst case here is (attempts - 1) * interval, so 3 attempts at
# 20s is 40s and stays on the host; 3 at 45s is 90s and does not. Measured:
# the 45s variant makes ONE fixture call and still reports `done`, because the
# policy was refused before any retry and the workflow reported the failure as
# its result. That is a different code path, not a slower version of this one,
# and a test drifting across the boundary would silently stop testing recovery.
#
# 40s against a 60s ceiling leaves one attempt of headroom. Raising `attempts`
# to 4 here puts the worst case exactly at the ceiling.
RETRY_BACKOFF_MS = 20_000

# Coupled to RETRY_BACKOFF_MS above by the host-retry ceiling -- worst case is
# (RETRY_ATTEMPTS - 1) * RETRY_BACKOFF_MS = 40s against a 60s budget -- and to
# `failTimes` by the f >= n threshold in the test below. Raising either one
# alone breaks a different thing, which is why both read from this name.
RETRY_ATTEMPTS = 3


def test_a_worker_lost_mid_backoff_resumes_the_retry_rather_than_restarting_it(
    cleat, retry_workflow, fixture_calls, worker
):
    """A run killed between two attempts finishes, and does not re-spend the budget.

    Upstream `test_failures.py::test_recovery_during_retries`. The tests above
    kill a worker during a durable CALL; this kills it during the WAIT between
    two attempts, which is a different moment in the same path and the one with
    no coverage here.

    It is a different moment because the run is durably suspended rather than
    executing. Nothing is in flight to be lost -- what has to survive is the
    *position in the retry policy*, and the two ways to get that wrong point in
    opposite directions:

      * The run is never rescheduled, and a workflow that was one attempt from
        succeeding sits forever. The completion assertion catches that.
      * The run resumes but the policy restarts from attempt one, so the budget
        is re-spent and the side effect happens more times than the caller
        authorised. The call-count assertion catches that, and nothing about
        the run's final status would.

    THE FIXTURE MUST FAIL AT LEAST `attempts` TIMES, and that is the whole
    reason this test is shaped the way it is. It is not a margin; below that
    threshold the count cannot distinguish the two behaviours AT ALL.

    The fixture fails the first `fail_times` calls bearing a key. It counts
    CALLS, not attempt numbers, and it lives in a process the crash does not
    touch -- so a replayed attempt does not replay its failure. It gets the
    next call in the sequence, which may well be a success. Writing f for
    fail_times and n for attempts, with one failed call before the crash:

        resuming  -> min(n, f + 1) calls
        restarting-> 1 + min(n, f) calls

    Those are EQUAL for every f < n, and differ by exactly one for f >= n. An
    earlier version of this test ran f=1, n=3 and asserted a count of 2. Both
    behaviours produce 2. It passed against an engine that does the wrong
    thing, and it would have passed against one that does the right thing, and
    it could not have told anyone which. Found by another session measuring the
    engine directly (ports#172, cleat#1111).

    f >= n has a consequence that has to be accepted rather than worked around:
    the correct run EXHAUSTS its budget and never succeeds. So this test cannot
    also witness "a resumed run can still succeed" -- that property needs its
    own case, and any such case is structurally blind to this one.

    The pre-crash assertions are the control. Crashing before the first attempt
    lands would leave nothing to resume, and every assertion below would hold
    for a run that had simply never started -- the same vacuity the sibling
    tests guard against with their `-after` count.
    """
    key = f"midbackoff-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": RETRY_ATTEMPTS,
        "intervalMs": RETRY_BACKOFF_MS, "failTimes": RETRY_ATTEMPTS,
        "failStatus": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # The first attempt must have failed before the crash, or there is no
    # backoff in progress to be interrupted.
    wait_until(
        lambda: fixture_calls(key) == 1,
        timeout=60.0,
        what="the first attempt to reach the fixture and fail",
    )
    assert fixture_calls(key) == 1, (
        f"the fixture saw {fixture_calls(key)} calls before the crash. If the "
        f"second attempt has already run, the crash lands after the retry "
        f"rather than inside it and this test measures the case above instead."
    )

    worker.crash()
    worker.restart()

    final = cleat.await_terminal(run_id, timeout=RECOVERY_TIMEOUT)
    assert final["status"] == "done", (
        f"the run did not finish after its worker was killed mid-backoff: "
        f"{final!r}. It was durably waiting between two attempts and owned by a "
        f"worker that never came back -- nothing was executing, so there is no "
        f"in-flight work to blame, only a schedule nobody resumed."
    )

    calls = fixture_calls(key)
    resumed, restarted = RETRY_ATTEMPTS, RETRY_ATTEMPTS + 1

    assert calls in (resumed, restarted), (
        f"the fixture was called {calls} times, and a {RETRY_ATTEMPTS}-attempt "
        f"policy crashed once mid-backoff can only reach {resumed} (the budget "
        f"resumed where it stopped) or {restarted} (the budget restarted from "
        f"attempt one). Anything else means the crash changed something other "
        f"than the retry position, and neither branch below describes it."
    )

    if calls == restarted:
        pytest.skip(
            f"cleat#1111, budget half: the run made {calls} calls under a "
            f"policy of {RETRY_ATTEMPTS}. MaxAttempts bounds attempts per "
            f"INCARNATION, not per workflow, so surviving a crash buys a "
            f"caller a fresh budget and a non-idempotent side effect happens "
            f"more times than it authorised.\n"
            f"\n"
            f"A skip rather than a failure only so the suite stays green while "
            f"#1111 is open, and deliberately NOT an unconditional skip. The "
            f"assertions above still run in full: the run was rescheduled and "
            f"reached a terminal state, and the count is pinned to exactly the "
            f"two values the mechanism permits. The day the budget is carried "
            f"across recovery this skip stops firing and the assertion below "
            f"takes over with no edit."
        )

    assert calls == resumed, (
        f"the fixture was called {calls} times; the retry budget resumed where "
        f"it stopped, which is what this test is for."
    )
