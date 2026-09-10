"""Cancelling several workflows at once, ported from dbos-transact-py's
tests/test_workflow_management.py.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream reference:
  test_bulk_cancel  tests/test_workflow_management.py

Upstream's `DBOS.cancel_workflows(wfids)` takes a **list of ids, not a filter**,
which is what makes this portable: it re-expresses as a loop over cleat's
`POST /api/workflows/:id/cancel` without inventing a query language cleat does
not have. Had it taken a filter, the port would be blocked on the listing gap
recorded in cleat#1122 rather than on anything about cancellation.

**The assertion is a durable side effect that did not happen.** Three workflows
each complete a first step, block, and would then run a second. All three are
cancelled; the first step must have run on every one and the second on none.
The counts come from the fixture service rather than from the workflows'
results, because a cancelled run reporting "I did not run step two" is the
defendant testifying.

**WHICH LAYER HOLDS `steps_two == 0` UP, measured rather than assumed.** Not the
workflow's cooperative poll -- the ENGINE. With the poll disabled so the
workflow ignores its cancellation entirely and runs on to step two, the count is
*still* zero: the durable call is refused with

    durable call steps.two: [0] workflow cancelled

So that assertion is true of cleat for a stronger reason than this test needs,
and it **cannot discriminate**: it passes whether or not the workflow observes
anything. The assertion that does discriminate is `outcome == "cancelled"`,
which under the same mutation reports `step_two_failed`.

Both are kept. `steps_two == 0` is upstream's property and is worth pinning; it
is simply not evidence about cooperation, and an earlier version of this comment
claimed it was. That is worth knowing beyond this file: **cleat's cancellation
is cooperative for a workflow's own control flow and ENFORCED at the host-call
boundary.** ISSUES entry 21 records the first half; the second is measured here.

**Not covered by the existing cancellation tests, checked before writing this.**
`test_cancellation.py`'s four cases are all single-workflow and assert on the
outcome string; `test_workflow_management.py` is force-complete/force-fail.
Nothing cancelled several runs and asserted that none advanced.
"""

import json
import uuid

from conftest import wait_until

# Long enough that all three runs are still in their poll loop when the cancels
# arrive, short enough that a run which somehow misses its cancel still ends the
# test rather than hanging it. A run that ignores cancellation reaches step two
# and fails the assertion, which is the outcome we want from that bug -- not a
# timeout, which says nothing about why.
RUN_MS = 20_000
WORKFLOWS = 3


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_cancelling_several_workflows_stops_all_of_them_before_their_next_step(
    cleat, bulk_cancel_workflow, fixture_calls
):
    key = f"bulk-cancel-{uuid.uuid4().hex[:8]}"

    run_ids = []
    for _ in range(WORKFLOWS):
        status, started = cleat.start(bulk_cancel_workflow, {"key": key, "ms": RUN_MS})
        assert status == 201, f"start rejected: {status} {started}"
        run_ids.append(started["id"])
    assert len(set(run_ids)) == WORKFLOWS, "each start should be a distinct run"

    # Cancel only once every run has finished step one. Cancelling earlier
    # would let a run be stopped BEFORE its first step, which passes the
    # `steps_two == 0` assertion for the wrong reason -- nothing ran at all.
    # Upstream's fixture blocks on an event for the same purpose.
    wait_until(
        lambda: fixture_calls(f"{key}-one") == WORKFLOWS,
        timeout=60.0,
        what=f"all {WORKFLOWS} workflows to complete step one",
    )

    for run_id in run_ids:
        status, _ = cleat.cancel(run_id)
        assert status == 200, f"cancel of {run_id} was not accepted: {status}"

    for run_id in run_ids:
        final = cleat.await_terminal(run_id, timeout=90.0)
        body = _body(final)
        assert body["outcome"] == "cancelled", (
            f"run {run_id} ended {body!r}. Every one of these was cancelled "
            f"while polling, so `completed` means the cancel did not reach it "
            f"-- and a run that reaches `completed` has run step two."
        )

    assert fixture_calls(f"{key}-one") == WORKFLOWS, (
        f"step one ran {fixture_calls(f'{key}-one')} times, want {WORKFLOWS}. "
        f"The cancels arrived before the workflows did their first step, so "
        f"the step-two assertion below would pass without meaning anything."
    )
    assert fixture_calls(f"{key}-two") == 0, (
        f"step two ran {fixture_calls(f'{key}-two')} times and should never "
        f"have run. This is upstream's property -- work downstream of a cancel "
        f"must not happen -- but note what a FAILURE here would mean: the "
        f"engine refuses durable calls from a cancelled run, so reaching the "
        f"fixture at all means that refusal has stopped working, not merely "
        f"that a workflow ignored its cancel. See the module docstring; the "
        f"assertion that discriminates on cooperation is the outcome check "
        f"above."
    )


def test_cancelling_one_of_several_leaves_the_others_running(
    cleat, bulk_cancel_workflow, fixture_calls
):
    """The control, without which the test above is satisfied by a cancel that
    is too broad.

    `steps_two == 0` across three runs is also what a cancel that stopped
    everything in the deployment would produce. Cancelling one of three and
    watching the other two reach step two is what distinguishes "cancel reached
    its targets" from "cancel reached everything".
    """
    key = f"bulk-cancel-one-{uuid.uuid4().hex[:8]}"

    run_ids = []
    for _ in range(WORKFLOWS):
        status, started = cleat.start(bulk_cancel_workflow, {"key": key, "ms": 3_000})
        assert status == 201, f"start rejected: {status} {started}"
        run_ids.append(started["id"])

    wait_until(
        lambda: fixture_calls(f"{key}-one") == WORKFLOWS,
        timeout=60.0,
        what=f"all {WORKFLOWS} workflows to complete step one",
    )

    status, _ = cleat.cancel(run_ids[0])
    assert status == 200, f"cancel was not accepted: {status}"

    outcomes = {}
    for run_id in run_ids:
        outcomes[run_id] = _body(cleat.await_terminal(run_id, timeout=90.0))["outcome"]

    assert outcomes[run_ids[0]] == "cancelled", (
        f"the cancelled run reported {outcomes[run_ids[0]]!r}"
    )
    others = [outcomes[r] for r in run_ids[1:]]
    assert others == ["completed"] * (WORKFLOWS - 1), (
        f"the runs that were NOT cancelled reported {others}, want all "
        f"'completed'. A cancel that stops runs it was not given is worse than "
        f"one that misses: it would make the bulk test above pass while being "
        f"catastrophic in production."
    )
    assert fixture_calls(f"{key}-two") == WORKFLOWS - 1, (
        f"step two ran {fixture_calls(f'{key}-two')} times, want "
        f"{WORKFLOWS - 1} -- one per uncancelled run."
    )
