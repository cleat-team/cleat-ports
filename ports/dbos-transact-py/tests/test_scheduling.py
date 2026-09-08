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


def _register_cron(cleat, cron_workflows, cleanup_schedules, key):
    """Create a `* * * * *` schedule and return its id."""
    status, started = cleat.start(cron_workflows, {
        "targetName": "cron_target", "cronExpr": "* * * * *", "markKey": key,
    })
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"the registering run did not complete: {final!r}"
    body = json.loads(final["result"]) if isinstance(final["result"], str) else final["result"]
    schedule_id = body["scheduleID"]
    cleanup_schedules.append(schedule_id)
    return schedule_id


def test_disabling_a_schedule_stops_it_firing(
    cleat, cron_workflows, fixture_calls, cleanup_schedules
):
    """The endpoint writes `enabled`; GetDueSchedules filters on it. Nothing
    checked that the two meet.

    This is the pair that has been wrong four times in this engine -- a writer
    with no reader, or a reader with no writer (cleat#889 was four of them at
    once). Here both halves exist: POST /api/schedules/{id}/disable calls
    SetScheduleEnabled, and GetDueSchedules selects `WHERE enabled = true` on
    all three dialects. Neither port exercised the combination.

    THE FIRST FIRE IS THE CONTROL and it is not optional. Without waiting for
    the schedule to fire at least once, "no fires after disable" is equally
    explained by a schedule that never worked -- and this suite has found
    several features where the recording half worked and the acting half did
    not, which is exactly that failure wearing a passing test.

    Slow by nature: two cron minutes plus scheduler lag.
    """
    key = f"cron-dis-{uuid.uuid4().hex[:8]}"
    schedule_id = _register_cron(cleat, cron_workflows, cleanup_schedules, key)

    _wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=CRON_FIRE_TIMEOUT,
        what="the schedule to fire at least once before it is disabled",
    )

    code, body = cleat.schedule_enabled(schedule_id, False)
    assert code == 200, f"disabling schedule {schedule_id} answered {code}: {body!r}"

    # The scheduler may already have a fire in flight, so settle first and take
    # the count after that, not before.
    time.sleep(5)
    baseline = fixture_calls(key)

    # Longer than a cron period: if `enabled` is not consulted, this window
    # contains at least one fire.
    time.sleep(75)
    after = fixture_calls(key)

    assert after == baseline, (
        f"the schedule fired {after - baseline} more times in 75s after being "
        f"disabled (baseline {baseline}, now {after}).\n"
        f"POST /disable calls SetScheduleEnabled and GetDueSchedules selects "
        f"WHERE enabled = true; if the count moved, one of those two is not "
        f"reaching the other."
    )


def test_re_enabling_a_schedule_resumes_it(
    cleat, cron_workflows, fixture_calls, cleanup_schedules
):
    """Disable must be reversible, or it is delete with a friendlier name.

    The control for the test above, in the other direction: if disabling
    worked by removing the row rather than by clearing a flag, this would fail
    while that one passed.
    """
    key = f"cron-re-{uuid.uuid4().hex[:8]}"
    schedule_id = _register_cron(cleat, cron_workflows, cleanup_schedules, key)

    _wait_until(
        lambda: fixture_calls(key) >= 1,
        timeout=CRON_FIRE_TIMEOUT,
        what="the schedule to fire once before being disabled",
    )

    code, _ = cleat.schedule_enabled(schedule_id, False)
    assert code == 200, f"disable answered {code}"
    time.sleep(5)
    disabled_at = fixture_calls(key)

    code, body = cleat.schedule_enabled(schedule_id, True)
    assert code == 200, f"re-enabling answered {code}: {body!r}"

    # And the schedule must still be listed -- a disable that deleted the row
    # would make re-enable a 500 or a silent no-op.
    code, listing = cleat.schedules()
    assert code == 200, f"the schedule list answered {code}"
    # Keyed by `name`, which IS the schedule id the API takes in its paths --
    # /api/schedules/{name}/enable. There is a separate uuid `id` column on the
    # table that never appears in the listing or a URL, so a caller only ever
    # sees one identifier. The first version of this assertion looked for
    # `schedule_id` and `id` and reported the schedule as deleted; it was
    # present the whole time.
    row = next((r for r in listing if r.get("name") == schedule_id), None)
    assert row is not None, (
        f"schedule {schedule_id} is absent from the listing after disable and "
        f"re-enable; disabling appears to have removed it rather than flagged it. "
        f"listing carries {[r.get('name') for r in listing]}"
    )
    assert row.get("enabled") is True, (
        f"schedule {schedule_id} is listed with enabled={row.get('enabled')!r} "
        f"after a successful re-enable, so the flag and the endpoint disagree"
    )

    _wait_until(
        lambda: fixture_calls(key) > disabled_at,
        timeout=CRON_FIRE_TIMEOUT,
        what="the re-enabled schedule to fire again",
    )
