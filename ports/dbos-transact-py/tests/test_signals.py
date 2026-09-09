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

from conftest import wait_until

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
    wait_until(
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


def test_polling_finds_nothing_before_a_signal_and_finds_it_after(
    cleat, poll_signal_pair, fixture_calls
):
    """PollSignal is non-blocking: it returns immediately, then sees a later signal.

    Both polls are asserted and the FIRST is the load-bearing one. A poll that
    always reported found=true would satisfy a test checking only the second,
    and one that always suspended would never reach the announcement at all.
    The pair separates "polling works" from "a signal eventually arrives".

    The workflow announces itself between the two polls, so this waits for that
    before sending. Without it the test races the workflow, and a signal
    arriving before the first poll makes that poll return true -- a failure
    about test timing rather than about the code.
    """
    poller, sender = poll_signal_pair
    key = f"poll-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(poller, {"key": key, "sleepMs": 4000})
    assert status == 201, f"start rejected: {status} {started}"

    # Wait for the first poll to have happened.
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if fixture_calls(f"{key}-polled") > 0:
            break
        time.sleep(0.2)
    else:
        pytest.fail(
            f"the poller never announced itself, so the first poll never completed. "
            f"A PollSignal that suspends instead of returning would look exactly like this."
        )

    payload = "sent-after-the-first-poll"
    status, sent = cleat.start(sender, {"targetRunID": started["id"], "payload": payload})
    assert status == 201, f"sender start rejected: {status} {sent}"
    cleat.await_terminal(sent["id"], timeout=30.0)

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the poller did not complete: {final.get('error') or final!r}"
    )

    body = _body(final)
    assert body["before"] is False, (
        f"the first poll reported a signal before one was sent: {body!r}"
    )
    assert body["after"] is True, (
        f"the second poll did not see a signal that had been delivered: {body!r}. "
        f"A poll that never records anything looks like this."
    )
    assert body["payload"] == payload, (
        f"the polled payload did not round-trip: {body!r}"
    )


def test_a_signal_goes_to_the_await_that_named_it_and_same_name_signals_queue_in_order(
    cleat, signal_order_workflow, fixture_calls
):
    """Signals are queued PER NAME, and within one name oldest-first.

    Ported from upstream's `test_send_recv`, whose assertion reads as an
    ordering claim and is not one. It sends `test1` on the default topic,
    `test2` on a named topic, then `test3` on the default, and expects
    `test2-test1-test3` back -- because the receiver reads the *named topic*
    first and the default queue afterwards. The result is not arrival order; it
    is per-name queues, each FIFO.

    Nothing here asserted that. `test_a_workflow_can_signal_another_and_the
    _payload_arrives` sends exactly one signal, so it cannot distinguish "the
    engine routes by name" from "the engine hands over whatever it has".

    The send order is what does the work: the `queued` signal is sent FIRST and
    the `topic` signal SECOND, so an engine that delivers earliest-arrived
    rather than what was asked for gives the first await `first-payload`, and
    this fails on the payload rather than on a count.
    """
    key = f"order-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(signal_order_workflow, {"key": key, "timeoutMs": 60_000})
    assert status == 201, f"start rejected: {status} {started}"
    target = started["id"]

    wait_until(
        lambda: fixture_calls(f"{key}-waiting") == 1,
        timeout=60.0,
        what="the receiver to reach its first await",
    )

    # Order matters and is the point. `queued` first, so it is already waiting
    # when the `topic` await is the one in progress.
    for name, payload in (("queued", "first"), ("topic", "only"), ("queued", "second")):
        code, body = cleat.signal(target, name, payload)
        assert code in (200, 202, 204), f"signal {name}={payload} rejected: {code} {body!r}"

    final = cleat.await_terminal(target, timeout=90.0)
    assert final["status"] == "done", f"the receiver did not complete: {final!r}"
    body = _body(final)
    assert body["outcome"] == "read", f"the receiver reported {body!r}"

    assert body["names"] == ["topic", "queued", "queued"], (
        f"the awaits were satisfied by {body['names']!r}. Each await named one "
        "signal; a name it did not ask for means delivery ignores the name."
    )
    assert body["payloads"][0] == "only", (
        f"the `topic` await received {body['payloads'][0]!r}, want 'only'. "
        "'first' here is the interesting failure: it means the engine handed "
        "over the earliest signal rather than the one the await named, which is "
        "exactly what upstream's test2-test1-test3 exists to rule out."
    )
    assert body["payloads"][1:] == ["first", "second"], (
        f"the two `queued` signals arrived as {body['payloads'][1:]!r}, want "
        "['first', 'second']. Within one name the oldest must come first; "
        "reversed means the queue is a stack."
    )
