"""Does the promise wake path have cleat#953's defect?

#953 was measured on signals: a delivery arriving while the workflow is AWAKE
matches zero rows on the wake update -- the predicate is
`status IN ('ready','suspended')` and a claimed workflow is `'running'` -- and
finalize then overwrites any pulled-forward wake with the workflow's own
timeout.

The identical predicate guards three more sites:

    engine/store_promises.go:70    a resolved promise
    engine/store_promises.go:103   a rejected promise
    engine/store_promises.go:218   a dispatched update request

Those were identified by READING the predicate. This asks the question by
running it, because the fix's scope was deliberately limited to what has been
measured -- four plausible hypotheses about this engine have died on contact
with a measurement in the last two days, and a source read is not one.

The shape mirrors the signal reproduction: awaiting several in sequence means
later resolutions land while the workflow is still handling an earlier one.
"""

import json
import time
import uuid

import pytest


COUNT = 5
BUDGET_MS = 20000


def _promise_ids(cleat, run_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, body = cleat.query(run_id, "promises")
        if code == 200 and body.get("value"):
            return body["value"].split(",")
        time.sleep(0.2)
    pytest.fail(f"run {run_id} never published its promise ids")


def test_promises_resolved_while_the_workflow_is_awake_are_not_lost(
    cleat, promise_chain_workflow
):
    """Resolve every promise with no gap, then see whether the workflow finishes.

    Under #953's mechanism the first resolution wakes a suspended workflow
    normally; the rest arrive while it is `running`, schedule no wake, and are
    invisible until the budget expires. The run would report `resolved` short of
    COUNT with `timedOut` true, while every promise is resolved in the table.
    """
    key = f"pchain-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(promise_chain_workflow, {
        "key": key, "count": COUNT, "budgetMs": BUDGET_MS,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    ids = _promise_ids(cleat, run_id)
    assert len(ids) == COUNT, f"expected {COUNT} promise ids, got {ids}"

    # No gaps: the point is that later resolutions arrive while the workflow is
    # awake handling an earlier one.
    for i, pid in enumerate(ids):
        code, body = cleat.resolve_promise(run_id, pid, f'{{"n":{i}}}')
        assert code in (200, 201), f"resolving promise {i} answered {code}: {body!r}"

    final = cleat.await_terminal(run_id, timeout=60.0)
    result = json.loads(final["result"]) if isinstance(final["result"], str) else final["result"]

    assert final["status"] == "done", f"the run ended {final['status']}: {final.get('error')}"
    assert result["resolved"] == COUNT and not result["timedOut"], (
        f"awaited {COUNT} promises, resolved {result['resolved']}, "
        f"timedOut={result['timedOut']}.\n"
        f"All {COUNT} were resolved over HTTP before the budget expired. If the run "
        f"stalled, the promise wake path has cleat#953's defect -- a resolution "
        f"arriving while the workflow is 'running' schedules no wake, and finalize "
        f"overwrites the deadline with the workflow's own timeout.\n"
        f"result: {result}"
    )


def test_one_promise_resolved_against_a_suspended_workflow_still_wakes_it(
    cleat, promise_chain_workflow
):
    """The control, and it is what makes the test above about timing.

    A single promise, resolved once the workflow is demonstrably waiting. If
    this fails, the promise wake path is broken outright rather than broken for
    resolutions that arrive at the wrong moment -- a different and larger claim.
    """
    key = f"pone-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(promise_chain_workflow, {
        "key": key, "count": 1, "budgetMs": BUDGET_MS,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    ids = _promise_ids(cleat, run_id)
    # Let it reach the await and suspend, so the resolution lands on a row that
    # is 'ready' rather than 'running'.
    time.sleep(3)

    code, body = cleat.resolve_promise(run_id, ids[0], '{"n":0}')
    assert code in (200, 201), f"resolving answered {code}: {body!r}"

    final = cleat.await_terminal(run_id, timeout=60.0)
    result = json.loads(final["result"]) if isinstance(final["result"], str) else final["result"]
    assert result["resolved"] == 1 and not result["timedOut"], (
        f"a single promise resolved against a suspended workflow did not wake it: "
        f"{result}. This is not #953's timing case -- it is the promise wake path "
        f"failing outright."
    )
