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

SLEEP_MS = 3000


def _wait_until(predicate, timeout: float, what: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


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
    _wait_until(
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
    _wait_until(
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

    _wait_until(
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
