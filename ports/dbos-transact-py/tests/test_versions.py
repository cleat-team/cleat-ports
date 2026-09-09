"""Version and MinVersion, the last two host calls without port coverage.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Both numbers come from the workflow instance row, through WithWorkflowState at
cmd/cleat-worker/setup.go:1620. That indirection is why "it returned a number"
is not an assertion worth making: if the option were ever unwired, MinVersion
would return the literal 1 from engine/lifecycle.go:97 and Version would follow
the same path -- silently, with no error anywhere. cleat#879 was exactly that
shape for a different option, and cleat#878 lists nine more that are unwired
today.

So the assertions are relational: the numbers must survive a suspension
unchanged, MinVersion must not exceed Version, and Version must match what the
deploy actually produced.
"""

import json
import uuid


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_the_reported_versions_survive_a_suspension(cleat, min_version_workflow):
    """Version and MinVersion are the same before and after a suspension.

    A suspension replays the prefix, so anything read from the instance row is
    read again. Numbers that differ across the boundary would mean the workflow
    saw its own identity change underneath it -- the same class of defect as
    cleat#882, where a poll re-answered differently on replay.
    """
    key = f"ver-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(min_version_workflow, {"key": key, "sleepMs": 3000})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the workflow did not complete: {final.get('error') or final!r}"
    )

    body = _body(final)

    assert final.get("generation", 1) > 1, (
        f"the workflow completed in one segment (generation {final.get('generation')}), "
        f"so it never suspended and this test did not compare across a replay."
    )

    assert body["beforeVersion"] == body["afterVersion"], (
        f"Version changed across a suspension: {body!r}"
    )
    assert body["beforeMin"] == body["afterMin"], (
        f"MinVersion changed across a suspension: {body!r}"
    )
    assert body["beforeMin"] <= body["beforeVersion"], (
        f"MinVersion exceeds Version, so the workflow requires a version newer than "
        f"the one it is running as: {body!r}"
    )


def test_the_version_reported_is_the_deployed_one(cleat, min_version_workflow):
    """The number the workflow reports is the one the API reports for the run.

    This is the half that makes the test falsifiable. Without it, a Version()
    hardwired to 1 would satisfy every assertion above -- they are all internal
    consistency checks, and a constant is perfectly self-consistent.
    """
    key = f"ver-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(min_version_workflow, {"key": key, "sleepMs": 3000})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the workflow did not complete: {final.get('error') or final!r}"
    )

    reported = _body(final)["beforeVersion"]
    deployed = final.get("def_version")
    assert deployed is not None, (
        f"the run record carries no def_version, so there is nothing to compare "
        f"the workflow's own Version() against: {final!r}"
    )
    assert reported == deployed, (
        f"the workflow reported Version()={reported} while the run it belongs to is "
        f"def_version={deployed}. A Version() that ignores the instance row would "
        f"look exactly like this."
    )


# Long enough that the deploy of v2 lands while the first run is parked
# mid-body. A run that finished before the deploy would satisfy every assertion
# below without ever having spanned a version change -- which is the entire
# subject.
VERSION_SLEEP_MS = 20_000


def test_a_running_workflow_finishes_on_the_version_it_started_with(
    cleat, version_marked_workflow
):
    """Ports upstream test_enqueue_version.

    Upstream pins a workflow to an application version at enqueue and asserts
    the run executes that version's code. Cleat has no per-start version
    argument -- code travels in the database (`workflow_defs.wasm_bytes`), not
    with the worker process -- so the portable half is the guarantee underneath
    it: a run executes ONE version of its definition, start to finish, even if
    a newer one is deployed while it is suspended.

    WHY THIS IS THE PROPERTY AND NOT A DETAIL. Replay re-executes the body from
    step 0 against recorded history. A suspended run that resumed on newly
    deployed bytes would replay code that never produced the history it is
    replaying against -- the branch taken before the suspension might not exist
    any more. Every durability guarantee assumes the body is stable for the
    life of a run, and deploying is the ordinary operation that would break it.

    NEITHER EXISTING VERSION TEST CAN SEE THIS. Both assert on the numbers a
    workflow reports about itself, which come from the instance row. A run
    resuming on the wrong bytes would report the same numbers and return a
    different answer.

    BOTH DIRECTIONS ARE ASSERTED, because each alone is satisfiable by a broken
    engine:

      pinned forever  an engine that never picks up a deploy at all passes the
                      "still says one" assertion and fails the "a new start
                      says two" one.
      switched live   an engine that moves every run to the newest bytes passes
                      the second and fails the first.

    The ordering is owned by this test rather than by the fixture, because a
    fixture that deployed both versions up front would leave nothing in flight
    across the change -- and the test would pass while asserting about a run
    that began after both deploys. That was the first draft of this test, and
    its name described a property its body never exercised.

    FALSIFIED by substitution rather than mutation, since the engine gets this
    right and cannot easily be made to get it wrong: putting the "two" binary
    in the v1 slot makes the in-flight run genuinely return "two", which is the
    observable a live-version-switch would produce. It fails in 23s with
    "a run that started on v1 reported {'before': 'two', 'after': 'two'}".
    """
    from conftest import deploy_version_two

    key = f"vermark-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(
        version_marked_workflow, {"key": key, "sleepMs": VERSION_SLEEP_MS}
    )
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # Deploy v2 while that run is parked in its sleep. This is the whole point;
    # everything below is reading the consequence.
    deploy_version_two()

    final = cleat.await_terminal(run_id, timeout=120.0)
    assert final["status"] == "done", (
        f"the run did not complete after a new version was deployed under it: "
        f"{final!r}"
    )

    body = _body(final)
    assert body["before"] == "one" and body["after"] == "one", (
        f"a run that started on v1 reported {body!r} after v2 was deployed "
        "mid-flight. It resumed on bytes that did not produce the history it "
        "was replaying against, which is the assumption every durability "
        "guarantee here rests on."
    )
    assert body["key"] == key, f"the run returned another run's key: {body!r}"

    # The other direction, and it is what stops the assertion above holding for
    # an engine that simply ignores deploys.
    status, fresh = cleat.start(version_marked_workflow, {"key": key, "sleepMs": 0})
    assert status == 201, f"start rejected: {status} {fresh}"
    newest = cleat.await_terminal(fresh["id"], timeout=60.0)
    assert newest["status"] == "done", f"run did not complete: {newest!r}"
    assert _body(newest)["before"] == "two", (
        f"a start made AFTER v2 was deployed still ran v1: {_body(newest)!r}. "
        "The deploy was not picked up at all, so the assertion above held "
        "because nothing ever changed rather than because the run was pinned."
    )
