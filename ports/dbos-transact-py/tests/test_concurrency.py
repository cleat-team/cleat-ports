"""Concurrency limits, ported from dbos-transact-py's tests/test_queue.py.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream reference:
  test_one_at_a_time_with_worker_concurrency  tests/test_queue.py:1134

What upstream asserts is that a queue with a concurrency limit of one runs its
tasks one at a time: enqueue two workflows, the second does not start while the
first is running, and after the first finishes BOTH complete.

THE GAP THIS FILE RECORDED IS CLOSED (cleat#1186, merged 2026-09-11).

It used to read:

    DBOS   enqueue -> the blocked task waits  -> runs later -> completes
    cleat  start   -> the blocked start is REJECTED, 409   -> never runs

and said the queueing half was "recorded as a gap rather than papered over with
a test that pretends a rejection is a deferral". cleat now defers: the key is
recorded on the row at insert time, the claim path skips a run whose key another
run holds, and acquiring the key is part of claiming. So a blocked start is
accepted with 201 and its run simply waits, which is DBOS's shape.

**Both halves of upstream's assertion are therefore asserted below for the first
time** -- the second start does not begin while the first runs, AND both
complete once the first finishes.

`409` has not disappeared: it is the fallback for a store that cannot record the
key on the row, where the alternative is a run that starts and is never
deferred. No dialect this suite runs against takes that path, so a 409 here now
means the key was not recorded, which is a defect rather than the contract.

AND THE COUNTER ARRIVED TOO (cleat#1116, closed 2026-09-20), which is what
un-skipped the last test in this file.

`concurrency_keys` is still one row per key, and that is still a mutex -- but it
is no longer the only arm. A key that names a live row in the `queues` table is
claimed against that row's `concurrency_limit` instead (cleat#1930), counted in
`queue_holders` under a row lock, so `concurrency=N` for N > 1 finally has
something to map onto. `cleatctl queue create` registers one (cleat#1934); the
`declared_queue` fixture is this harness's only route to it, because no HTTP
route registers a queue.

A key with no registered queue keeps the old behaviour exactly -- which is why
the three tests above are unchanged and still pass. The two arms are what the
last test here discriminates between: with a queue declaring 2, two runs must be
admitted at once; without one, a bug that ignored the table would admit one.

Still absent: `worker_concurrency` (a PER-WORKER cap, cleat#1917, which was
blocked on this) and the rate limiter (`limiter={limit, period}`, cleat#1918).
Neither has a cleat surface yet, and neither is tested here.
"""

import time
import uuid

import pytest


def _key() -> str:
    return f"port-concurrency-{uuid.uuid4()}"


