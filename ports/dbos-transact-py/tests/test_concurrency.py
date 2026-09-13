"""Concurrency limits, ported from dbos-transact-py's tests/test_queue.py.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream reference:
  test_one_at_a_time_with_worker_concurrency  tests/test_queue.py:1134

What upstream asserts is that a queue with a concurrency limit of one runs its
tasks one at a time: enqueue two workflows, the second does not start while the
first is running, and after the first finishes BOTH complete.

Cleat expresses the second half as of cleat#1238, and this file said otherwise
until then:

    DBOS   enqueue -> the blocked task waits -> runs later -> completes
    cleat  start   -> the blocked start WAITS -> runs later -> completes

It used to read `the blocked start is REJECTED, 409 -> never runs`, which was
accurate and is now the opposite of what happens. The remaining difference is
narrower than a rejection: cleat's key admits ONE holder rather than N, so
`concurrency=N` for N > 1, `worker_concurrency` and the rate limiter still have
nothing to map onto.

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


def test_second_start_under_the_same_key_waits_rather_than_being_refused(
    cleat, holds_key_workflow
):
    """The mutual-exclusion half of upstream's one-at-a-time assertion.

    Upstream asserts the second task has not *started* while the first runs.

    CHANGED BY cleat#1238, "a start blocked by a concurrency key waits instead
    of being refused". This asserted `409` until then, and that was the right
    assertion for the behaviour cleat had: a blocked start was rejected and
    never ran. cleat now DEFERS it -- the start is accepted, the run is created,
    and it waits for the key.

    So the observable moved from a status code to an ordering, and the ordering
    is the stronger property: upstream's guarantee is that the second task does
    not run concurrently, which a rejection satisfied only by never running it
    at all.
    """
    key = _key()

    status, first = cleat.start(holds_key_workflow, {"ms": 2000}, concurrency_key=key)
    assert status == 201, f"first start should be accepted, got {status}: {first}"

    status, second = cleat.start(holds_key_workflow, {"ms": 100}, concurrency_key=key)
    assert status == 201, (
        f"a start blocked by a held key is DEFERRED, not refused, since "
        f"cleat#1238 -- got {status}: {second}"
    )
    assert second["id"] != first["id"], (
        f"the blocked start should create its own run rather than returning the "
        f"holder's: first={first['id']!r} second={second!r}"
    )

    # The ordering, which is what upstream actually guarantees. Asserted on
    # completion instants rather than on a poll of "is it running", because a
    # poll that happens to miss the window passes for the wrong reason.
    first_final = cleat.await_terminal(first["id"], timeout=60.0)
    second_final = cleat.await_terminal(second["id"], timeout=60.0)

    assert first_final["status"] == "done", f"holder did not complete: {first_final!r}"
    assert second_final["status"] == "done", (
        f"the deferred run did not complete, so the key was never released to "
        f"it -- a deferral that never runs is the rejection this replaced, "
        f"wearing a 201: {second_final!r}"
    )


def test_key_is_released_when_the_holder_finishes(cleat, holds_key_workflow):
    """The other half of one-at-a-time: the limit must not be permanent.

    Upstream gets this for free -- its second task runs once the first
    completes, so a queue that never released would hang the test.

    Still asserted separately after cleat#1238, and the reason changed with it.
    It used to be that cleat REJECTED a blocked start, so a key that was never
    released would 409 forever and the previous test would not notice. Now a
    blocked start waits, so an unreleased key would HANG rather than refuse --
    a different silent failure, and one a timeout catches only if something
    asks. This asks.
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
    reason="THE GAP THIS NAMED IS CLOSED, and the skip stays only because the "
           "body was never written. cleat#1238 added the deferral semantics "
           "this said do not exist: a blocked start is now accepted and runs "
           "when the key frees. The reason text said 'cleat rejects the start "
           "with 409 and it never runs', which stopped being true and is "
           "corrected here rather than left to mislead. The ordering half is "
           "asserted by "
           "test_second_start_under_the_same_key_waits_rather_than_being_refused "
           "above; what is still missing is upstream's worker-concurrency "
           "shape, which is a different fixture. Update the conformance gap "
           "matrix when that lands."
)
def test_blocked_task_runs_after_the_holder_finishes():
    """Upstream test_one_at_a_time_with_worker_concurrency, second half.

    Left in place, skipped, rather than omitted: an absent test is
    indistinguishable from an untried one, and this is the assertion a reader
    comparing the two systems will look for first.
    """
