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
from datetime import datetime, timezone

import pytest

from conftest import wait_until

# Cron granularity is one minute, so a `* * * * *` schedule fires within a
# minute of being created plus the scheduler's own lag (measured at ~8s after
# the minute boundary). 100s covers both with room, and this is the slowest
# test in the suite by a wide margin.
#
# It is here rather than replaced by a faster proxy because "the schedule row
# exists and has a next_run_at" is exactly the assertion that would have passed
# against a scheduler that never fired.
CRON_FIRE_TIMEOUT = 100.0


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

    wait_until(
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

    wait_until(
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

    wait_until(
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

    wait_until(
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

    wait_until(
        lambda: fixture_calls(key) > disabled_at,
        timeout=CRON_FIRE_TIMEOUT,
        what="the re-enabled schedule to fire again",
    )


# ---------------------------------------------------------------------------
# Schedule policies: misfire, catch-up limit, overlap
#
# WHAT IS AND IS NOT ALREADY COVERED, re-derived against develop rather than
# quoted from when these were written -- test_misfire.py (#61) landed in
# between and made the original claim false:
#
#   misfire_policy   test_misfire.py sets it and asserts the BEHAVIOUR:
#                    catch_up delivers the backlog after an outage, skip does
#                    not. Covered, and these tests do not repeat it.
#   catch_up_limit   appears twice on develop, both times in prose -- a
#                    sentence and an assertion message. Never sent.
#   overlap_policy   appears ONCE on develop, inside a grep command quoted in
#                    test_misfire.py's own docstring. Never sent.
#
# Check it by looking at where the name sits, not by counting matches; a
# text search cannot tell a request field from a sentence about one:
#
#     git grep -n overlap_policy origin/develop -- 'ports/'
#
# So two of the three policy fields still reach the server from no test at
# all, and the surface itself -- does a value survive the round trip, is a
# bad one refused, what comes back when you send nothing -- is untested for
# all three. That is what these add, one layer below #61: it asks what the
# policy DOES, these ask whether it can be SET.
#
# They pin the OPERATOR path deliberately. The scheduling tests above register
# schedules from guest code via h.ScheduleCron, which carries none of the
# three -- so POST /api/schedules is not merely another way in, it is the only
# way to set a policy at all.
#
# What these do NOT test is what the policies do; #61 does that.
#
# The rejection test is the one that distinguishes the two failure modes a
# write-only surface has: a field that is stored but ignored, and a field that
# is neither stored nor rejected. A round-trip alone cannot tell "accepted and
# persisted" from "accepted, defaulted, and happens to match what I sent".


def test_the_schedule_policies_round_trip_through_the_api(cleat, cron_workflows, cleanup_schedules):
    """All three policy fields survive create and come back on read.

    Non-default values on purpose: sending catch_up/allow would pass against a
    server that dropped the fields entirely and let the column defaults answer.
    """
    name = f"policy-{uuid.uuid4().hex[:8]}"
    status, created = cleat.create_schedule(
        name, "*/5 * * * *", "cron_target",
        misfire="skip", catch_up_limit=7, overlap_policy="skip",
    )
    assert status in (200, 201), f"create rejected: {status} {created}"
    cleanup_schedules.append(name)

    status, listing = cleat.schedules()
    assert status == 200, f"listing failed: {status} {listing}"
    rows = listing if isinstance(listing, list) else listing.get("schedules", [])
    mine = [r for r in rows if r.get("name") == name]
    assert len(mine) == 1, f"expected exactly one schedule named {name}, got {mine!r}"
    got = mine[0]

    assert got.get("misfire_policy") == "skip", (
        f"misfire_policy read back as {got.get('misfire_policy')!r}, want 'skip'. "
        "The field was accepted by the API and is not in the row -- a policy that "
        "cannot be set is worse than one that does not exist, because the caller "
        "is told it succeeded."
    )
    assert got.get("catch_up_limit") == 7, (
        f"catch_up_limit read back as {got.get('catch_up_limit')!r}, want 7"
    )
    assert got.get("overlap_policy") == "skip", (
        f"overlap_policy read back as {got.get('overlap_policy')!r}, want 'skip'"
    )


def test_an_unknown_misfire_policy_is_refused(cleat, cron_workflows, cleanup_schedules):
    """An unrecognised policy is a 400, not a silent fall back to the default.

    This is what makes the round-trip above mean something. A server that
    ignored the field entirely would still store 'catch_up', still answer 200,
    and still look correct to any test that only sends valid values.

    It matters beyond tidiness: the scheduler reads the stored string and the
    migration constrains the column to ('catch_up','skip'), so a value that
    reached the database would be one the scheduler cannot interpret at 03:00 --
    which is the reason engine/cron.go gives for validating at all.
    """
    name = f"policy-bad-{uuid.uuid4().hex[:8]}"
    status, body = cleat.create_schedule(
        name, "*/5 * * * *", "cron_target", misfire="sometimes",
    )
    if status in (200, 201):
        cleanup_schedules.append(name)
    assert status == 400, (
        f"an unknown misfire policy answered {status} {body!r}, want 400. "
        "Accepting it means either the value is stored and the scheduler will "
        "meet it later, or it is dropped and the caller was told a policy was "
        "set that was not."
    )


def test_a_schedule_created_without_policies_carries_the_documented_defaults(
    cleat, cron_workflows, cleanup_schedules
):
    """Omitting the fields yields catch_up and allow, not empty strings.

    The defaults are a documented promise -- engine/cron.go says catch_up is the
    default "because the engine promises at-least-once", and allow is the
    default "only because it is what the scheduler has always done". A row that
    came back with '' would satisfy neither, and would push the decision to
    whichever reader remembered to call MisfirePolicyOrDefault.
    """
    name = f"policy-default-{uuid.uuid4().hex[:8]}"
    status, created = cleat.create_schedule(name, "*/5 * * * *", "cron_target")
    assert status in (200, 201), f"create rejected: {status} {created}"
    cleanup_schedules.append(name)

    _, listing = cleat.schedules()
    rows = listing if isinstance(listing, list) else listing.get("schedules", [])
    mine = [r for r in rows if r.get("name") == name]
    assert len(mine) == 1, f"expected one schedule named {name}, got {mine!r}"
    got = mine[0]

    assert got.get("misfire_policy") == "catch_up", (
        f"misfire_policy defaulted to {got.get('misfire_policy')!r}, want 'catch_up'"
    )
    assert got.get("overlap_policy") == "allow", (
        f"overlap_policy defaulted to {got.get('overlap_policy')!r}, want 'allow'"
    )


def test_a_newly_created_schedule_is_not_already_due(cleat, cron_workflows, cleanup_schedules):
    """next_run_at comes back in the future, not at the epoch.

    The column is `NOT NULL DEFAULT now()`, but a column default applies only
    when the INSERT omits the column, and CreateSchedule names every column. So
    a handler that left NextRunAt unset bound the zero time.Time and the row
    stored 0001-01-01 -- and the scheduler selects due work with
    `next_run_at <= now()`, which year 1 satisfies permanently. Every schedule
    created through this endpoint fired on the next tick regardless of its cron
    expression (cleat#998).

    Asserted here rather than only upstream because the unit test that covers
    it uses a mock store: it can prove the handler PASSES a sane value, not
    that a real database stores one and a real API hands it back. This is the
    only place all three are true at once.

    A daily cron is what makes it an assertion. With `*/5 * * * *` the next
    instant is at most five minutes out, which is close enough to now that a
    clock skew or a slow create could make a correct value look wrong; at 07:00
    daily the gap between "the epoch" and "the right answer" is never smaller
    than hours.
    """
    name = f"due-{uuid.uuid4().hex[:8]}"
    status, created = cleat.create_schedule(name, "0 7 * * *", "cron_target")
    assert status in (200, 201), f"create rejected: {status} {created}"
    cleanup_schedules.append(name)

    status, listing = cleat.schedules()
    assert status == 200, f"listing failed: {status} {listing}"
    rows = listing if isinstance(listing, list) else listing.get("schedules", [])
    mine = [r for r in rows if r.get("name") == name]
    assert len(mine) == 1, f"expected one schedule named {name}, got {mine!r}"

    next_run = mine[0].get("next_run_at")
    assert next_run, f"next_run_at missing from the listing: {mine[0]!r}"
    # Parse without assuming a fixed offset spelling: Go renders RFC3339 with
    # "Z" for UTC, which fromisoformat rejected before 3.11.
    parsed = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    assert parsed.year > 1970, (
        f"next_run_at is {next_run}, at or before the epoch. The schedule is "
        "permanently due and will fire on the next scheduler tick instead of "
        "at 07:00."
    )
    assert parsed > now, (
        f"next_run_at is {next_run}, which is already past (now {now.isoformat()}). "
        "A schedule created just now is due immediately."
    )
