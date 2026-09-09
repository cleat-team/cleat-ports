"""What cancelling a parent does, and to whom.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream's `test_cancel_workflow_children` builds parent -> child -> grandchild,
cancels the parent, and asserts all three observe it: cancellation is a property
of the subtree, applied at once.

cleat's answer is opt-in per child. Three things are measured here, each with
the control that makes it mean something:

1. **A cancelled parent parked in a child await is not stopped.** It runs to
   completion on its own schedule and returns its result normally.
   `AwaitChild` does not check `PollCancellation`, and entry 21 records that
   cleat's cancellation is cooperative by design.
2. **A `REQUEST_CANCEL` child does observe it, and stops early** -- measured at
   6.75s against a 120s budget, roughly 1.75s after the cancel.
   (Budgets were shortened afterwards; see the constants.)
3. **An `ABANDON` child does not** -- it ran its budget out in full and
   reported `completed`. This is the control, and it is the reason 2 is a statement
   about the policy rather than about cancellation in general.

**What is deliberately NOT claimed here: when the flag is written.** Two probes
disagreed and the disagreement is unresolved. A polling child observes
cancellation ~1.75s after the cancel, while sampling `cancellation_requested`
directly for a NON-polling child showed the column flipping only when the
parent closed, ~15s later. `PollCancellation` reads the workflow's own column
(`CheckCancellation`, `engine/store_signals.go:34`) with no parent traversal,
so both cannot be true of the same mechanism and one of the two probes is
measuring something other than what it appears to.

The assertions below are chosen to survive either answer: they are about which
children observe cancellation and whether they stop early, not about when a
column changes. Pinning the timing would need a third measurement, and ISSUES
entry 29 records it as open rather than guessing.

**Why two children in one parent.** The parent cannot close until the child it
awaits has finished, and the `REQUEST_CANCEL` arm of `enforceParentClosePolicy`
carries `AND status NOT IN ('done','failed')`. So an awaited child can never be
the one propagation reaches. The long child is never awaited.

**Why the long child is `cancellable`.** `cancellation_requested` is a column
no API exposes, and nothing else in this suite reads the database -- doing so
would also make the assertion dialect-specific. `cancellable` polls
`PollCancellation` and returns `{"outcome":"cancelled"}`, turning the flag into
a result an ordinary GET can see.

**These tests assert cleat's behaviour, not upstream's.** It is a divergence
nobody has adjudicated, so they record what cleat does and entry 29 states the
question. If cleat ever adopts subtree cancellation they should fail, and that
failure is the point.
"""

import json
import time
import uuid

import pytest

from conftest import wait_until

# The short child bounds how long the parent stays parked; the long child must
# outlast it comfortably so that it is unambiguously still running when the
# parent closes.
#
# Sized down from 20s/120s once the behaviour was established. The ABANDON
# control has to wait out the long child in full -- that is what it asserts --
# so LONG_MS is the module's floor, and 120s cost the shared suite two minutes
# to re-establish a separation 45s makes just as clearly. The REQUEST_CANCEL
# child is reached about 1.75s after the cancel, so it has ~40s of headroom
# either way.
SHORT_MS = 10000
LONG_MS = 45000


