"""Fire-and-forget sends.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS's `send` delivers a message without waiting for a reply, and the engine
property worth asserting is that it is delivered exactly once even though the
workflow body runs more than once. Cleat's `h.DurableSend` is the same shape:
the host records an event and dispatches in a goroutine, and skips the call on
replay.

These tests exist for a second reason. `h.DurableSend` was unreachable from a Go
workflow until cleat#806 — a public method and a host export with nothing
between them. That fix was verified at the import section of the compiled
binary, which shows the call can be *made*. Whether it *arrives* is a different
claim, and this is the test that makes it.
"""

import json
import time
import uuid

import pytest

SLEEP_MS = 3000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _wait_until(predicate, timeout: float, what: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


def test_a_fire_and_forget_send_reaches_the_service(cleat, send_workflow, fixture_calls):
    """The send arrives, which the import-section check in cleat#806 cannot show."""
    key = f"send-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(send_workflow, {"key": key, "sleepMs": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    # The dispatch outlives the host call by design -- it runs in a goroutine --
    # so arrival is not ordered against the workflow finishing.
    _wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=30.0,
        what="the fire-and-forget send to reach the fixture service",
    )


def test_a_send_is_not_repeated_when_the_workflow_replays(
    cleat, send_workflow, fixture_calls
):
    """Exactly once, across a suspension that replays the body from step 0.

    The workflow sleeps after sending, so the resumed execution re-runs the send
    statement. A count of 2 would mean every suspension duplicates every message
    a workflow had already sent.
    """
    key = f"send-once-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(send_workflow, {"key": key, "sleepMs": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    _wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=30.0,
        what="the send to reach the fixture service",
    )

    # Settle: a duplicate dispatched by the replaying execution would arrive
    # after the first, so checking immediately could read 1 and miss it.
    time.sleep(2.0)

    assert fixture_calls(key) == 1, (
        f"the send was delivered {fixture_calls(key)} times across one "
        "suspension. The workflow body ran twice -- once before the sleep and "
        "once on replay after it -- and the send must be served from history "
        "the second time."
    )


def test_a_send_after_a_suspension_still_arrives(cleat, send_after_sleep_workflow, fixture_calls):
    """The half of `send` that a durable engine has to get right.

    DBOS's send is available anywhere in a workflow, including after a step
    that made it wait, and a send that a resumed run silently drops is worse
    than one that fails: the history records that it happened.

    Both keys are asserted, and the early one is why. It is the same call in
    the same workflow, differing only in which side of the suspension it falls
    on -- so if the late send is missing while the early one arrived, the
    difference is the suspension and nothing else. A test that asserted only
    the late send could not tell "sends after a sleep are dropped" from "the
    fixture is down".

    cleat#835: DurableSend's replay branch returned success for a step past the
    end of recorded history without recording an event or dispatching. Measured
    before the fix: 0 arrivals in 3 runs for the late send, 3 of 3 for the
    early one.
    """
    early = f"early-{uuid.uuid4().hex[:8]}"
    late = f"late-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(send_after_sleep_workflow, {
        "earlyKey": early, "lateKey": late, "sleepMs": SLEEP_MS,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    _wait_until(
        lambda: fixture_calls(early) >= 1,
        timeout=30.0,
        what="the send made before the suspension to reach the fixture service",
    )
    _wait_until(
        lambda: fixture_calls(late) >= 1,
        timeout=30.0,
        what="the send made after the suspension to reach the fixture service",
    )
