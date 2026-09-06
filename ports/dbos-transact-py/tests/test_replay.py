"""Replay determinism: completed work is not redone when a run resumes.

Derived from the assertions of dbos-transact-py's step-once tests, not from
upstream source. See UPSTREAM and ../../docs/licensing.md.

DBOS asserts this by counting invocations of a decorated step across a recovery.
Cleat has no step decorator and no counter to inspect, so the property has to be
asserted through a captured value: something recorded before a suspension that
can be shown, afterwards, not to have been recomputed.

**That test cannot currently be written against cleat, and the reason is the
finding.** Three separate attempts, each blocked:

1. `h.NewUUID()` returns the constant `00000000-0000-4000-8000-000000000000` in
   every compiled workflow -- `cleat build` does not wire `cleat_random` for it
   (cleat-team/cleat#775). A constant survives replay perfectly, so a test built
   on it passes no matter what the engine does. This was caught only because a
   guard test asserted the run had really suspended.

2. Publishing a value with `SetQueryState` before suspending and sampling it
   from outside does not work: query state is not readable while a run is
   suspended. It becomes visible when the run completes -- by which point
   `SetQueryState` has run again on replay and overwritten the evidence.

3. `h.SideEffect`, the primitive that exists for exactly this, **validates
   rather than caches**. On replay it recomputes the function and fails the
   workflow if the result differs:

       cleat_side_effect: replay divergence at step 0: SideEffect produced
       "1788659611398" but history recorded "1788659611196". Your workflow may
       have a non-determinism bug (time.Now(), random values, ...)

   The value it rejected came from `h.Now()` -- the clock `cleat vet` E003
   directs users to *instead of* `time.Now()`, with the message "Use h.Now() for
   deterministic time". It is not deterministic across replay here.

So the toolchain rejects `time.Now()` and points at `h.Now()`; `h.Now()`
diverges; and `SideEffect`, the wrapper for non-determinism, treats that
divergence as a workflow-fatal error. There is no combination of these that
captures a non-deterministic value across a suspension.

This matters more than one skipped test. Re-executing from step 0 while serving
completed work from history is cleat's central architectural claim, **no
upstream suite tests it**, and a workflow author currently has no supported way
to observe it either.
"""

import pytest

SLEEP_MS = 3000


@pytest.mark.skip(
    reason="BLOCKED: no primitive captures a non-deterministic value across a "
           "replay. h.NewUUID() is a constant (cleat#775); query state is not "
           "readable mid-suspension; h.SideEffect validates instead of caching "
           "and fails the run on divergence, including on values from h.Now(), "
           "which cleat vet E003 recommends as the deterministic clock."
)
def test_a_captured_value_is_not_recomputed_after_a_suspension():
    """Cleat's central claim. Left in place, skipped, rather than omitted.

    An absent test is indistinguishable from an untried one, and this is the
    assertion a reader comparing cleat to DBOS or Temporal will look for first.
    """


def test_a_suspension_really_suspends(cleat, replay_identity_workflow):
    """What can be asserted today: the run does suspend for its full duration.

    Not the determinism claim, and not a substitute for it. Kept because it is
    the half that is measurable from outside, and because it is what caught the
    input-binding defect: while this port passed `{"input": 3000}` instead of
    `{"input": {"ms": 3000}}`, `ms` bound to zero, every sleep was a no-op, and
    every timing assertion in this port held for the wrong reason.
    """
    import time

    started_at = time.monotonic()
    status, started = cleat.start(replay_identity_workflow, {"ms": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    elapsed_ms = (time.monotonic() - started_at) * 1000

    assert final["status"] == "done", (
        f"run did not complete: {final.get('status')!r} "
        f"{(final.get('error') or '')[:200]!r}"
    )
    assert elapsed_ms >= SLEEP_MS * 0.8, (
        f"the run finished in {elapsed_ms:.0f}ms for a requested {SLEEP_MS}ms "
        "sleep, so it never actually suspended"
    )
