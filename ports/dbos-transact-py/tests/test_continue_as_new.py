"""Continue-as-new: a workflow that restarts itself with fresh input.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS uses this to keep a long-running workflow's history bounded -- the point
is that the run ends and a successor begins with the same identity and a
smaller history, rather than one run accumulating events forever.

The assertion is the fixture's call count, not the returned value. Each
iteration announces itself under the same key, so the count is the number of
iterations that actually executed. A returned value cannot make this claim: the
final run's result is identical whether it was the third iteration or the
first, so a chain that silently stopped after one would look exactly like a
complete one.
"""

import json
import time
import uuid

import pytest

ITERATIONS = 3


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _wait_until(predicate, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


def test_a_workflow_can_continue_as_new_and_every_iteration_runs(
    cleat, continue_as_new_workflow, fixture_calls
):
    key = f"can-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(
        continue_as_new_workflow, {"key": key, "remaining": ITERATIONS}
    )
    assert status == 201, f"start rejected: {status} {started}"

    _wait_until(
        lambda: fixture_calls(key) >= ITERATIONS,
        timeout=90.0,
        what=f"all {ITERATIONS} iterations to run",
    )

    # Settle, so an extra iteration would be visible rather than merely late.
    time.sleep(2.0)
    assert fixture_calls(key) == ITERATIONS, (
        f"{fixture_calls(key)} iterations ran, expected {ITERATIONS}. More than "
        "asked for means the chain does not terminate; fewer means a link was "
        "dropped and the workflow reported success without doing the work."
    )


@pytest.mark.skip(
    reason="GAP: continue-as-new inserts a NEW instance row with a fresh "
           "gen_random_uuid() and nothing links it to its predecessor. The "
           "caller's run completes with {} and there is no way to reach the run "
           "carrying the real result -- parent_workflow_id is null on the "
           "continuation. DBOS and Temporal both preserve the workflow identity "
           "across the transition. cleat#826."
)
def test_the_workflow_id_survives_the_transition(
    cleat, continue_as_new_workflow, fixture_calls
):
    """Continue-as-new starts a new RUN of the same WORKFLOW.

    Left visible rather than deleted: this is the assertion a reader expects,
    and it is the one that says whether a caller can follow the chain at all.
    """
    key = f"can-id-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(continue_as_new_workflow, {"key": key, "remaining": 2})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"the chain did not complete: {final!r}"

    body = _body(final)
    assert body["outcome"] == "finished", (
        f"the last iteration reported {body!r}. `continue-did-not-take-effect` "
        "means ContinueAsNew returned without ending the run, so the workflow "
        "carried on and returned from the wrong place."
    )
    assert body["workflowId"] == started["id"], (
        f"the workflow id changed across continue-as-new: started {started['id']!r}, "
        f"finished as {body['workflowId']!r}"
    )
