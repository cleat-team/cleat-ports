"""Cron schedules and delayed invocation.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Maps to `tests/test_scheduler.py` upstream, which asserts that a scheduled
workflow actually runs on its schedule rather than that a schedule row was
written. That distinction is the whole content of these tests: creating a
schedule and starting the workflow it names are two different mechanisms, and
this repository has now found several features where the recording half worked
and the acting half did not.

Cleat's surface differs from DBOS's `@DBOS.scheduled` decorator — a workflow
registers a schedule at runtime with `h.ScheduleCron` — so the API does not
port, but the assertions do.
"""

import json
import time
import uuid

import pytest

# Cron granularity is one minute, so a `* * * * *` schedule fires within a
# minute of being created plus the scheduler's own lag (measured at ~8s after
# the minute boundary). 100s covers both with room, and this is the slowest
# test in the suite by a wide margin.
#
# It is here rather than replaced by a faster proxy because "the schedule row
# exists and has a next_run_at" is exactly the assertion that would have passed
# against a scheduler that never fired.
CRON_FIRE_TIMEOUT = 100.0


def _wait_until(predicate, timeout: float, what: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


@pytest.fixture
def cleanup_schedules(cleat):
    """Delete every schedule this module created, whatever the test did.

    The schedules are recurring: one left behind starts a workflow every
    minute for the rest of the run, which shows up as unexplained load in
    whatever test happens to be running next.
    """
    created = []
    yield created
    for name in created:
        cleat.delete_schedule(name)


def test_a_workflow_can_register_a_cron_schedule(cleat, cron_workflows, cleanup_schedules):
    """ScheduleCron and ListCrons agree, and the API sees the same schedule."""
    key = f"cron-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(cron_workflows, {
        "targetName": "cron_target", "cronExpr": "* * * * *", "markKey": key,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    body = json.loads(final["result"]) if isinstance(final["result"], str) else final["result"]
    schedule_id = body["scheduleID"]
    cleanup_schedules.append(schedule_id)
    assert schedule_id, "ScheduleCron returned an empty schedule id"

    # ListCrons is the workflow's own view; the API is an operator's. They are
    # separate read paths over the same rows, so asserting both catches one of
    # them drifting.
    listed = body["listed"]
    assert any(s["schedule_id"] == schedule_id for s in listed), (
        f"ListCrons did not report the schedule it had just created: {listed!r}"
    )

    api_status, schedules = cleat.schedules()
    assert api_status == 200, f"GET /api/schedules: {api_status}"
    mine = [s for s in schedules if s["name"] == schedule_id]
    assert len(mine) == 1, f"the API does not list the schedule: {schedules!r}"
    assert mine[0]["def_name"] == "cron_target"
    assert mine[0]["next_run_at"], "the schedule has no next_run_at, so nothing will fire it"


def test_a_cron_schedule_actually_starts_its_workflow(cleat, cron_workflows, fixture_calls, cleanup_schedules):
    """The half that a schedule row cannot show.

    Slow by nature: cron granularity is a minute. Asserted on the fixture
    rather than on a workflow listing because a cron-started run's history is
    purged when it completes, and its input is the only thing that ties it back
    to this test.
    """
    key = f"cron-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(cron_workflows, {
        "targetName": "cron_target", "cronExpr": "* * * * *", "markKey": key,
    })
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    body = json.loads(final["result"]) if isinstance(final["result"], str) else final["result"]
    cleanup_schedules.append(body["scheduleID"])

    _wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=CRON_FIRE_TIMEOUT,
        what="the cron schedule to start its workflow and that workflow to reach the fixture",
    )


def test_deleting_a_schedule_removes_it(cleat, cron_workflows, cleanup_schedules):
    """A schedule that cannot be removed is worse than one that cannot be made."""
    key = f"cron-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(cron_workflows, {
        "targetName": "cron_target", "cronExpr": "* * * * *", "markKey": key,
    })
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=60.0)
    body = json.loads(final["result"]) if isinstance(final["result"], str) else final["result"]
    schedule_id = body["scheduleID"]

    del_status, _ = cleat.delete_schedule(schedule_id)
    assert del_status == 200, f"DELETE /api/schedules/{schedule_id}: {del_status}"

    api_status, schedules = cleat.schedules()
    assert api_status == 200
    assert not any(s["name"] == schedule_id for s in schedules), (
        "the schedule is still listed after being deleted, so it will keep firing"
    )


def test_a_delayed_invocation_reaches_the_service(cleat, schedule_invoke_workflow, fixture_calls):
    """`ScheduleInvoke` fires after its delay, across a suspension.

    The workflow records the schedule in one segment and sleeps past the delay,
    so the invocation is due while the workflow is suspended in another. That
    is the arrangement that broke `DurableSend` and `PluginCallStreaming`
    (cleat#835): work recorded on one side of the replay frontier and expected
    to happen on the other.
    """
    key = f"si-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(schedule_invoke_workflow, {
        "invokeKey": key, "delayMs": 1000, "sleepMs": 6000,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    _wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=30.0,
        what="the delayed invocation to reach the fixture service",
    )
