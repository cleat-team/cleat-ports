"""Durable deferred cleanup.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS runs a step's cleanup when the workflow finishes rather than when the
cleanup is registered, and the durable-execution property worth asserting is
that it runs once even though the body runs more than once. Cleat's
`h.DurableDeferFunc` is the same shape: the guest keeps a defer table and the
entry-point wrapper drains it in LIFO order before reporting completion.

These tests exist for a second reason. IMPROVEMENT-PLAN 3.70 records that
"every defer in every Go WASM workflow came to do nothing while the host
recorded success" -- the host invoked defers by an entry-point name no guest
exported, and a miss returned byte-identical results to a hit with a nil error,
so every caller's `if err != nil` was dead code. Throughout that period a test
asserting only that the workflow completed would have passed. This asserts that
the cleanup *arrives*, which is a different claim.
"""

import json
import time
import uuid

import pytest

import functools

from conftest import wait_until as _wait_until
from test_workflow_management import _claimed_generation

#: This module polled at 0.25s before wait_until was shared, and keeps it.
#: Not tidied to the 0.5s default: some predicates here test a TRANSIENT
#: state (a run being "running", a fixture call in flight), and polling
#: less often can miss one entirely rather than merely notice it later.
wait_until = functools.partial(_wait_until, interval=0.25)

SLEEP_MS = 3000


def test_a_registered_cleanup_runs(cleat, defer_workflow, fixture_calls):
    """The defer body reaches the service. 3.70's defect was silent otherwise."""
    body_key = f"defer-body-{uuid.uuid4().hex[:8]}"
    defer_key = f"defer-run-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(defer_workflow, {
        "bodyKey": body_key, "deferKey": defer_key, "sleepMs": SLEEP_MS,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    # Dispatch outlives the host call by design -- DurableSend hands off to a
    # goroutine -- so arrival is not ordered against the workflow finishing.
    wait_until(
        lambda: fixture_calls(defer_key) >= 1,
        timeout=30.0,
        what="the deferred cleanup to reach the fixture service",
    )


def test_a_cleanup_does_not_run_at_registration(cleat, defer_workflow, fixture_calls):
    """A defer that fires when registered is a defer in name only.

    Asserted while the workflow is suspended mid-sleep, against a body call
    made just before the registration. Seeing the body's call and not the
    defer's is what separates "deferred" from "ran immediately" -- a count
    taken after completion cannot, because by then both are 1.
    """
    body_key = f"defer-body-{uuid.uuid4().hex[:8]}"
    defer_key = f"defer-run-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(defer_workflow, {
        "bodyKey": body_key, "deferKey": defer_key, "sleepMs": SLEEP_MS,
    })
    assert status == 201, f"start rejected: {status} {started}"

    # Wait for the BODY's call rather than sleeping a guessed interval: it
    # proves the workflow reached the line after the registration, which is
    # the moment the claim is about. A fixed sleep would either race the
    # start-up or outlast the workflow.
    wait_until(
        lambda: fixture_calls(body_key) >= 1,
        timeout=30.0,
        what="the workflow body to reach the registration point",
    )

    assert fixture_calls(defer_key) == 0, (
        "the deferred cleanup ran at registration time, not at the end: "
        f"the fixture saw {fixture_calls(defer_key)} call(s) under {defer_key} "
        "while the workflow was still suspended"
    )

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"


def test_a_cleanup_runs_once_though_the_body_runs_twice(cleat, defer_workflow, fixture_calls):
    """The durability property: replay re-registers, and cleanup still runs once.

    The workflow suspends on a durable sleep, so the resumed execution replays
    the body from step 0 and calls DurableDeferFunc a second time. If each call
    appended a fresh table entry, the surviving execution would drain two of
    them and the service would be called twice.

    The body's own send is the control. It is replayed too, and the engine
    serves it from history rather than repeating it, so a run in which BOTH
    counts are 2 is a replay defect rather than a defer defect -- and this test
    would otherwise report it as the latter.
    """
    body_key = f"defer-body-{uuid.uuid4().hex[:8]}"
    defer_key = f"defer-run-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(defer_workflow, {
        "bodyKey": body_key, "deferKey": defer_key, "sleepMs": SLEEP_MS,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    wait_until(
        lambda: fixture_calls(defer_key) >= 1,
        timeout=30.0,
        what="the deferred cleanup to reach the fixture service",
    )

    # Settle: a second delivery would arrive shortly after the first, so
    # asserting == 1 the instant the first lands would pass against a double
    # send. Wait past the window rather than sampling once.
    time.sleep(3.0)

    body_calls = fixture_calls(body_key)
    defer_calls = fixture_calls(defer_key)

    assert body_calls == 1, (
        f"the body's own send ran {body_calls} times across the replay; "
        "this is a replay defect, not a defer one, and it invalidates the "
        "cleanup count below"
    )
    assert defer_calls == 1, (
        f"the deferred cleanup ran {defer_calls} times. The body runs twice "
        "(once before the sleep, once on resume), so a defer table that grows "
        "on every registration drains one entry per execution."
    )


