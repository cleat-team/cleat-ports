"""Detached execution, ported from dbos-transact-py's fire-and-forget tests.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS starts a workflow without waiting via `start_workflow` and holds a handle.
Cleat's equivalent is `h.RunDetached(name, inputJSON)`: the started workflow is
not awaited and the caller gets no handle back, so there is nothing to poll.

**That absence is what makes this test shaped the way it is.** With no handle,
the only way to know the detached workflow ran is to have it do something
observable, so it calls the fixture service with a key the test chose. The
parent completing proves the request was accepted — and until cleat#796 that
was all it ever proved, because `RunDetached` took a closure, could not be
wired across the WASM ABI, and its unwired branch returned nil. It worked under
`localdev` and `cleattest`, which populate the field in-process, and started
nothing in every compiled workflow.

A conformance suite that ran only against the test double would have called
this feature healthy for as long as it existed.
"""

import json
import time
import uuid

import pytest


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_detached_workflow_actually_runs(cleat, detached_workflow, fixture_calls):
    """The assertion the feature failed for its whole life.

    The parent returns as soon as the request is accepted, so the test waits on
    the fixture rather than on any workflow: the detached run reaching the
    service is the only evidence it exists.
    """
    key = str(uuid.uuid4())

    status, started = cleat.start(detached_workflow, {"key": key, "seq": 1})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"parent did not complete: {final!r}"
    assert _body(final)["outcome"] == "requested"

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if fixture_calls(key) >= 1:
            break
        time.sleep(0.25)

    assert fixture_calls(key) >= 1, (
        "the parent reported the detached workflow was requested and the "
        "service was never called, so nothing ran. This is the cleat#796 shape: "
        "RunDetached returned success and started nothing in every compiled "
        "workflow, while working under localdev and cleattest."
    )


def test_the_parent_does_not_wait_for_the_detached_run(cleat, detached_workflow, fixture_calls):
    """Fire-and-forget: the parent must finish without the child finishing.

    Guards the test above from passing on an implementation that simply ran the
    child inline — which is exactly what the old closure form did under
    localdev and cleattest, and why it looked correct there.

    The detached run sleeps via its retry interval, so the parent completing
    well inside that window is evidence it did not wait.
    """
    key = str(uuid.uuid4())

    started_at = time.monotonic()
    status, started = cleat.start(detached_workflow, {"key": key, "seq": 1})
    assert status == 201

    final = cleat.await_terminal(started["id"], timeout=60.0)
    parent_ms = (time.monotonic() - started_at) * 1000

    assert final["status"] == "done"
    assert parent_ms < 15_000, (
        f"the parent took {parent_ms:.0f}ms; a fire-and-forget start should "
        "return without waiting for the workflow it started"
    )


@pytest.mark.skip(
    reason="GAP: RunDetached returns no handle, so a caller cannot address the "
           "workflow it started — no status, no result, no cancellation. DBOS's "
           "start_workflow returns a handle and its tests assert on it. Cleat's "
           "host call cleat_run_detached does compute a run ID internally; it "
           "is simply not returned to the guest."
)
def test_a_detached_run_can_be_addressed_by_its_caller():
    """Upstream's handle-based assertion, kept visible rather than dropped."""
