"""Delivery without LISTEN/NOTIFY, ported from dbos-transact-py's tests/test_failures.py.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream reference:
  test_notification_errors  tests/test_failures.py

Upstream drops DBOS's notification connection mid-run and asserts send/recv
still delivers. The property underneath is the portable one: **the system must
not DEPEND on the notification channel**, because the channel is exactly what
is missing when it fails.

Cleat's shape is the same in the part that matters. `pgNotify` writes
`SELECT pg_notify($1,'')` inside the transaction that delivers a signal or
makes a run ready (engine/store_notify.go), the worker holds a dedicated LISTEN
connection (cmd/cleat-worker/notify.go), and the dispatch loop selects over
that channel and a 500ms poll. NOTIFY is an accelerator; the poll is the
guarantee.

**Nothing else in this suite runs with it off.** `-notify-channel` defaults to
`cleat_dispatch`, so every other test has NOTIFY available and the poll merely
behind it. A regression that made cleat depend on NOTIFY -- a wake path that
stopped being reachable by polling -- would pass this suite completely.

WHY THE MECHANISM DIFFERS FROM UPSTREAM'S, deliberately.

Upstream kills the connection mid-flight. Doing that here would mean reaching
into PostgreSQL to `pg_terminate_backend` the LISTEN session, which needs a
database client the suite does not have and does not otherwise want: every
other test drives cleat over HTTP, and ISSUES 30 is the worked example of what
goes wrong when a port reads the database instead of the endpoint -- a claim
verified against `information_schema` that was false of what a client receives.

Starting the worker with the channel disabled asserts the same property at the
same place with none of that. What it does not cover is RECOVERY: pq.NewListener
reconnects on its own (10s minimum), and whether delivery is continuous across
a drop is a different question. Recorded here rather than left as an implied
gap.
"""

import json
import uuid

from conftest import wait_until


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_signal_is_delivered_with_notify_disabled(
    cleat, worker_without_notify, signal_pair, fixture_calls
):
    """The same delivery test_signals.py makes, with the accelerator removed.

    Deliberately the identical assertion rather than a weaker one: if this
    diverged from its sibling, a failure here would not tell you whether
    delivery broke or only this test's version of it did.
    """
    # Assert the flag actually took. The fixture sets an environment variable
    # and restarts a shell script; neither of those is the worker, and a
    # restart that silently kept the default channel would make everything
    # below a re-run of a test that already passes -- green, and evidence of
    # nothing.
    argv = worker_without_notify
    assert "-notify-channel=" in argv, (
        f"the worker under test does not carry -notify-channel=; its argv is "
        f"{argv!r}. Without that this asserts nothing the existing signal test "
        f"does not already assert.")

    receiver_name, sender_name = signal_pair
    key = f"nonotify-{uuid.uuid4().hex[:8]}"
    payload = f"payload-{uuid.uuid4().hex[:6]}"

    status, receiver = cleat.start(receiver_name, {"key": key, "timeoutMs": 60_000})
    assert status == 201, f"receiver start rejected: {status} {receiver}"
    target = receiver["id"]

    wait_until(
        lambda: fixture_calls(f"{key}-waiting") == 1,
        timeout=60.0,
        what="the receiver to reach its await (polling only, no NOTIFY)",
    )

    status, sender = cleat.start(sender_name, {"targetRunID": target, "payload": payload})
    assert status == 201, f"sender start rejected: {status} {sender}"
    sent = cleat.await_terminal(sender["id"], timeout=60.0)
    assert sent["status"] == "done", f"the sender did not complete: {sent!r}"
    assert _body(sent)["outcome"] == "sent", f"the sender reported {_body(sent)!r}"

    # No wall clock. The assertion is that delivery HAPPENS without NOTIFY, not
    # that it happens within some multiple of the poll interval -- a bound on
    # that would be measuring how loaded the machine is. The timeout below is a
    # harness limit, not the claim.
    final = cleat.await_terminal(target, timeout=120.0)
    assert final["status"] == "done", (
        f"the receiver did not complete with NOTIFY disabled: {final!r}. The "
        f"sender reported delivering, so the signal is in the database and "
        f"nothing woke the receiver to see it -- the poll is not carrying what "
        f"the notification channel usually carries.")

    body = _body(final)
    assert body["outcome"] == "signalled", (
        f"the receiver reported {body!r} with NOTIFY disabled. `timedout` here "
        f"means the wait ended on its own deadline rather than on the signal.")
    assert body["payload"] == payload, (
        f"payload did not survive delivery without NOTIFY: sent {payload!r}, "
        f"received {body['payload']!r}")


def test_a_workflow_starts_with_notify_disabled(cleat, worker_without_notify,
                                                fanout_workflow):
    """Dispatch itself, not only signal delivery.

    `pgNotify` is called on the ready path as well as the signal path
    (engine/store_lifecycle.go calls it in four places). A regression could
    leave signals reachable by polling while making a newly-started run wait
    for a notification that never comes, and the test above would still pass.
    """
    argv = worker_without_notify
    assert "-notify-channel=" in argv, f"worker argv lacks the flag: {argv!r}"

    # (n, ms, mode) -- the declared parameters; conftest.Cleat.start refuses a
    # payload missing any of them, which is how this was caught before it ran.
    status, started = cleat.start(fanout_workflow, {"n": 1, "ms": 200, "mode": 0})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=120.0)
    assert final["status"] == "done", (
        f"a workflow started with NOTIFY disabled did not run: {final!r}. "
        f"Nothing but the poll can pick it up, so this is the poll failing to "
        f"claim ready work.")
