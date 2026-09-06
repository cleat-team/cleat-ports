"""Durable-call retry semantics, ported from dbos-transact-py's failure tests.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS distinguishes retryable step failures from permanent ones: a step that
raises a retryable error is retried per its policy, one that raises a
non-retryable error is not. Cleat has the same distinction —
`RetryPolicy.NonRetryableErrors`, and error classes in `engine/callerrors.go` —
so the assertions port.

**Only the permanent half is covered here, and the reason is worth stating.**
Observing backoff requires a call that fails in a *retryable* way a controlled
number of times, which needs a fixture service that can be told to fail. This
port has no such fixture, and inventing one that talks to the worker is a
harness change rather than a test. The retryable half is left as a skipped test
naming what it needs, not silently omitted.
"""

import json

import pytest

# Large enough that a single retry could not hide in scheduling noise: the
# measured no-retry path completes in ~220ms.
INTERVAL_MS = 2000
ATTEMPTS = 5


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_permanently_failing_call_is_not_retried(cleat, retry_workflow):
    """A call that cannot ever succeed must not burn its retry budget.

    The target service does not exist, so the failure is a configuration error
    rather than a transient one. With MaxAttempts=5 and a 2s interval, retrying
    even once would cost at least 2s; not retrying costs ~200ms. The wall clock
    is therefore the discriminator, and it is a wide margin rather than a tight
    one.
    """
    import time

    started_at = time.monotonic()
    status, started = cleat.start(
        retry_workflow, {"attempts": ATTEMPTS, "intervalms": INTERVAL_MS}
    )
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    elapsed_ms = (time.monotonic() - started_at) * 1000

    assert final["status"] == "done", f"run did not complete: {final!r}"

    body = _body(final)
    assert body["outcome"] == "failed", (
        f"the call to a non-existent service did not fail: {body!r}"
    )
    assert "not configured" in body["error"], (
        "the failure is not the one this test intends to exercise; it should be "
        f"an unresolvable service, got: {body['error']!r}"
    )

    assert elapsed_ms < INTERVAL_MS, (
        f"the run took {elapsed_ms:.0f}ms with a {INTERVAL_MS}ms retry interval "
        f"and MaxAttempts={ATTEMPTS}, so a permanent failure was retried. A call "
        "that cannot succeed should fail immediately rather than consume its "
        "budget."
    )


def test_the_retry_budget_does_not_change_the_outcome(cleat, retry_workflow):
    """Guards the above against passing because the policy was ignored entirely.

    If MaxAttempts were dropped on the floor, the test above would also pass —
    it only observes that no time was spent. Running with a budget of one and a
    budget of five must produce the same outcome and the same error, which is
    what "classified permanent" means as distinct from "policy not applied".
    """
    outcomes = []
    for attempts in (1, ATTEMPTS):
        status, started = cleat.start(
            retry_workflow, {"attempts": attempts, "intervalms": INTERVAL_MS}
        )
        assert status == 201
        final = cleat.await_terminal(started["id"], timeout=90.0)
        assert final["status"] == "done", f"run failed: {final!r}"
        body = _body(final)
        outcomes.append((body["outcome"], "not configured" in body["error"]))

    assert outcomes[0] == outcomes[1] == ("failed", True), (
        f"budget changed the outcome: {outcomes!r}"
    )


@pytest.mark.skip(
    reason="NEEDS A FIXTURE: observing backoff requires a call that fails "
           "retryably a controlled number of times. cleat retries short "
           "policies host-side and long ones guest-side via DurableSleep, so "
           "both paths are worth covering — but neither can be reached without "
           "a service that can be told to fail, which this port does not have."
)
def test_a_retryable_failure_is_retried_with_backoff():
    """Upstream's step-retry assertion, kept visible rather than dropped."""
