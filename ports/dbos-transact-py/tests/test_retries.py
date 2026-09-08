"""Durable-call retry semantics, ported from dbos-transact-py's failure tests.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS distinguishes retryable step failures from permanent ones: a step that
raises a retryable error is retried per its policy, one that raises a
non-retryable error is not. Cleat has the same distinction —
`RetryPolicy.NonRetryableErrors`, and error classes in `engine/callerrors.go` —
so the assertions port.

Both halves are covered. The retryable half needs a service that can be told to
fail a controlled number of times, which is what scripts/fixture-service.py is:
the worker forwards unrecognised service calls to it, and cleat classifies a 5xx
from that path as transient, so a policy applies to it.
"""

import json

import pytest

# Large enough that a single retry could not hide in scheduling noise: the
# measured no-retry path completes in ~220ms.
INTERVAL_MS = 2000

# Used only by test_a_permanently_failing_call_is_not_retried, which
# discriminates "was it retried" by wall clock and therefore needs the interval
# to dominate fixed overhead rather than merely exceed it. See that test.
PERMANENT_PROBE_INTERVAL_MS = 15000
ATTEMPTS = 5


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_permanently_failing_call_is_not_retried(cleat, retry_workflow):
    """A call that cannot ever succeed must not burn its retry budget.

    The fixture rejects a request with no `key` as a 400, and cleat classifies
    a 4xx from a forwarded service as PERMANENT (408 and 429 excepted). Retrying
    even once costs at least one interval; not retrying costs a few hundred ms.
    The wall clock is the discriminator.

    IT USES ITS OWN INTERVAL, much larger than the suite's, and that is the
    point rather than an inconsistency.

    This test previously used the shared INTERVAL_MS of 2000 and asserted the
    run finished inside it, on the reasoning that "the margin is wide rather
    than tight". It was not. On a slower machine the run took 2309ms WITHOUT
    retrying -- start-up, deploy check and HTTP round trips -- while one retry
    would have cost 2000ms plus that same overhead. The two hypotheses
    overlapped, so the assertion could no longer tell them apart and failed on
    the honest case.

    Measured when it failed: 2309ms observed for no-retry, against a ~2250ms
    floor for one-retry. A margin that is 8x on paper can be 0x in practice
    once fixed overhead is comparable to the thing being measured.

    With a 15s interval the floor for one retry is 15s and the no-retry case is
    hundreds of ms, so the two cannot overlap on any machine this suite runs
    on. A fully-retried run would take 4 x 15s = 60s, still inside
    await_terminal's 90s, so a real regression fails THIS assertion with its
    message rather than timing out with a vaguer one.

    The direct measurement is not available here: the fixture only produces a
    permanent 400 for a request with NO key, and it counts calls BY key, so
    fixture_calls cannot see this one. The sibling test below uses the counter
    precisely because it can.

    Note this cannot use an unresolvable service name any more. Once the
    harness sets --bench-svc-url, every unrecognised service is forwarded, so
    "no endpoint registered" is no longer reachable — the fixture answers for
    all of them.
    """
    import time

    started_at = time.monotonic()
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": "", "attempts": ATTEMPTS,
        "intervalMs": PERMANENT_PROBE_INTERVAL_MS, "failTimes": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    elapsed_ms = (time.monotonic() - started_at) * 1000

    assert final["status"] == "done", f"run did not complete: {final!r}"
    body = _body(final)
    assert body["outcome"] == "failed", (
        f"a request the fixture rejects with 400 did not fail: {body!r}"
    )
    assert elapsed_ms < PERMANENT_PROBE_INTERVAL_MS, (
        f"the run took {elapsed_ms:.0f}ms with a {PERMANENT_PROBE_INTERVAL_MS}ms retry interval "
        f"and MaxAttempts={ATTEMPTS}, so a permanent failure was retried. A call "
        "that cannot succeed should fail immediately rather than consume its "
        "budget."
    )


def test_a_permanent_failure_is_reached_exactly_once(cleat, retry_workflow, fixture_calls):
    """The direct evidence for the timing assertion above.

    Elapsed time shows no waiting happened; the call counter shows no repeat
    happened. A 4xx must be attempted once regardless of the budget, and this
    distinguishes "classified permanent" from "retried instantly", which the
    clock alone cannot.
    """
    import uuid

    key = str(uuid.uuid4())
    # fail_times is irrelevant: the fixture 400s on the malformed shape before
    # it consults the counter, so this key should record no calls at all... it
    # records one, because the request does reach the service and is rejected.
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": ATTEMPTS,
        "intervalMs": 200, "failTimes": 999,
    })
    assert status == 201
    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    # 999 failures against a budget of 5: transient, so it is retried to the
    # budget and no further.
    reached = fixture_calls(key)
    assert reached == ATTEMPTS, (
        f"the service was reached {reached} times for a budget of {ATTEMPTS}"
    )
    assert _body(final)["outcome"] == "failed"


def test_a_retryable_failure_is_retried_with_backoff(cleat, retry_workflow, fixture_calls):
    """The half that needed a fixture: a transient failure IS retried.

    The fixture returns 503 for the first `failTimes` calls bearing a key, and
    cleat classifies a 5xx from a forwarded service as transient, so the policy
    applies. Two independent pieces of evidence, because either alone is weak:
    the service was reached three times (the retry happened) AND the run took at
    least the configured backoff (the waiting happened).
    """
    import time
    import uuid

    key = str(uuid.uuid4())
    interval, failures = 400, 2

    started_at = time.monotonic()
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 5,
        "intervalMs": interval, "failTimes": failures,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=120.0)
    elapsed_ms = (time.monotonic() - started_at) * 1000

    assert final["status"] == "done", f"run did not complete: {final!r}"
    body = _body(final)
    assert body["outcome"] == "succeeded", (
        f"the call never succeeded despite a budget of 5 and only {failures} "
        f"deliberate failures: {body!r}"
    )

    reached = fixture_calls(key)
    assert reached == failures + 1, (
        f"the service was reached {reached} times, expected {failures + 1} "
        "(two failures then a success). A count of 1 means the transient "
        "failure was not retried at all."
    )

    assert elapsed_ms >= failures * interval * 0.8, (
        f"the run took {elapsed_ms:.0f}ms for {failures} retries at "
        f"{interval}ms, so the configured backoff was not applied. Note that "
        "RetryPolicy.MaxInterval must be set: the host clamps each wait to it, "
        "so leaving it at zero silently reduces every backoff to a 1ms floor."
    )


def test_the_retry_budget_is_finite(cleat, retry_workflow, fixture_calls):
    """A transient failure that never clears must still stop.

    Guards the test above against a policy that would retry forever: with more
    deliberate failures than the budget allows, the call must fail and the
    service must be reached exactly MaxAttempts times — not fewer, which would
    mean the budget was under-spent, and not more, which would mean it was
    ignored.
    """
    import uuid

    key = str(uuid.uuid4())
    attempts = 3

    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": attempts,
        "intervalMs": 200, "failTimes": 99,
    })
    assert status == 201
    final = cleat.await_terminal(started["id"], timeout=120.0)

    assert final["status"] == "done", f"run did not complete: {final!r}"
    assert _body(final)["outcome"] == "failed", (
        "a call that fails every time reported success"
    )
    reached = fixture_calls(key)
    assert reached == attempts, (
        f"the service was reached {reached} times for a budget of {attempts}"
    )