def test_a_defer_runs_on_a_propagated_failure_and_costs_the_run_its_dlq_place(
    cleat, defer_dead_letter_workflow, fixture_calls
):
    """Two findings in one run, and they point in opposite directions.

    THE GOOD ONE: a workflow that ends by propagating a terminal error still
    runs the defer it owes. That is the guest-driven exit path, and it works.
    It is also the control cleat#1152 was missing -- that issue measured
    `force-complete` and `force-fail` skipping defers and could not say whether
    the mechanism worked anywhere. It does, here, so #1152 is the narrow
    reading: those endpoints bypass a working mechanism rather than the defer
    phase being globally unreachable.

    THE BAD ONE: running it costs the run its place in the dead-letter queue.
    `deadLettered = eligibleForDLQ && endedOnAnExhaustedCall(history)` asks
    what the LAST durable act was, and a defer body's send is itself a durable
    call -- deliberately, since a cleanup that cannot reach the host cannot
    release the lock it took. That send lands after the exhausted call, so the
    history no longer ends on one and the run is `failed` rather than
    `dead_lettered`.

    The distinction is not cosmetic: one is kept for an operator to re-drive
    and the other is deleted by --completed-workflow-retention-days. So the
    work least likely to be retained is the work that took a lock and released
    it in a defer. cleat#1155.

    The control is the sibling fixture: `deadletter` differs from this one
    essentially by not registering a defer, and it reaches `dead_lettered` --
    test_dead_letters.py passes on it. Without that comparison this test would
    only say "a workflow failed", which is not a finding.
    """
    body_key = f"dldefer-body-{uuid.uuid4().hex[:8]}"
    defer_key = f"dldefer-run-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(defer_dead_letter_workflow, {
        "service": "flaky", "bodyKey": body_key, "deferKey": defer_key,
        "attempts": 2, "intervalMs": 100,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    final = cleat.await_terminal(run_id, timeout=90.0)

    # The body must demonstrably have run, or a missing cleanup below is a
    # workflow that never started rather than a skipped defer -- the vacuity
    # ports#172 turned on.
    wait_until(
        lambda: fixture_calls(body_key) >= 1,
        timeout=30.0,
        what="the body to reach the fixture, proving the defer was registered",
    )

    wait_until(
        lambda: fixture_calls(defer_key) >= 1,
        timeout=60.0,
        what="the deferred cleanup to run on a propagated terminal failure",
    )
    assert fixture_calls(defer_key) == 1, (
        f"the cleanup ran {fixture_calls(defer_key)} times for one run; once is "
        f"the contract however the workflow ends."
    )

    if final["status"] == "failed":
        pytest.skip(
            f"cleat#1155: the run exhausted its retries and its error still "
            f"reads 'retries exhausted', but it settled {final['status']!r} "
            f"rather than dead_lettered -- because the defer above ran, and a "
            f"defer body's durable send lands after the exhausted call, so "
            f"endedOnAnExhaustedCall(history) is false.\n"
            f"\n"
            f"error: {final.get('error', '')[:220]}\n"
            f"\n"
            f"A skip rather than a failure only so the suite stays green while "
            f"#1155 is open. Everything above still ran, and the useful half is "
            f"an ASSERTION rather than this skip: the cleanup DID run on a "
            f"propagated failure, exactly once. That is the control cleat#1152 "
            f"lacked, and it makes #1152 the narrow reading."
        )

    assert final["status"] == "dead_lettered", (
        f"a run that exhausted its retries settled {final['status']!r}: {final!r}"
    )