def test_a_second_start_under_the_same_key_waits_then_runs(cleat, holds_key_workflow):
    """Upstream's one-at-a-time assertion, BOTH halves (cleat#1186).

    Upstream enqueues two tasks against a queue with a concurrency limit of one:
    the second does not start while the first runs, and after the first finishes
    both complete. Until cleat#1186 the second half was unportable because cleat
    refused the second start outright, and this test asserted the refusal's
    status code instead -- a status code standing in for a behaviour.

    The behaviour is now directly observable, so it is what is asserted.
    """
    key = _key()

    status, first = cleat.start(holds_key_workflow, {"ms": 3000}, concurrency_key=key)
    assert status == 201, f"first start should be accepted, got {status}: {first}"
    run_id = first["id"]

    status, second = cleat.start(holds_key_workflow, {"ms": 100}, concurrency_key=key)
    assert status == 201, (
        f"a second start under a held key should be ACCEPTED and deferred since "
        f"cleat#1186, got {status}: {second}. A 409 here means the key was not "
        f"recorded on the row, which is the fallback path for a store that "
        f"cannot do so -- a defect on this dialect, not the contract"
    )
    second_id = second["id"]
    assert second_id != run_id, "a deferred start must be its own run, not the holder's id"

    # The half upstream asserts and this file could not: the second has NOT
    # begun. Sampled while the holder still has seconds of its hold left, so a
    # non-terminal status here is deferral rather than a race with completion.
    for _ in range(4):
        body = cleat.get(second_id)[1]
        assert body.get("status") == "ready", (
            f"the deferred run reached {body.get('status')!r} while the key was "
            f"still held; exclusion is what a concurrency key is for, and a "
            f"start that is accepted but not excluded is worse than a refusal"
        )
        time.sleep(0.25)

    # And the other half: once the holder finishes, the waiter runs. A deferral
    # that never resumes is a queue that hangs, which upstream gets for free
    # because a stuck queue fails its own test.
    final = cleat.await_terminal(run_id)
    assert final["status"] == "done", (
        f"the holder should complete normally, got {final.get('status')!r} "
        f"error={final.get('error')!r}"
    )

    second_final = cleat.await_terminal(second_id, timeout=60.0)
    assert second_final["status"] == "done", (
        f"the deferred run did not complete after its blocker finished, got "
        f"{second_final.get('status')!r}: a key that defers but never releases "
        f"is indistinguishable from one that refuses, and fails silently"
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


# Two, not one: one is what an UNREGISTERED key already gives, so a limit of one
# would pass this test whether the queue was registered or not. Two is the
# smallest number that can tell the semaphore from the mutex.
QUEUE_LIMIT = 2

# Four seconds, so the two admitted holders overlap for many samples. The
# assertion is about how many hold a slot AT ONCE, and a hold short enough to
# finish between two samples would make "never more than two" true for the wrong
# reason -- which is what `full_samples` below refuses to accept.
QUEUE_HOLD_MS = 4000


def test_blocked_task_runs_after_the_holder_finishes(
    cleat, holds_key_workflow, declared_queue
):
    """Upstream test_one_at_a_time_with_worker_concurrency, second half.

    SKIPPED FOR A FORTNIGHT AND NOW WRITTEN, which is the whole reason it was
    left in the tree with a docstring and no body: an absent test is
    indistinguishable from an untried one, and this is the assertion a reader
    comparing the two systems looks for first.

    ITS SKIP REASON WAS FALSE TWICE, and both times in the same direction --
    claiming a gap that had closed. The first version read "cleat rejects the
    start with 409 and it never runs", which stopped being true at cleat#1186.
    The second read "cleat still has no queueing concurrency LIMIT", which
    stopped being true at cleat#1930 and was fully reachable at cleat#1934. A
    skip carries its justification in prose that nothing executes, so it cannot
    go red when the world moves under it; it just keeps telling every reader
    who trusts it about a hole that is filled.

    WHAT UPSTREAM ASSERTS: a queue with a concurrency limit runs at most that
    many tasks at once, and the ones past the limit are HELD and run later
    rather than refused. Cleat spells the queue as a row in `queues` and the
    enqueue as a start carrying that queue's name as its `concurrency_key`.

    WHY THE LIMIT IS TWO, AND WHY THAT IS THE TEST'S OWN CONTROL. An
    unregistered key is a mutex, N=1. So a test written with a limit of one
    would pass identically against a cleat that ignored the `queues` table
    entirely -- it would be measuring the mechanism the three tests above
    already cover. At two, the two arms disagree, and this test fails in a
    DIFFERENT way against each defect:

        the table is ignored / the queue never registered   peak 1, not 2
        the limit is not enforced                           3 hold a slot at once

    Both directions are asserted, so neither a missing semaphore nor a missing
    limit passes. Falsified, not assumed: see the PR body.

    The three runs are identical in duration on purpose. Asserting WHICH two
    are admitted would rest on the claim's `ORDER BY priority, created_at`
    breaking a tie between three starts issued in one loop, which is a
    different property from the one under test and a real source of flake. The
    waiter is identified by being the one not admitted.

    OCCUPANCY IS READ AS `started_at` AND NOT-TERMINAL, WHICH IS NEITHER FIELD
    ALONE. Two earlier versions of this test were written and both were wrong
    against a working engine, which is why the reasoning is here rather than
    trusted:

      * `status == "running"` cannot see a holder. `holds_key` holds its key
        across a DURABLE SLEEP, and a sleeping run reads `ready` -- the same
        thing a run deferred behind a full queue reads. Measured, three runs
        against a queue declaring 2:

            t+0.0s   running  ready  ready
            t+0.4s   ready    ready  ready      <- both holders, asleep
            t+5.4s   done     done   running    <- the waiter, admitted

        For most of the window `status` says `ready` about a run holding a slot
        and about a run that has never had one.

      * `started_at` alone cannot see a LIMIT, because it is monotone: it
        answers "has this ever begun", so once the first holder releases and
        the waiter is admitted, all three have begun and a snapshot taken then
        reads as three-at-once. The first version of this test asserted exactly
        that and failed against a correct engine whenever the sample landed
        after the release.

    `started_at AND NOT terminal` is "holds a slot right now", it goes down as
    well as up, and it is what the limit is a limit on.
    """
    queue = declared_queue(QUEUE_LIMIT)

    runs = []
    for _ in range(QUEUE_LIMIT + 1):
        status, body = cleat.start(
            holds_key_workflow, {"ms": QUEUE_HOLD_MS}, concurrency_key=queue
        )
        assert status == 201, (
            f"a start against a declared queue should be accepted and deferred, "
            f"never refused, got {status}: {body}"
        )
        runs.append(body["id"])
    assert len(set(runs)) == len(runs), f"starts returned duplicate ids: {runs}"

    begun: set[str] = set()
    peak = 0            # most slots held simultaneously, over every sample
    full_samples = 0    # samples that caught the queue exactly at its limit

    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        bodies = {rid: cleat.get(rid)[1] for rid in runs}
        begun |= {rid for rid, b in bodies.items() if b.get("started_at")}
        holding = [
            rid for rid, b in bodies.items()
            if b.get("started_at") and b.get("status") not in cleat.TERMINAL
        ]

        # The limit, asserted at EVERY sample rather than once. This is the
        # direction a broken enforcement fails in, and it is the reason the
        # loop samples instead of waiting and then looking.
        assert len(holding) <= QUEUE_LIMIT, (
            f"{len(holding)} runs held a slot at once on a queue declaring "
            f"concurrency={QUEUE_LIMIT} ({holding}); admission past a declared "
            f"limit is the failure this table exists to prevent"
        )
        peak = max(peak, len(holding))

        if len(holding) == QUEUE_LIMIT:
            full_samples += 1
            # While the queue is full, the run past the limit has never begun.
            # Upstream's "does not start while the others run", and the half a
            # deferral-that-rejects would also satisfy -- which is why the
            # completion assertions below are the other half.
            waiting = [rid for rid in runs if rid not in begun]
            assert len(waiting) == 1, (
                f"the queue is at its limit of {QUEUE_LIMIT} and "
                f"{len(waiting)} of {len(runs)} runs have never begun; expected "
                f"exactly the one past the limit"
            )

        if len(begun) == len(runs):
            break
        time.sleep(0.2)

    # The semaphore. ONE is what an unregistered key gives -- a mutex -- so this
    # is the assertion that separates a declared queue from cleat's original
    # mechanism, and the one that fails if the `queues` row was never read.
    assert peak == QUEUE_LIMIT, (
        f"at most {peak} run(s) ever held a slot at once on a queue declaring "
        f"concurrency={QUEUE_LIMIT}. One means the declared limit was not read "
        f"and the key fell back to the concurrency_keys mutex, which is what an "
        f"unregistered name does -- so check that the queue was registered"
    )

    # Non-vacuity. A run in which the queue was never observed full has proved
    # nothing about exclusion, and would pass every assertion above.
    assert full_samples >= 3, (
        f"the queue was caught at its limit in only {full_samples} sample(s), "
        f"so exclusion was barely measured. The holders sleep {QUEUE_HOLD_MS}ms, "
        f"which should afford many"
    )

    assert len(begun) == len(runs), (
        f"only {len(begun)} of {len(runs)} runs ever began within 90s; a queue "
        f"that defers and never releases is indistinguishable from one that "
        f"refuses, and fails silently"
    )

    # And that everything finishes, not merely starts.
    for rid in runs:
        final = cleat.await_terminal(rid, timeout=90.0)
        assert final["status"] == "done", (
            f"run {rid} did not complete: {final.get('status')!r} "
            f"error={final.get('error')!r}"
        )


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
    # Establish the key is held BEFORE the crash by observing DEFERRAL, not a
    # refusal: since cleat#1186 a blocked start is accepted and its run waits.
    # The probe changed; what it establishes did not -- without this there would
    # be nothing for the post-crash check to have survived.
    status, blocked = cleat.start(
        holds_key_workflow, {"ms": 100}, concurrency_key=key
    )
    assert status == 201, (
        f"a start under a held key should be accepted and deferred, got "
        f"{status}: {blocked}"
    )
    blocked_body = cleat.get(blocked["id"])[1]
    assert blocked_body.get("status") == "ready", (
        f"the key was not held before the crash -- the second run reached "
        f"{blocked_body.get('status')!r} instead of waiting, so this test "
        f"cannot say anything about a key surviving one"
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
    assert status == 201, (
        f"a start under a held key should be accepted and deferred, got "
        f"{status}: {during}"
    )
    during_body = cleat.get(during["id"])[1]
    assert during_body.get("status") == "ready", (
        f"the key was free while its holder was still unfinished -- the new run "
        f"reached {during_body.get('status')!r} instead of waiting. The holder "
        "was mid-sleep with its worker killed, so this runs a second workflow "
        "alongside a first that is about to be recovered and resumed: two at "
        "once under a key that exists to prevent exactly that."
    )

    # CONTROL, and it is the reason the deferral above can be attributed at all.
    # A freshly-restarted worker that was claiming nothing would leave EVERY new
    # run sitting in 'ready', and this test would read as proof of a property
    # the engine might not have. A distinct key that reaches a terminal state at
    # this exact moment shows the worker is claiming and running work, so the
    # other run is waiting on the key rather than on the restart.
    #
    # This replaced a 201-vs-409 contrast when cleat#1186 made both starts
    # answer 201: the discriminating signal moved from the status code to
    # whether the run executes, so the control had to move with it or it would
    # have compared two identical values and proved nothing.
    status, control = cleat.start(
        holds_key_workflow, {"ms": 100}, concurrency_key=_key()
    )
    assert status == 201, (
        f"a start under an UNHELD key was refused {status} right after the "
        f"restart: {control}"
    )
    control_final = cleat.await_terminal(control["id"], timeout=CRASH_RECOVERY_TIMEOUT)
    assert control_final["status"] == "done", (
        f"a run under an unheld key did not complete after the restart, got "
        f"{control_final.get('status')!r}. The deferral above cannot be "
        "attributed to the held key while the worker is running nothing at all."
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
