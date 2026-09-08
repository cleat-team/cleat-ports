"""Distributed locks held across a suspension.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS serialises work through queue concurrency; cleat exposes the primitive
directly as `h.AcquireLock`/`h.ReleaseLock`, backed by the same concurrency-key
store. The engine property worth asserting is the one a lock exists for: while
one run holds a key, another run cannot take it, and once the holder releases,
the next caller can.

The holder suspends while holding. That is the case that separates a
distributed lock from a busy worker: if the key were held by whichever worker
happened to be executing, a suspension would drop it and the second acquire
would wrongly succeed.
"""

import json
import time
import uuid

import pytest

from conftest import wait_until

HOLD_MS = 20_000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _try_once(cleat, tryer, key):
    status, started = cleat.start(tryer, {"key": key, "ttlMs": 120000})
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"the lock attempt did not complete: {final!r}"
    return _body(final)


def test_a_held_lock_cannot_be_taken_and_is_released(cleat, lock_workflows, fixture_calls):
    """All three phases in one test, because they are one claim.

    Split apart, "cannot be taken" passes against an engine where acquire
    always fails, and "can be taken after release" passes against one where it
    always succeeds. Only the sequence distinguishes a working lock from a
    constant.
    """
    holder_name, try_name = lock_workflows
    key = f"lock-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(holder_name, {"key": key, "holdMs": HOLD_MS})
    assert status == 201, f"start rejected: {status} {started}"
    holder_id = started["id"]

    # Wait for the holder to announce, so the attempt below is known to happen
    # while the lock is held rather than before it was taken.
    wait_until(
        lambda: fixture_calls(f"{key}-held") == 1,
        timeout=60.0,
        what="the holder to acquire the lock and announce it",
    )

    # Phase 1: held.
    blocked = _try_once(cleat, try_name, key)
    assert blocked.get("acquired") is False, (
        f"a second run took a lock another run holds: {blocked!r}. The holder is "
        "suspended at this point, so a lock that appears free here is one held by "
        "a worker rather than by the run."
    )

    # Phase 2: the holder finishes and releases.
    final = cleat.await_terminal(holder_id, timeout=120.0)
    assert final["status"] == "done", f"the holder did not complete: {final!r}"
    assert _body(final)["outcome"] == "held-and-released", (
        f"the holder reported {_body(final)!r}"
    )

    # Phase 3: released, so the next caller gets it.
    freed = _try_once(cleat, try_name, key)
    assert freed.get("acquired") is True, (
        f"the lock was still not available after the holder released it: {freed!r}. "
        "A lock that is never released is indistinguishable from one that is "
        "always held, and phase 1 above would pass either way."
    )


def test_distinct_keys_do_not_block_each_other(cleat, lock_workflows, fixture_calls):
    """The control for phase 1.

    Without it, an engine whose acquire always returns false passes the
    "cannot be taken" assertion for the wrong reason.
    """
    holder_name, try_name = lock_workflows
    held = f"lock-{uuid.uuid4().hex[:8]}"
    other = f"lock-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(holder_name, {"key": held, "holdMs": HOLD_MS})
    assert status == 201, f"start rejected: {status} {started}"

    wait_until(
        lambda: fixture_calls(f"{held}-held") == 1,
        timeout=60.0,
        what="the holder to acquire its lock",
    )

    free = _try_once(cleat, try_name, other)
    assert free.get("acquired") is True, (
        f"an unrelated key was blocked while {held!r} was held: {free!r}. The lock "
        "is keyed on the whole store rather than on the key it was given."
    )
