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


# The reaper needs the heartbeat to go stale (10s) and then to run (every 10s),
# then the reclaimed workflow has to be picked up and replayed. Same sizing as
# test_recovery.py, and for the same reason.
CRASH_HOLD_MS = 45_000
CRASH_RECOVERY_TIMEOUT = 180.0


def test_a_key_held_by_a_crashed_worker_is_neither_stuck_nor_freed_early(
    cleat, holds_key_workflow, worker
):
    """Ports upstream test_queue_deduplication_recovery.

    Upstream crashes a process holding a deduplication id and asserts the id is
    usable again afterwards. Cleat's concurrency key is the same kind of
    exclusive claim, so the property ports even though the queueing half does
    not (see the module docstring).

    WHY THIS IS NOT test_key_is_released_when_the_holder_finishes. That test
    releases the key down the ordinary path: the holder runs to completion and
    the worker that owns it tidies up. Here the owning worker is killed, so the
    row is reclaimed by the reaper and finished by a different worker. Nothing
    about the graceful path implies the reclaimed one -- release could plausibly
    be the exiting worker's job, and would then never happen for a worker that
    did not exit.

    BOTH DIRECTIONS ARE ASSERTED, because they are opposite failures and each
    one alone is satisfiable by a broken engine:

      freed too early  -- if the key is released the moment its worker dies, a
                          second start is admitted while the original is still
                          recovering, and two runs execute concurrently under a
                          key whose entire purpose is that they cannot. An
                          engine with this bug passes any test that only checks
                          the key eventually frees.
      stuck forever    -- if release is the dying worker's job, the key is held
                          by a row nobody will ever finish and every later start
                          409s permanently. An engine with THIS bug passes any
                          test that only checks the key is still held.

    The failure is silent in both directions, which is why it is asserted on
    the status codes at three separate moments rather than on the final state.

    FALSIFIED: pointing the mid-recovery start at a fresh key instead of the
    held one fails in 1.63s with "the key was free while its holder was still
    unfinished, got 201". So the safety assertion can see an unheld key at the
    moment it matters, rather than passing because every start is refused.
    """
    key = _key()

    status, first = cleat.start(
        holds_key_workflow, {"ms": CRASH_HOLD_MS}, concurrency_key=key
    )
    assert status == 201, f"first start should be accepted, got {status}: {first}"

    # Establish the key is actually held BEFORE the crash. Without this, a key
    # that was never taken would satisfy the post-crash rejection check for the
    # wrong reason -- there would be nothing to have survived.
    status, blocked = cleat.start(
        holds_key_workflow, {"ms": 100}, concurrency_key=key
    )
    assert status == 409, (
        f"the key was not held before the crash, so this test cannot say "
        f"anything about it surviving one; got {status}: {blocked}"
    )

    worker.crash()
    worker.restart()

    # SAFETY. The original is still mid-sleep and now owned by a worker that is
    # never coming back. It has ~40s of its hold left, so a free key here is
    # not a race with legitimate completion -- it is the key being released on
    # worker death rather than on run completion.
    status, during = cleat.start(
        holds_key_workflow, {"ms": 100}, concurrency_key=key
    )
    assert status == 409, (
        f"the key was free while its holder was still unfinished, got {status}: "
        f"{during}. The holder was mid-sleep with its worker killed, so this "
        "admits a second run alongside a first that is about to be recovered "
        "and resumed -- two runs at once under a key that exists to prevent "
        "exactly that."
    )
    assert key in during.get("error", ""), (
        f"refused, but not demonstrably because of this key: {during!r}. A 409 "
        "that names something else would satisfy the assertion above for a "
        "reason unrelated to what is being tested."
    )

    # CONTROL, and it is the reason the 409 above can be attributed at all. A
    # freshly-restarted worker refusing starts for its own reasons would
    # produce the same rejection, and the test would read as proof of a
    # property the engine might not have. A distinct key admitted at this exact
    # moment shows the server is taking starts and that the refusal is about
    # the key, not about the restart.
    status, control = cleat.start(
        holds_key_workflow, {"ms": 100}, concurrency_key=_key()
    )
    assert status == 201, (
        f"a start under an UNHELD key was refused {status} right after the "
        f"restart: {control}. The rejection above cannot be attributed to the "
        "held key while the server is refusing starts generally."
    )

    # LIVENESS. The reclaimed run finishes on another worker, and the key has
    # to come back with it.
    final = cleat.await_terminal(first["id"], timeout=CRASH_RECOVERY_TIMEOUT)
    assert final["status"] == "done", (
        f"the holder did not complete after its worker was killed: {final!r}"
    )

    status, after = cleat.start(
        holds_key_workflow, {"ms": 100}, concurrency_key=key
    )
    assert status == 201, (
        f"the key was still held after its holder reached a terminal state, "
        f"got {status}: {after}. Released on the ordinary path but not on the "
        "reclaimed one leaves the key permanently unusable, and every later "
        "start under it 409s forever."
    )
    assert after["id"] != first["id"], "a re-start should be a new run"
