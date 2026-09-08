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


def test_a_failure_that_never_stops_is_retried_to_the_budget(cleat, retry_workflow, fixture_calls):
    """A 503 on every attempt is retried exactly MaxAttempts times.

    RENAMED. This was `test_a_permanent_failure_is_reached_exactly_once`, and
    its docstring read "A 4xx must be attempted once regardless of the budget".
    It measured neither. The key is a valid uuid, so the fixture never takes its
    `key is required` 400 branch (scripts/fixture-service.py); with
    fail_times=999 every attempt is a 503, which cleat classifies TRANSIENT. The
    assertion below -- reached == ATTEMPTS -- is correct and always was. The
    name and docstring described the opposite case.

    Two comments inside the old body contradicted each other, one saying "it
    records one" and the other "retried to the budget", which is how the
    mismatch surfaced. Both were written by reasoning about the fixture rather
    than reading it; the assertion followed one and the name followed the other.

    Why the rename mattered enough to do first: permanent classification had NO
    call-count evidence anywhere, only the wall-clock test above -- the one
    whose margin already failed once at 2309ms against a ~2250ms floor. A test
    named as though the direct evidence existed is exactly what stopped anyone
    noticing it did not. test_a_permanent_status_is_attempted_once now supplies
    it.
    """
    import uuid

    key = str(uuid.uuid4())
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": ATTEMPTS,
        "intervalMs": 200, "failTimes": 999,
    })
    assert status == 201
    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

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



# The two tests below pin the retry budget from both sides of its boundary.
#
# test_the_retry_budget_is_finite above uses failTimes=99 -- far more failures
# than the budget -- which proves the budget is finite but says nothing about
# where it ends. A policy that granted 2 attempts and one that granted 4 both
# pass it. That is the same weakness as asserting a threshold without checking
# the statistic can separate the hypotheses: the test excludes "infinite" and
# admits every finite value.
#
# Run as a pair they locate the edge exactly. With MaxAttempts = N:
#
#   failTimes = N-1   the last permitted attempt succeeds   -> succeeded, N calls
#   failTimes = N     the last permitted attempt fails      -> failed,    N calls
#
# An off-by-one in either direction breaks exactly one of them, which is what
# makes the pair worth more than either alone. A budget of N-1 fails the first
# (the call never gets its winning attempt); a budget of N+1 fails the second
# (the service is reached N+1 times and the workflow reports success).
#
# Both assert the call count as well as the outcome, because the two can
# disagree: a workflow can report failure having spent fewer attempts than its
# budget, and the outcome alone would not show it.

BUDGET = 3


def test_a_call_that_succeeds_on_its_last_permitted_attempt_succeeds(
    cleat, retry_workflow, fixture_calls
):
    """failTimes = BUDGET-1, so the final attempt is the one that works.

    The boundary case a budget is most likely to get wrong: spending the last
    attempt is legitimate, and a policy that stops one short would fail a call
    that was about to succeed. That failure mode is invisible against
    failTimes=99, where the call was never going to succeed anyway.
    """
    import uuid

    key = str(uuid.uuid4())
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": BUDGET,
        "intervalMs": 200, "failTimes": BUDGET - 1,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=120.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    body = _body(final)
    assert body["outcome"] == "succeeded", (
        f"a call that fails {BUDGET - 1} times within a budget of {BUDGET} "
        f"reported {body['outcome']!r}. The winning attempt is the last one the "
        f"policy permits, so a budget that stops one short looks exactly like "
        f"this. error: {body.get('error')!r}"
    )

    reached = fixture_calls(key)
    assert reached == BUDGET, (
        f"the service was reached {reached} times; expected exactly {BUDGET} "
        f"({BUDGET - 1} failures then the success). Fewer means the call "
        f"succeeded earlier than the fixture was told to allow; more means the "
        f"successful attempt was retried."
    )


def test_a_call_that_fails_on_its_last_permitted_attempt_fails(
    cleat, retry_workflow, fixture_calls
):
    """failTimes = BUDGET, one more failure than the budget can absorb.

    The other side of the same edge. Together with the test above this pins
    MaxAttempts to exactly BUDGET: that one shows attempt BUDGET is spent, this
    one shows attempt BUDGET+1 is not.
    """
    import uuid

    key = str(uuid.uuid4())
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": BUDGET,
        "intervalMs": 200, "failTimes": BUDGET,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=120.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    body = _body(final)
    assert body["outcome"] == "failed", (
        f"a call that fails {BUDGET} times within a budget of {BUDGET} reported "
        f"{body['outcome']!r} -- the budget granted at least one attempt more "
        f"than it should have"
    )

    reached = fixture_calls(key)
    assert reached == BUDGET, (
        f"the service was reached {reached} times for a budget of {BUDGET}. "
        f"More than {BUDGET} means the policy over-spent; fewer means it gave "
        f"up before exhausting the budget."
    )


