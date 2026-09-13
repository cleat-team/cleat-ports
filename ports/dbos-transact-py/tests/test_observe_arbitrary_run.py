"""Reading an arbitrary workflow's status from inside a workflow.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Ports dbos-transact-py's `test_retrieve_workflow_in_workflow`: `retrieve_workflow(id)`
called from within a running workflow, for a run the caller did not spawn.

This case sat in `worklists/test-dbos.md` as "needs something cleat lacks" and
in ISSUES as entry 33, on the premise that `cleat_poll_child` and
`cleat_await_child` are the only guest-side cross-workflow reads and are
**children-only**. The premise was never measured, and it is false.
`PollChild` hands the run id straight to `GetChildResult`, whose query is
`WHERE id = ?` with no parentage predicate on postgres, mysql or mssql, and the
ABI binding does not filter either. Recorded on cleat#1120.

So the capability exists and is merely misnamed -- the `child` in `poll_child`
names the common case, not a restriction. That makes this case portable, and
it belongs in the suite for a reason beyond tidiness: **it is the only test
that would notice if the parentage restriction were ever added.** Adding one
would be a defensible design choice, but it would silently break any workflow
observing a run it did not spawn, and nothing else here looks.
"""

import json
import uuid

import pytest

LEAF_MS = 200


@pytest.fixture(scope="session")
def observe_workflow(cleat) -> str:
    """Deploy the observer and the leaf it observes.

    The leaf is deployed by the fan-out fixture too; deploying it again under
    the same name is idempotent and keeps this module independent of the order
    pytest happens to pick.
    """
    from conftest import _build_and_deploy

    _build_and_deploy("childleaf", "child_leaf")
    return _build_and_deploy("observerun", "observe_run")


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_workflow_can_read_the_status_of_a_run_it_did_not_spawn(cleat, observe_workflow):
    """Upstream's assertion: observe an arbitrary run from inside a workflow.

    The observed run is started through the API before the observer exists, so
    it cannot be the observer's child by construction. The test does not rest
    on that construction alone -- it reads `parent_workflow_id` back and
    asserts it is absent, because "it is not a child" is the entire content of
    the assertion and a port that quietly observed a child would pass while
    testing nothing. That is the mistake this case was originally shelved for.
    """
    tag = f"observed-{uuid.uuid4().hex[:8]}"

    # A standalone run, spawned by nobody.
    status, leaf = cleat.start("child_leaf", {"ms": LEAF_MS, "tag": tag})
    assert status == 201, f"leaf start rejected: {status} {leaf}"
    leaf_id = leaf["id"]
    leaf_final = cleat.await_terminal(leaf_id, timeout=60.0)
    assert leaf_final["status"] == "done", (
        f"the leaf did not complete: {leaf_final.get('status')!r} "
        f"{(leaf_final.get('error') or '')[:300]!r}"
    )

    # THE CONTROL. If this run has a parent, the test below is observing a
    # child and the upstream assertion is not being made.
    assert not leaf_final.get("parent_workflow_id"), (
        f"the observed run has parent_workflow_id="
        f"{leaf_final.get('parent_workflow_id')!r}, so it IS somebody's child "
        f"and this test is not asserting what it claims"
    )

    # Now observe it from inside a workflow.
    status, obs = cleat.start("observe_run", {"runID": leaf_id, "tag": tag})
    assert status == 201, f"observer start rejected: {status} {obs}"
    obs_final = cleat.await_terminal(obs["id"], timeout=60.0)
    assert obs_final["status"] == "done", (
        f"the observer did not complete: {obs_final.get('status')!r} "
        f"{(obs_final.get('error') or '')[:300]!r}"
    )

    body = _body(obs_final)
    assert body["outcome"] == "observed", (
        f"the observer could not read the run: {body!r}"
    )
    assert body["status"] == "completed", (
        f"the observer saw status {body['status']!r} for a run that finished "
        f"before the observer started"
    )

    # The RESULT, not merely the status. Asserting the status alone would pass
    # against an observer that found the row and read nothing off it.
    assert body["result"] == {"tag": tag}, (
        f"the observer read result {body['result']!r}, want {{'tag': {tag!r}}}"
    )


def test_observing_an_unknown_run_is_not_reported_as_completed(cleat, observe_workflow):
    """The negative half, and the one that makes the positive half mean something.

    `GetChildResult` returns a zero `ChildOutcome` and a nil error for a row it
    cannot find, so "absent" and "running" arrive at the guest looking alike.
    The thing that must not happen is an unknown id reported as *completed*:
    that is the shape of cleat#1115, where a failed child was reported done,
    and it is the failure an observer would act on.
    """
    missing = str(uuid.uuid4())

    status, obs = cleat.start("observe_run", {"runID": missing, "tag": "ghost"})
    assert status == 201, f"observer start rejected: {status} {obs}"
    obs_final = cleat.await_terminal(obs["id"], timeout=60.0)
    assert obs_final["status"] == "done", (
        f"the observer did not complete: {obs_final.get('status')!r} "
        f"{(obs_final.get('error') or '')[:300]!r}"
    )

    body = _body(obs_final)
    assert body["status"] != "completed", (
        f"a run id that was never started was reported {body['status']!r} "
        f"with result {body.get('result')!r}"
    )
