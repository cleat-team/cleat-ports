"""Replay determinism: completed work is not redone when a run resumes.

Derived from the assertions of dbos-transact-py's step-once tests, not from
upstream source. See UPSTREAM and ../../docs/licensing.md.

DBOS counts invocations of a decorated step across a recovery. Cleat has no step
decorator and no counter to inspect, so the property is asserted through
`SideEffect`, which *validates* rather than caches: on replay it recomputes the
function and fails the workflow if the result differs from history.

That validation is what makes this testable from outside. A workflow that
captures the clock in a `SideEffect`, suspends, and then completes **has proved
the captured value survived the replay** — because if it had been recomputed to
anything else, the engine would have refused the run:

    cleat_side_effect: replay divergence at step 0: SideEffect produced
    "1788668316318" but history recorded "1788668316209"

That is not hypothetical: this exact workflow produced exactly that error until
cleat#787, and the guard test below exists to prove the suspension is real, so
"it completed" cannot be satisfied without a replay having happened.

This is the one place the port asserts something no upstream suite does.
Re-executing from step 0 while serving completed work from history is cleat's
central architectural claim, and Temporal and DBOS both express the equivalent
guarantee through machinery cleat does not have.
"""

import json
import time

import pytest

SLEEP_MS = 3000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


RUNS = 3


def test_a_captured_value_survives_the_replay(cleat, replay_identity_workflow):
    """Cleat's central claim, asserted via SideEffect's own validation.

    The workflow captures `h.Now()` in a SideEffect, suspends, and returns.
    Reaching `done` means the recomputed value matched history on resume; any
    divergence fails the run outright.

    Run several times, deliberately. Falsifying this against a worker built
    without cleat#787 showed a single run is not a reliable detector: the
    divergence only appears when the gap between reading the clock and the row
    being written exceeds a millisecond, and one fast run can miss it. Three
    runs also give the distinctness check below something to compare, so the
    two assertions share the same work.
    """
    captured = []
    for i in range(RUNS):
        started_at = time.monotonic()
        status, started = cleat.start(replay_identity_workflow, {"ms": SLEEP_MS})
        assert status == 201, f"run {i}: start rejected: {status} {started}"

        final = cleat.await_terminal(started["id"], timeout=90.0)
        elapsed_ms = (time.monotonic() - started_at) * 1000

        assert final["status"] == "done", (
            f"run {i} did not complete: {final.get('status')!r} "
            f"{(final.get('error') or '')[:300]!r}. A 'replay divergence' here "
            "means a value captured before the suspension was recomputed "
            "differently after it — cleat re-executes from step 0 on resume and "
            "must serve completed work from history."
        )
        # Without this, the assertion above is satisfiable with no replay at all.
        assert elapsed_ms >= SLEEP_MS * 0.8, (
            f"run {i} finished in {elapsed_ms:.0f}ms for a requested "
            f"{SLEEP_MS}ms sleep, so it never suspended and nothing was replayed"
        )
        captured.append(_body(final)["cached"])

    # A constant would survive replay perfectly and prove nothing. h.NewUUID()
    # returned one in every compiled workflow until cleat#786, and the first
    # version of this test used it, passed, and asserted nothing. A clock
    # reading is the opposite: independent reads essentially never agree, so
    # stability across a resume is evidence rather than coincidence.
    assert len(set(captured)) == RUNS, (
        f"{RUNS} runs captured {len(set(captured))} distinct value(s): "
        f"{captured!r}. If the captured value is constant, surviving a replay "
        "proves nothing."
    )
    for v in captured:
        assert int(v) > 1_700_000_000_000, f"not a plausible epoch-ms value: {v}"


def test_the_virtual_clock_advances_across_a_sleep(cleat, replay_identity_workflow):
    """The durable clock must move by the duration the workflow asked for.

    `h.Now()` read after a suspension and BEFORE any new event is recorded must
    already reflect the sleep. It did not until the fix that accompanies
    cleat#804: a sleep records no event and advances the virtual clock in
    memory, but Now() preferred the last recorded event's timestamp, so it
    handed back a pre-sleep instant. Measured at 163ms of apparent elapsed time
    across a 3000ms sleep.

    The window matters because it is where a workflow naturally looks at the
    clock: immediately on waking, to decide what to do next.
    """
    status, started = cleat.start(replay_identity_workflow, {"ms": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    body = _body(final)
    cached, fresh = int(body["cached"]), int(body["fresh"])
    advanced = fresh - cached

    assert advanced >= SLEEP_MS * 0.8, (
        f"the virtual clock advanced {advanced}ms across a {SLEEP_MS}ms sleep. "
        "A durable clock read on waking must already include the wait; a value "
        "near zero means it returned the pre-suspension anchor."
    )

    # Bounded on both sides. The lower bound alone would pass on a clock that
    # jumped to some far-future wall-clock instant, which is the same defect
    # class -- a read that is not the durable anchor -- pointing the other way.
    # The slack above SLEEP_MS is the real time the resumed execution takes;
    # measured at ~165ms.
    assert advanced <= SLEEP_MS * 2, (
        f"the virtual clock advanced {advanced}ms across a {SLEEP_MS}ms sleep, "
        "far more than was asked for. The clock should carry the sleep plus the "
        "cost of resuming, not an unrelated wall-clock reading."
    )