# ---------------------------------------------------------------------------
# cleat's HTTP classification boundary
#
# THESE PIN CLEAT'S MAPPING, NOT AN UPSTREAM ASSERTION, and the distinction is
# worth stating rather than blurring. DBOS separates retryable step failures
# from non-retryable ones by EXCEPTION TYPE and says nothing about HTTP status
# codes. The status mapping is cleat's own, in benchSvcStatusError
# (cmd/cleat-worker/setup.go):
#
#     status >= 400 && status < 500 && status != 408 && status != 429
#         -> PERMANENT, not retried
#     everything else -> TRANSIENT, retried per policy
#
# It is pinned here because it is the vehicle the entire retryable half of this
# port rides on: every test above reaches the transient path only because a 503
# maps to it. If that mapping moves, those tests stop measuring what they claim
# and would still pass -- a 500 reclassified as permanent makes
# "retried to the budget" fail loudly, but 408 or 429 reclassified fails
# nothing at all, because nothing exercised them.
#
# 408 and 429 are carved OUT of the 4xx rule, so they are the two the condition
# is most likely to lose. Dropping either `!=` clause is invisible today.
#
# The discriminator is the call count, never the clock. See
# test_a_permanently_failing_call_is_not_retried for what happens otherwise: a
# margin that was 8x on paper was 0x in practice once fixed overhead became
# comparable to the retry interval.

PERMANENT_STATUSES = [400, 401, 403, 404]
TRANSIENT_STATUSES = [408, 429, 500, 502, 503]


def _drive_status(cleat, retry_workflow, status_code):
    """Fail every attempt with status_code; return the final body and the count."""
    import uuid

    key = str(uuid.uuid4())
    ok, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": ATTEMPTS,
        "intervalMs": 200, "failTimes": 999, "failStatus": status_code,
    })
    assert ok == 201, f"start rejected for status {status_code}: {ok} {started}"
    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"
    return final, key


@pytest.mark.parametrize("status_code", PERMANENT_STATUSES)
def test_a_permanent_status_is_attempted_once(
    cleat, retry_workflow, fixture_calls, status_code
):
    """A 4xx outside {408, 429} must be attempted once and not retried.

    This is the call-count evidence for permanent classification, which did not
    exist before: the only coverage was a wall-clock assertion, and the test
    that appeared to supply the direct measurement was in fact measuring the
    transient path under a misleading name.

    Exactly 1 is the claim, not "fewer than the budget". A run that retried once
    and gave up would satisfy the looser form while still meaning the status was
    classified retryable.
    """
    final, key = _drive_status(cleat, retry_workflow, status_code)

    reached = fixture_calls(key)
    assert reached == 1, (
        f"HTTP {status_code} reached the service {reached} times with a budget of "
        f"{ATTEMPTS}, so cleat classified it TRANSIENT. Every 4xx except 408 and "
        f"429 is PERMANENT and must be attempted once -- see benchSvcStatusError "
        f"in cmd/cleat-worker/setup.go."
    )
    assert _body(final)["outcome"] == "failed"


@pytest.mark.parametrize("status_code", TRANSIENT_STATUSES)
def test_a_transient_status_is_retried_to_the_budget(
    cleat, retry_workflow, fixture_calls, status_code
):
    """408, 429 and every 5xx must be retried exactly MaxAttempts times.

    408 and 429 are the cases with no coverage at all before this. They are
    exceptions carved out of the 4xx rule, so losing either `!=` clause in
    benchSvcStatusError reclassifies a retryable failure as permanent -- and
    nothing failed when that happened, because nothing drove those two codes.

    The 5xx rows are not redundant with the tests above even though they take
    the same path: they are the control. If the whole mapping broke, the 4xx
    rows alone could not tell "408 was reclassified" from "the fixture never
    reached cleat" -- both give a count of 1. The 5xx rows failing at the same
    time says it is the harness; the 5xx rows passing while 408 fails says it is
    the boundary.
    """
    final, key = _drive_status(cleat, retry_workflow, status_code)

    reached = fixture_calls(key)
    assert reached == ATTEMPTS, (
        f"HTTP {status_code} reached the service {reached} times, want {ATTEMPTS}. "
        f"408, 429 and every 5xx are TRANSIENT and must be retried to the budget. "
        f"A count of 1 means cleat classified this PERMANENT -- for 408 or 429 "
        f"that is the carve-out in benchSvcStatusError having been lost."
    )
    assert _body(final)["outcome"] == "failed"
