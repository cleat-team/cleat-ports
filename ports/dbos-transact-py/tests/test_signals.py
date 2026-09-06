"""Signal-await timeouts.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS's `recv` takes a timeout and returns None when nothing arrives. Cleat's
`DurableAwaitSignals` is the same shape, returning a timedOut flag.

This test earned its place by being the control that made cleat#814
diagnosable. The promise await and the signal await are written the same way --
record the await, suspend with `Until = now + timeout` -- so the question was
whether the promise defect was shared or particular. Running this said: the
signal await comes back `timedout` at generation 2, while the promise await was
at generation 31 and climbing. That contrast turned "promises hang" into "the
promise path is missing a timeout report the signal path has", which is a
different and much smaller problem.

Keeping it means the next person asking that question gets the answer for free
instead of writing the probe again.
"""

import json
import time
import uuid

import pytest

# Short: the assertion is that the timeout fires at all, and a long one only
# makes the suite slower without making the claim stronger.
TIMEOUT_MS = 5000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_signal_await_times_out_when_nothing_arrives(cleat, signal_timeout_workflow):
    status, started = cleat.start(signal_timeout_workflow, {"timeoutMs": TIMEOUT_MS})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", (
        f"a workflow waiting for a signal nobody sends did not complete: {final!r}. "
        "The timeout is the only thing that can end this wait."
    )

    body = _body(final)
    assert body["outcome"] == "timedout", (
        f"outcome was {body!r}. A signal await that neither receives nor times "
        "out leaves the workflow waiting forever, which is what cleat#814 was "
        "on the promise side."
    )


def _wait_until(predicate, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


def test_a_workflow_can_signal_another_and_the_payload_arrives(
    cleat, signal_pair, fixture_calls
):
    """The cross-workflow path, which is where promises were entirely broken.

    A sender returning success proves nothing on its own -- the promise settler
    ran to completion, reported `{"settled":"resolved"}`, and had no effect at
    all, for three defects in a row. So the assertion is the RECEIVER's result:
    it must come back `signalled`, with the payload the sender was given.
    """
    receiver_name, sender_name = signal_pair
    key = f"sig-{uuid.uuid4().hex[:8]}"
    payload = f"payload-{uuid.uuid4().hex[:6]}"

    status, receiver = cleat.start(receiver_name, {"key": key, "timeoutMs": 60_000})
    assert status == 201, f"receiver start rejected: {status} {receiver}"
    target = receiver["id"]

    # Only signal once the receiver is known to be waiting. Delivery to a run
    # that has not reached its await is a different question -- whether an
    # early signal is held -- and mixing them would leave a failure unable to
    # say which case broke.
    _wait_until(
        lambda: fixture_calls(f"{key}-waiting") == 1,
        timeout=60.0,
        what="the receiver to reach its await",
    )

    status, sender = cleat.start(sender_name, {"targetRunID": target, "payload": payload})
    assert status == 201, f"sender start rejected: {status} {sender}"
    sent = cleat.await_terminal(sender["id"], timeout=60.0)
    assert sent["status"] == "done", f"the sender did not complete: {sent!r}"
    assert _body(sent)["outcome"] == "sent", f"the sender reported {_body(sent)!r}"

    final = cleat.await_terminal(target, timeout=90.0)
    assert final["status"] == "done", (
        f"the receiver did not complete: {final!r}. It was waiting on a signal "
        "the sender reported delivering."
    )

    body = _body(final)
    assert body["outcome"] == "signalled", (
        f"the receiver reported {body!r}. `timedout` here means the sender "
        "succeeded and delivered nothing, which is exactly how promise "
        "settlement failed before cleat#813."
    )
    assert body["payload"] == payload, (
        f"the payload did not survive delivery: sent {payload!r}, received "
        f"{body['payload']!r}. A signal that arrives empty wakes the waiter and "
        "loses what it was waiting for."
    )
    assert body["name"] == "go", f"the signal name did not survive: {body!r}"
