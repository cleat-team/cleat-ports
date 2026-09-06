"""Cancellation, ported from dbos-transact-py's workflow-management tests.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Cleat and DBOS differ here in two ways, and both are visible from outside:

**Cancellation is cooperative.** `POST /api/workflows/:id/cancel` records the
request; nothing enforces it. A workflow observes it by calling
`h.PollCancellation()` and deciding what to do. One that never asks runs to
completion, and the cancel request returns 200 either way. DBOS's
`cancel_workflow` stops the workflow whether or not it cooperates.

**There is no cancelled terminal status.** The engine writes `ready`, `running`,
`done`, `failed`, `terminated`, `terminating` and `dead_lettered`, and nothing
else. A workflow that observed its cancellation and returned ends in `done` --
the same status as one that succeeded. `ErrCancelled` exists as an error class
but never as a workflow state. So from the outside, a cancelled workflow and a
completed one are distinguishable only by whatever the workflow chose to put in
its own result payload.

Both are asserted below rather than described, because a divergence that is only
written down in a comment is one that can regress silently.
"""

import json

import pytest

RUN_MS = 6000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_polling_workflow_observes_cancellation(cleat, cancellable_workflow):
    """The half that works like the upstream test: cancel takes effect."""
    status, started = cleat.start(cancellable_workflow, {"ms": RUN_MS, "poll": 1})
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    status, _ = cleat.cancel(run_id)
    assert status == 200, f"cancel was not accepted: {status}"

    final = cleat.await_terminal(run_id, timeout=30.0)
    body = _body(final)

    assert body["outcome"] == "cancelled", (
        f"a polling workflow did not observe its cancellation: {body!r}"
    )
    assert body["elapsed_ms"] < RUN_MS, (
        f"the workflow ran its full {RUN_MS}ms despite being cancelled: {body!r}"
    )


def test_a_cancelled_workflow_still_reports_status_done(cleat, cancellable_workflow):
    """Pins the divergence: there is no cancelled status to end up in.

    Asserting `done` may read strangely. It is deliberate. If cleat ever grows a
    real cancelled state this test fails, which is exactly when the port should
    be revisited -- and until then it records that an operator cannot tell a
    cancelled run from a successful one by status alone.
    """
    status, started = cleat.start(cancellable_workflow, {"ms": RUN_MS, "poll": 1})
    assert status == 201
    run_id = started["id"]

    assert cleat.cancel(run_id)[0] == 200
    final = cleat.await_terminal(run_id, timeout=30.0)

    assert final["status"] == "done", (
        f"expected the cancelled run to report 'done', got {final['status']!r}. "
        "If this now reports a distinct cancelled state, cleat has gained one "
        "and this port's cancellation mapping should be revisited."
    )
    assert _body(final)["outcome"] == "cancelled", (
        "the run reported 'done' and its payload does not say it was cancelled, "
        "so nothing anywhere records that a cancellation happened"
    )


def test_cancellation_is_cooperative_and_a_workflow_may_ignore_it(cleat, cancellable_workflow):
    """A workflow that never polls is unaffected by cancel.

    This is the assertion a reader coming from DBOS or Temporal will least
    expect, so it is asserted rather than left as prose. `poll=0` never calls
    PollCancellation; the run completes normally and reports the full elapsed
    time, after a cancel that returned 200.
    """
    status, started = cleat.start(cancellable_workflow, {"ms": RUN_MS, "poll": 0})
    assert status == 201
    run_id = started["id"]

    status, _ = cleat.cancel(run_id)
    assert status == 200, (
        f"cancel returned {status}; the point of this test is that it is "
        "accepted and then has no effect"
    )

    final = cleat.await_terminal(run_id, timeout=30.0)
    body = _body(final)

    assert final["status"] == "done"
    assert body["outcome"] == "completed", (
        f"a non-polling workflow was stopped by cancel: {body!r}. If cleat has "
        "made cancellation pre-emptive, this port's mapping needs revisiting."
    )
    assert body["elapsed_ms"] >= RUN_MS, (
        f"the run stopped early at {body['elapsed_ms']}ms without polling"
    )


@pytest.mark.skip(
    reason="GAP: cleat has no pre-emptive cancellation and no cancelled terminal "
           "status. DBOS's cancel_workflow stops a workflow regardless of "
           "cooperation and leaves it in a distinct state; cleat records the "
           "request and leaves both the stopping and the reporting to the "
           "workflow. Porting upstream's assertion verbatim would require "
           "semantics that do not exist."
)
def test_cancel_stops_a_workflow_that_does_not_cooperate():
    """Upstream's cancel_workflow assertion, kept visible rather than dropped."""