def _result(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


@pytest.fixture(scope="module")
def parked_parent(cleat, cancel_awaiting_parent_workflow):
    """Start the parent, let it park in its await, then cancel it.

    Module-scoped: both tests below ask about one cancelled run, and starting a
    second would double a 20s wait for nothing. They read different parts of the
    same outcome.
    """
    tag = uuid.uuid4().hex[:6]
    status, started = cleat.start(cancel_awaiting_parent_workflow,
                                  {"shortMs": SHORT_MS, "longMs": LONG_MS, "tag": tag})
    assert status == 201, f"start rejected: {status} {started}"
    parent = started["id"]

    # The parent must be parked in AwaitChild before the cancel lands, or this
    # measures cancelling a starting workflow -- a different case.
    wait_until(lambda: cleat.get(parent)[1].get("status") in ("ready", "running"),
               timeout=60.0, what="the parent to be running")
    time.sleep(5)

    status, _ = cleat.cancel(parent, reason="port test: ISSUES entry 29")
    assert status == 200, f"cancel rejected: {status}"

    final = cleat.await_terminal(parent, timeout=180.0)
    return final


def test_cancelling_a_parked_parent_does_not_stop_it(parked_parent):
    """The parent finishes normally, on its own schedule, flag or no flag."""
    assert parked_parent["status"] == "done", (
        f"the parent did not complete: {parked_parent['status']}. The subject of "
        "this test is that cancellation does NOT stop a parent parked in a child "
        "await; a parent that stopped would mean cleat had adopted pre-emptive "
        "cancellation, which entry 21 records it deliberately does not have."
    )
    body = _result(parked_parent)
    assert body["outcome"] == "completed", (
        f"the parent reported {body['outcome']!r} rather than completing: {body}. "
        "`AwaitChild` does not check `PollCancellation`, so the await returns its "
        "result as though no cancel had happened."
    )


def test_a_live_request_cancel_child_observes_the_cancellation(
        cleat, parked_parent):
    """A REQUEST_CANCEL child is reached, and stops well short of its budget."""
    long_id = _result(parked_parent)["long"]

    # The parent has already reached a terminal state, so the close hook has run
    # or is running. The child observes its flag at its next poll, within 250ms
    # of it being set, so a short wait is enough.
    final = cleat.await_terminal(long_id, timeout=60.0)

    assert final["status"] == "done", f"the long child did not finish: {final}"
    body = _result(final)
    assert body["outcome"] == "cancelled", (
        f"the long child reported {body['outcome']!r}: {body}. It polls "
        "PollCancellation every 250ms and was declared REQUEST_CANCEL, so "
        "'completed' here means cancellation never reached it at all. The "
        "ABANDON control below is what makes this a statement about the "
        "policy rather than about cancellation in general."
    )

    # It stopped EARLY. Without this, a child that ran its full LONG_MS and
    # happened to report cancellation at the end would pass, and the claim is
    # that propagation is what ended it.
    assert body["elapsed_ms"] < LONG_MS, (
        f"the long child observed cancellation only after running its full "
        f"{LONG_MS}ms ({body['elapsed_ms']}ms): {body}. The flag would then have "
        "arrived too late to have shortened anything."
    )


def test_an_abandon_child_is_not_reached_at_all(cleat, abandon_variant_workflow):
    """The control. Identical shape, one word different, opposite outcome.

    Without this the previous test is not evidence about `REQUEST_CANCEL`: a
    child that stopped early for any other reason -- the worker noticing the
    parent had gone, a cascade nobody documented, a coincidence of timing --
    would satisfy it just as well.

    A SEPARATE WORKFLOW, not a parameter, and that is not tidiness. The first
    attempt at this control edited the policy in place and redeployed under the
    same name. Both deploys reported `v1`, the run picked up the old module, and
    the control PASSED -- reporting `cancelled` for what was supposed to be an
    ABANDON child, which read as "propagation ignores the policy". Two distinct
    definition names make that failure impossible to reproduce by accident.
    """
    tag = uuid.uuid4().hex[:6]
    status, started = cleat.start(abandon_variant_workflow,
                                  {"shortMs": SHORT_MS, "longMs": LONG_MS, "tag": tag})
    assert status == 201, f"start rejected: {status} {started}"
    parent = started["id"]

    wait_until(lambda: cleat.get(parent)[1].get("status") in ("ready", "running"),
               timeout=60.0, what="the parent to be running")
    time.sleep(5)
    assert cleat.cancel(parent, reason="port test: entry 29 control")[0] == 200

    final = cleat.await_terminal(parent, timeout=180.0)
    assert final["status"] == "done", f"the control parent did not complete: {final}"
    long_id = _result(final)["long"]

    child = cleat.await_terminal(long_id, timeout=LONG_MS / 1000 + 60)
    body = _result(child)
    assert body["outcome"] == "completed", (
        f"the ABANDON child reported {body['outcome']!r}: {body}. ABANDON means "
        "the child is not reached, so anything else here means cancellation "
        "propagates regardless of policy -- and the REQUEST_CANCEL test above "
        "would then be measuring nothing."
    )
    assert body["elapsed_ms"] >= LONG_MS, (
        f"the ABANDON child stopped early at {body['elapsed_ms']}ms of {LONG_MS}ms: "
        f"{body}. It reported completion, so something ended it without going "
        "through the cancellation path it polls."
    )
