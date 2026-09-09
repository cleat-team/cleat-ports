"""Assertions that need two live workers against one database.

Everything here was listed in the README's "what this suite structurally
cannot catch" until the `second_worker` fixture existed. `cleat-worker` serves
the HTTP API and runs workflows in one process, and the harness started
exactly one -- so a property that distinguishes "serialised inside a process"
from "serialised in the database" could be described here and not asserted.

That distinction is the whole subject of this file. A test that contends for a
key through ONE API server exercises whatever that process does about it;
cleat's answer is a row in `concurrency_keys` with `key_hash` as PRIMARY KEY
and `ON CONFLICT DO NOTHING`, which is a claim about the database and not
about the process. Only a second process can tell those apart.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.
"""

import json
import time
import uuid

import pytest

from conftest import Cleat, wait_until


def _key() -> str:
    return f"xworker-{uuid.uuid4().hex[:12]}"


def test_a_held_key_is_refused_from_a_second_worker(
    cleat, second_worker, api_key, holds_key_workflow
):
    """A key held via one worker is refused through the other.

    THE POINT IS THE SECOND PROCESS. test_concurrency.py already asserts that a
    second start under a held key is refused -- through the same worker, where
    a process-local map would satisfy it just as well as a database row. This
    is the same assertion with the two starts on opposite sides of a process
    boundary, so only the database can be doing the work.

    Both workers share the database, the API key and the fixture service, which
    is the configuration under test. If this passes while the single-worker
    version also passes, the exclusion is where cleat says it is.
    """
    other = Cleat(second_worker, api_key)
    assert other.base != cleat.base, (
        f"both clients point at {cleat.base}: this test would then assert "
        f"single-worker exclusion under a name that claims otherwise, and pass "
        f"for a reason it is written to rule out"
    )
    key = _key()

    status, first = cleat.start(holds_key_workflow, {"ms": 3000}, concurrency_key=key)
    assert status == 201, f"first start rejected: {status} {first}"

    status, body = other.start(holds_key_workflow, {"ms": 100}, concurrency_key=key)
    assert status == 409, (
        f"a key held through worker 1 was not refused through worker 2: got "
        f"{status} {body!r}. Two workers share one `concurrency_keys` table, so "
        f"a 201 here means the exclusion is process-local -- which would make "
        f"every single-worker concurrency assertion in this suite true of the "
        f"process and not of cleat."
    )


def test_distinct_keys_do_not_block_across_workers(
    cleat, second_worker, api_key, holds_key_workflow
):
    """The control, and it is not optional.

    Without it the test above passes against a worker that refuses every start
    it did not originate -- a broken second worker looks identical to correct
    mutual exclusion. This asserts the refusal is about the KEY.
    """
    other = Cleat(second_worker, api_key)

    status_a, a = cleat.start(holds_key_workflow, {"ms": 1500}, concurrency_key=_key())
    assert status_a == 201, f"first start rejected: {status_a} {a}"

    status_b, b = other.start(holds_key_workflow, {"ms": 100}, concurrency_key=_key())
    assert status_b == 201, (
        f"a start under a DIFFERENT key was refused through the second worker: "
        f"{status_b} {b!r}. The second worker is rejecting starts for some "
        f"reason other than key contention, so the exclusion test above proves "
        f"nothing."
    )


# The receiver's own timeout. Long enough that "woke on the delivery" and "woke
# when its own deadline expired" are half a minute apart, which is what makes
# the assertion below a separation rather than a tuned margin.
AWAIT_TIMEOUT_MS = 30_000


def test_a_signal_delivered_through_the_other_worker_wakes_the_receiver(
    cleat, second_worker, api_key, signal_pair, fixture_calls
):
    """A signal written by one process must wake a workflow the other is running.

    THIS IS THE CROSS-PROCESS HALF OF cleat#953, AND IT IS THE HALF THAT WAS
    NEVER DRIVEN. Delivery bumps `signal_seq` and a claim stamps
    `signal_seq_at_claim`; finalize compares them and pulls `next_wake_at`
    forward when they differ. Every existing test of that machinery -- the
    engine's included -- issues the delivery and runs the workflow in ONE
    process, where the two counters are written by the same binary against the
    same connection pool. Here the delivery is an HTTP POST to a second worker,
    so the increment and the comparison happen in different processes and only
    the database carries the fact between them.

    WHAT THIS DOES *NOT* ASSERT, because the HTTP surface cannot reach it: a
    delivery arriving while another worker holds the run `running`. A suspended
    workflow has an EMPTY `assigned_to` -- measured -- so there is no owner to
    deliver "past" while it waits, and the running window is the few hundred
    milliseconds of a segment. That case needs `claimSpecific` at the store
    level, which is where the engine's own test for it lives.

    The outcome alone is not the assertion, and that is the trap this is shaped
    around. cleat#953's original symptom was `AwaitSignals` reporting a timeout
    with the signal already in the table -- but the mirror of it is a receiver
    that reports `signalled` having sat until its deadline and only then found
    the row. Both return a value; only the timing separates them.
    """
    other = Cleat(second_worker, api_key)
    assert other.base != cleat.base, (
        f"both clients point at {cleat.base}: this test would then deliver "
        f"through the same process that runs the workflow, which is what every "
        f"other signal test already does, and it would pass without exercising "
        f"the cross-process path at all."
    )

    receiver_name, _ = signal_pair
    key = f"xw-sig-{uuid.uuid4().hex[:8]}"

    status, receiver = cleat.start(
        receiver_name, {"key": key, "timeoutMs": AWAIT_TIMEOUT_MS}
    )
    assert status == 201, f"receiver start rejected: {status} {receiver}"
    target = receiver["id"]

    # Signal only once the receiver has reached its await. Delivering earlier
    # asks a different question -- whether an early signal is held for the
    # eventual await -- and a failure could not say which case broke.
    wait_until(
        lambda: fixture_calls(f"{key}-waiting") == 1,
        timeout=60.0,
        what="the receiver to reach its await",
    )

    started = time.monotonic()
    status, body = other.signal(target, "go", '{"via":"second-worker"}')
    assert status in (200, 202, 204), (
        f"the second worker refused the delivery: {status} {body!r}. Nothing "
        f"below is about signal wakeup if the signal was never accepted."
    )

    final = cleat.await_terminal(target, timeout=AWAIT_TIMEOUT_MS / 1000 + 30)
    elapsed = time.monotonic() - started

    assert final["status"] == "done", f"the receiver did not complete: {final!r}"

    result = final["result"]
    outcome = (json.loads(result) if isinstance(result, str) else result)["outcome"]
    assert outcome == "signalled", (
        f"the receiver reported {outcome!r} after a delivery the second worker "
        f"accepted. `timedout` means the signal was written by one process and "
        f"never seen by the other -- the durable row is there and nothing acted "
        f"on it."
    )

    # THE HALF THE OUTCOME CANNOT CARRY. A receiver that slept to its own
    # deadline and only then noticed the row also reports `signalled`. The two
    # are ~30s apart, so this is a separation between the hypotheses rather
    # than a threshold anyone tuned: a prompt wake takes a second or two.
    assert elapsed < AWAIT_TIMEOUT_MS / 1000 / 2, (
        f"the receiver reported `signalled` but took {elapsed:.1f}s, more than "
        f"half its own {AWAIT_TIMEOUT_MS / 1000:.0f}s timeout. It was not woken "
        f"by the delivery -- it slept to its deadline and found the row on its "
        f"way past. That is cleat#953's symptom with the sign flipped, and it "
        f"is invisible in the outcome."
    )
