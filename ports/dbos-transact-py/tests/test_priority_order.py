"""Does priority actually order dispatch, or is it only recorded?

test_priority_is_accepted_and_recorded pins the half that is checkable without
a race -- the value survives the round trip -- and says why it stops there:

    asserting observed order needs the worker saturated so that work actually
    queues ... there is no way from here to hold the worker busy and enqueue
    behind it deterministically. A timing race dressed as an ordering assertion
    would fail for reasons unrelated to priority.

That is right about the race and wrong about there being no way. THE FIRST
BATCH is racy -- the worker starts claiming while later starts are still being
issued, so arrival order contaminates it. THE SECOND BATCH is not: by the time
the first batch of long-held slots frees, every workflow has been enqueued for
seconds, and which of the REMAINDER gets claimed next is a pure ordering
question with no race left in it.

My first attempt at this stopped the worker to build the backlog. That does not
work and the failure is instructive: the API is served BY the worker process,
so with it stopped there is nothing to accept a start. Saturation, not absence.

The distinction matters because "priority is recorded" and "priority is
honoured" is the same pair as a live reader with no writer -- a value that
round-trips and changes nothing.
"""

import time
import uuid

import pytest


CONCURRENCY = 10          # the shared worker's -concurrency
ENQUEUED = 24             # comfortably more than two batches
HOLD_MS = 9000            # long enough that batch 1 is still held while batch 2 waits


def _priorities(fixture_log, key):
    """Priorities in the order the fixture saw them start."""
    return [int(c.split(".p", 1)[1]) for c in fixture_log(key)]


def test_priority_orders_the_second_batch(cleat, priority_mark_workflow, fixture_log):
    """Of the work still queued, the worker claims the best priorities next.

    THE CONTROL IS THE ASSIGNMENT ORDER. Priorities are assigned in REVERSE
    enqueue order -- the first workflow started gets the worst priority, the
    last gets the best -- so ordering by `created_at` alone produces the exact
    opposite answer. A pass cannot be explained by insertion order.

    Only the second batch is asserted. The first is contaminated by the enqueue
    race the existing test correctly identified, and is used here only to
    establish which workflows were still waiting.
    """
    key = f"prio-order-{uuid.uuid4().hex[:8]}"

    for i in range(ENQUEUED):
        priority = ENQUEUED - 1 - i            # reverse of enqueue order
        status, run = cleat.start(
            priority_mark_workflow,
            {"key": key, "priority": priority, "holdMs": HOLD_MS},
            priority=priority,
        )
        assert status == 201, f"start {i} rejected: {status} {run}"

    # Wait for everything, then compare the two halves of what remains after
    # the enqueue window.
    #
    # THE FIRST `CONCURRENCY` ARRIVALS ARE EXCLUDED, and that is a statement
    # about the system rather than a convenience. The worker begins claiming as
    # soon as the first start lands, while the rest are still being issued --
    # so those claims are made from a queue that does not yet contain the
    # better priorities. They cannot be ordered with respect to work that did
    # not exist.
    #
    # The measured arrival order shows it plainly:
    #
    #   [19,16,23,18,20,17,22,21, | 1,2,0,6,8,4,7,3,5, | 13,15,12,9,11,10,14]
    #
    # The first eight are the WORST priorities -- claimed during enqueue, in
    # arrival order, exactly as expected. Everything after is near-perfectly
    # ordered.
    #
    # Two earlier versions of this assertion tried to slice into batches and
    # scored 9 of 10, then 8 of 10 under a fuller suite. The fix for that is
    # not a looser threshold: slots free one at a time, so there is no instant
    # at which a batch exists as a set, and any membership assertion is partly
    # an assertion about where an arbitrary cut fell. Comparing means of the
    # post-enqueue remainder has no cut to get wrong and uses every
    # observation.
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and len(_priorities(fixture_log, key)) < ENQUEUED:
        time.sleep(0.2)
    seen = _priorities(fixture_log, key)
    assert len(seen) == ENQUEUED, (
        f"only {len(seen)} of {ENQUEUED} workflows started within 180s: {seen}"
    )

    ordered = seen[CONCURRENCY:]          # after the enqueue window
    half = len(ordered) // 2
    first_mean = sum(ordered[:half]) / half
    second_mean = sum(ordered[half:]) / len(ordered[half:])

    assert first_mean + 4 <= second_mean, (
        f"among the {len(ordered)} workflows claimed after the enqueue window, the "
        f"first {half} averaged priority {first_mean:.1f} and the rest averaged "
        f"{second_mean:.1f}; expected the earlier ones to be at least 4 better.\n"
        f"arrival order: {seen}\n"
        f"post-enqueue:  {ordered}\n"
        f"Priorities were assigned in REVERSE enqueue order, so created_at alone "
        f"would reverse this sign, and ignoring priority would make the means "
        f"roughly equal.\n"
        f"The claim query orders by `priority ASC, created_at` on all three "
        f"dialects; if that is not observable, the field is recorded and unused."
    )


def test_every_enqueued_workflow_eventually_runs(cleat, priority_mark_workflow, fixture_log):
    """The control for the test above.

    If work queued behind a saturated worker were dropped rather than deferred,
    the ordering assertion would be describing a subset that survived by some
    other route. This asserts the plain thing, with a short hold so it is about
    completeness rather than slots.
    """
    key = f"prio-drain-{uuid.uuid4().hex[:8]}"
    count = CONCURRENCY + 4

    for i in range(count):
        status, _ = cleat.start(
            priority_mark_workflow,
            {"key": key, "priority": i, "holdMs": 200},
            priority=i,
        )
        assert status == 201, f"start {i} rejected: {status}"

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if len(_priorities(fixture_log, key)) >= count:
            return
        time.sleep(0.3)

    seen = _priorities(fixture_log, key)
    pytest.fail(
        f"only {len(seen)} of {count} enqueued workflows ran within 120s: {seen}. "
        f"Work queued behind a saturated worker must be claimed as slots free; "
        f"if it is not, the queue silently loses anything submitted past capacity."
    )