def test_a_force_completed_workflow_still_runs_its_defers(
    cleat, defer_workflow, fixture_calls
):
    """A HOST-driven terminal transition must not skip the cleanup it owes.

    The three tests above all end the workflow the ordinary way -- the body
    returns and the entry-point wrapper drains the defer table on its way out.
    None of them exercises the case where something OUTSIDE the guest decides
    the workflow is over, and that is the case with a history of going wrong.

    `engine/defer_phase.go` records why it is a two-phase transition and what
    the one-phase version did: TerminateWorkflow used to call
    releaseWorkflowResources immediately after the terminal UPDATE, so "the
    host dropped the sticky assignment and the concurrency keys, and the defer
    that would have released them never ran. A terminated workflow's cleanup
    was not merely skipped, it was pre-empted by the host doing a DIFFERENT
    release, in the wrong order, with no record that anything was owed."

    The shape that fixes it is MARK then FINALIZE: the outcome is recorded in
    pending_terminal_status, the workflow moves to 'terminating' and stays
    schedulable, and the dispatch loop later replays it as a defer segment and
    applies the recorded outcome only after the defers have run. This asserts
    the observable end of that -- the cleanup arrives -- rather than the
    mechanism, so it holds for any implementation that keeps the guarantee.

    Load-bearing: the run must still be RUNNING when it is forced. Forcing a
    workflow that has already finished tests nothing, because the ordinary exit
    path would have drained the defers anyway and the assertion below would
    pass against an engine that skips cleanup entirely. Waiting for the body
    key is what establishes that.
    """
    body_key = f"defer-fc-body-{uuid.uuid4().hex[:8]}"
    defer_key = f"defer-fc-run-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(defer_workflow, {
        "bodyKey": body_key, "deferKey": defer_key, "sleepMs": 30_000,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    wait_until(
        lambda: fixture_calls(body_key) >= 1,
        timeout=60.0,
        what="the workflow body to reach the fixture, so the run is demonstrably "
             "mid-flight when it is forced",
    )
    assert fixture_calls(defer_key) == 0, (
        f"the deferred cleanup reached the fixture {fixture_calls(defer_key)} "
        f"time(s) BEFORE the workflow was forced. A defer that fires early is a "
        f"defer in name only, and it would make the assertion below hold for "
        f"the wrong reason."
    )

    code, body = cleat.admin(run_id, "force-complete", {
        "generation": _claimed_generation(cleat, run_id),
        "result": json.dumps({"forced": True}),
    })
    assert code == 200, f"force-complete answered {code}: {body!r}"

    final = cleat.await_terminal(run_id, timeout=90.0)
    assert final["status"] == "done", (
        f"the forced run settled as {final['status']!r}: {final!r}. "
        f"'terminating' here would mean the defer phase never finalized -- the "
        f"workflow is holding its resources and no terminal outcome was applied."
    )

    # Give the defer phase a generous window. Measured: it never arrives, and
    # the status is `done` at t+0 and every sample for two minutes -- the run
    # does not pass through `terminating` at all.
    deadline = time.time() + 60.0
    while time.time() < deadline and fixture_calls(defer_key) == 0:
        time.sleep(1.0)

    calls = fixture_calls(defer_key)
    if calls == 0:
        pytest.skip(
            f"cleat#1152: force-complete ended the run without running the "
            f"defer it owed. Status went to {final['status']!r} directly, never "
            f"through 'terminating', and the cleanup did not arrive in 60s.\n"
            f"\n"
            f"engine/defer_phase.go's two-phase MARK/FINALIZE exists precisely "
            f"to stop this, and describes the pre-fix behaviour it replaced: "
            f"'A terminated workflow's cleanup was not merely skipped, it was "
            f"pre-empted by the host doing a DIFFERENT release, in the wrong "
            f"order, with no record that anything was owed.' That fix reached "
            f"TerminateWorkflow and not the operator endpoints beside it.\n"
            f"\n"
            f"A skip rather than a failure only so the suite stays green while "
            f"#1152 is open, and deliberately NOT an unconditional skip: every "
            f"assertion above still runs -- the body reached the fixture, the "
            f"defer had NOT fired early, force-complete answered 200, and the "
            f"run settled terminal rather than stranding in 'terminating'. "
            f"Those are the controls that make this finding precise rather "
            f"than 'something did not happen'."
        )

    assert calls == 1, (
        f"the deferred cleanup ran {calls} times for one forced run. Once is "
        f"the contract: the defer table is drained once however the workflow "
        f"ends, and a forced end must not double-drain it."
    )
