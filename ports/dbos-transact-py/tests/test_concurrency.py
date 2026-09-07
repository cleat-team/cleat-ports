"""Concurrency limits, ported from dbos-transact-py's tests/test_queue.py.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream reference:
  test_one_at_a_time_with_worker_concurrency  tests/test_queue.py:1134

What upstream asserts is that a queue with a concurrency limit of one runs its
tasks one at a time: enqueue two workflows, the second does not start while the
first is running, and after the first finishes BOTH complete.

Cleat cannot express the second half, and the difference is not a detail:

    DBOS   enqueue -> the blocked task waits  -> runs later -> completes
    cleat  start   -> the blocked start is REJECTED, 409   -> never runs

DBOS's queue defers work. Cleat's concurrency key is a mutual exclusion lock:
`concurrency_keys` is keyed `key_hash BYTEA PRIMARY KEY`, one row per key, so
it admits one holder and turns the second caller away. There is no counter, so
`concurrency=N` for N > 1, `worker_concurrency`, and the rate limiter have
nothing to map onto at all.

So the mutual-exclusion half ports and is asserted below; the queueing half is
recorded as a gap rather than papered over with a test that pretends a
rejection is a deferral.
"""

import uuid

import pytest


def _key() -> str:
    return f"port-concurrency-{uuid.uuid4()}"


def test_second_start_under_the_same_key_is_rejected(cleat, holds_key_workflow):
    """The mutual-exclusion half of upstream's one-at-a-time assertion.

    Upstream asserts the second task has not *started* while the first runs.
    Here the second start does not merely fail to begin, it is refused, so the
    assertion is on the status code the caller receives.
    """
    key = _key()

    status, first = cleat.start(holds_key_workflow, {"ms": 3000}, concurrency_key=key)
    assert status == 201, f"first start should be accepted, got {status}: {first}"
    run_id = first["id"]

    status, body = cleat.start(holds_key_workflow, {"ms": 100}, concurrency_key=key)
    assert status == 409, (
        f"second start under a held key should be refused with 409, got "
        f"{status}: {body}"
    )
    assert key in body.get("error", ""), (
        "the rejection should name the key it conflicted on, so an operator "
        f"can tell which of several keys blocked the start; got {body!r}"
    )

    # The first run must still finish. A rejected second start that also killed
    # the first would satisfy the assertion above and be catastrophic.
    final = cleat.await_terminal(run_id)
    assert final["status"] == "done", (
        f"the holder should complete normally, got {final.get('status')!r} "
        f"error={final.get('error')!r}"
    )


def test_key_is_released_when_the_holder_finishes(cleat, holds_key_workflow):
    """The other half of one-at-a-time: the limit must not be permanent.

    Upstream gets this for free -- its second task runs once the first
    completes, so a queue that never released would hang the test. Cleat
    rejects instead, so nothing in the previous test would notice a key that
    was never released; every later start would simply 409 forever. Asserted
    separately because the failure is silent rather than loud.
    """
    key = _key()

    status, first = cleat.start(holds_key_workflow, {"ms": 200}, concurrency_key=key)
    assert status == 201, f"first start should be accepted, got {status}: {first}"

    final = cleat.await_terminal(first["id"])
    assert final["status"] == "done", f"holder did not complete: {final!r}"

    status, second = cleat.start(holds_key_workflow, {"ms": 100}, concurrency_key=key)
    assert status == 201, (
        f"the key should be free once its holder reached a terminal state, "
        f"got {status}: {second}"
    )
    assert second["id"] != first["id"], "a re-start should be a new run"


def test_distinct_keys_do_not_block_each_other(cleat, holds_key_workflow):
    """Guards the assertion above against being vacuously true.

    If concurrency keys were ignored entirely, the rejection test would fail --
    but if starts were rejected for some unrelated reason, it would pass for
    the wrong reason. Two different keys must both be admitted.
    """
    status_a, a = cleat.start(holds_key_workflow, {"ms": 1500}, concurrency_key=_key())
    status_b, b = cleat.start(holds_key_workflow, {"ms": 1500}, concurrency_key=_key())

    assert status_a == 201, f"first key rejected: {status_a} {a}"
    assert status_b == 201, f"second, different key rejected: {status_b} {b}"

    for run in (a, b):
        assert cleat.await_terminal(run["id"])["status"] == "done"


@pytest.mark.skip(
    reason="GAP: cleat has no queueing concurrency limit. DBOS defers a blocked "
           "task and runs it when the limit frees; cleat rejects the start with "
           "409 and it never runs. Porting upstream's assertion verbatim would "
           "require deferral semantics that do not exist. Tracked in the "
           "conformance gap matrix."
)
def test_blocked_task_runs_after_the_holder_finishes():
    """Upstream test_one_at_a_time_with_worker_concurrency, second half.

    Left in place, skipped, rather than omitted: an absent test is
    indistinguishable from an untried one, and this is the assertion a reader
    comparing the two systems will look for first.
    """
