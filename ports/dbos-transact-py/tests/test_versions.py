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
