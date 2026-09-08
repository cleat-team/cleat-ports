"""What a schedule does about firings it missed while nothing was running.

Ported from upstream `test_scheduler.py::test_automatic_backfill_on_restart`.
Upstream calls it backfill; cleat calls it the misfire policy, and the
behaviour asserted is the same one.

WHY THIS FILE EXISTS AT ALL. cleat has had this feature the whole time, it is
reachable over HTTP, and it is ON BY DEFAULT -- `engine/cron.go` says "Empty is
valid and means MisfireCatchUp". Nothing in either port had ever exercised it:

    grep -rniE 'misfire|catch_up|overlap_policy' across both ports  ->  0

So every schedule this suite has ever created ran under a policy nobody had
checked, along with the catch-up limit beside it.

THE CONTROL IS THE POINT. Asserting that catch_up delivers a missed firing
shows only that something fired after the worker came back -- which a schedule
with no backlog handling would also do, at its next instant. The `skip`
schedule is what makes this a test of the POLICY: same outage, same cron, same
window, and it must deliver NOTHING from the backlog.

WHY COUNTING IS LEGITIMATE HERE, since counting usually cannot tell "delivered
the missed instant" from "fired once on restart". The two policies differ in
the CARDINALITY of what they deliver, by definition -- `catch_up` delivers the
backlog "one instant per poll tick, up to the schedule's catch-up limit", and
`skip` "resumes at the next future instant and delivers none of the backlog".
An outage spanning two instants therefore separates them without a clock:
catch_up owes two, skip owes zero. The workflow cannot stamp its scheduled
instant -- cleat passes the schedule's stored input verbatim and does not
inject the firing time -- so cardinality is the observable that exists.

BLOCKED ON cleat#995 AS OF 2026-09-08, AND THE GUARD IS BELOW RATHER THAN A
BARE SKIP. The misfire policy can only be set through POST /api/schedules --
the ScheduleCron host call takes (workflowName, cronExpr, timezone, inputJSON)
and no policy -- and that endpoint never sets next_run_at, so a schedule it
creates is dated 0001-01-01. The scheduler then reads it as overdue by two
millennia and drains up to catch_up_limit (60) firings on the FIRST TICK, with
no outage involved.

That is not a setup inconvenience. It would satisfy the `catch_up >= 2`
assertion below on its own, so the test would pass while measuring nothing --
which is exactly what it did before the guard was added, with a 135-second
sleep that was decorative. The guard reads next_run_at back and skips if it is
in the past, so the day #995 is fixed this test starts asserting in full with
nobody editing it.

COST: this test takes about three minutes, and cannot be made faster. cleat's
cron dialect is five fields (`engine/cron.go:75` rejects anything else), so one
minute is the shortest interval expressible, and the outage has to span two of
them for the cardinality argument above to hold.
"""

import time
from datetime import datetime, timezone

import pytest

from conftest import wait_until

CRON_EVERY_MINUTE = "* * * * *"

#: Two full minute boundaries, plus a margin for the boundary we start inside.
OUTAGE_SECONDS = 135

#: The scheduler polls every 15s (cmd/cleat-worker/main.go: scheduleInterval)
#: and catch_up delivers "one instant per poll tick", so two missed instants
#: need two ticks. Generous enough for three, because a tick landing just after
#: the restart costs most of one interval before anything happens at all.
DRAIN_SECONDS = 75

#: The control is snapshotted after the FIRST delivery rather than the second,
#: and that timing is the whole of its validity. `skip` resumes at its next
#: FUTURE instant, and a control taken after that instant sees a firing that is
#: entirely legitimate and reads it as a backlog delivery.
#:
#: A fixed window cannot guarantee this. The falsification run that found it
#: put both schedules on `skip` expecting the catch_up assertion to fail; what
#: failed instead was the control, because the restart happened to land close
#: to a minute boundary and skip's next instant fired inside the window. That
#: is a coin-flip in the real test too, not just in the falsification.
#:
#: So the restart is ALIGNED to just after a minute boundary, which makes the
#: headroom ~57s rather than "somewhere between 0 and 60".
FIRST_TICK_SECONDS = 40

#: Restart this many seconds after a minute boundary. Small enough to leave
#: nearly a full interval of headroom, large enough that the boundary's own
#: firing is not racing the restart itself.
RESTART_OFFSET_SECONDS = 4

@pytest.fixture()
def misfire_schedules(cleat, cron_workflows, worker, fixture_calls):
    """Two schedules over one outage: one catch_up, one skip.

    CREATED WHILE THE WORKER IS UP, then the worker is stopped. The obvious
    order is the other way round -- stop first, so the schedules cannot fire
    before the outage -- and it does not work: in this harness the worker
    process IS the API server (`scripts/worker.sh url` is the base URL every
    request goes to), so a stopped worker refuses the POST that would create
    them. conftest's `stop()` docstring says "the API keeps accepting starts
    with no worker running", which is true of a deployment where the two are
    separate processes and not of this one; nothing had exercised it, because
    test_recovery.py is the only other user of this fixture and it crashes and
    restarts with no request in between.

    So the window is: create, verify nothing has fired, stop. `next_run_at` for
    a `* * * * *` schedule is the next minute boundary, and the stop follows
    within a second, but the assertion below is what makes that a checked fact
    rather than an assumption -- if a firing does land first, the test says so
    instead of quietly measuring a shorter outage.
    """
    stamp = str(int(time.time()))
    names = {"catch_up": f"misfire-catchup-{stamp}", "skip": f"misfire-skip-{stamp}"}
    keys = {p: f"misfire-{p}-{stamp}" for p in names}

    for policy, name in names.items():
        status, body = cleat.create_schedule(
            name=name, cron=CRON_EVERY_MINUTE, def_name="cron_target",
            entry_point="HandleCronTarget",
            inp={"key": keys[policy], "tag": policy},
            misfire=policy,
        )
        assert status in (200, 201), f"creating the {policy} schedule: {status} {body}"

    # THE #995 GUARD. A schedule whose next_run_at is already in the past is
    # not the schedule this test means to create, and the catch_up assertion
    # would pass off the backlog that produces rather than off the outage.
    # Read it back rather than trusting the 201.
    listed_status, listed = cleat.schedules()
    assert listed_status == 200, f"GET /api/schedules: {listed_status}"
    by_name = {s["name"]: s for s in listed}
    for policy, name in names.items():
        row = by_name.get(name)
        assert row is not None, f"the {policy} schedule is absent from the listing"
        nra = row.get("next_run_at") or ""
        if nra < datetime.now(timezone.utc).isoformat():
            for n in names.values():
                cleat.delete_schedule(n)
            pytest.skip(
                f"cleat#995: POST /api/schedules stored next_run_at={nra!r} for "
                f"{name!r}, which is in the past. The scheduler treats such a "
                f"schedule as overdue and drains up to catch_up_limit firings on "
                f"its first tick, which would satisfy this test's catch_up "
                f"assertion without any outage. Skipping rather than asserting "
                f"something that measures nothing. This skip retires itself when "
                f"#995 is fixed."
            )

    for policy, key in keys.items():
        fired = fixture_calls(key)
        assert fired == 0, (
            f"the {policy} schedule fired {fired} time(s) between being created "
            f"and the worker being stopped, so the outage does not span the "
            f"instants this test assumes"
        )

    worker.stop()

    yield names, keys

    # The API is only reachable with the worker up, and the fixture's own
    # teardown restarts it -- but that runs AFTER this one, so restart here
    # rather than leaving two schedules firing every minute for the rest of
    # the session.
    worker.restart()
    for name in names.values():
        cleat.delete_schedule(name)


def test_a_schedule_set_to_catch_up_delivers_what_it_missed(
    cleat, misfire_schedules, worker, fixture_calls
):
    """cleat#N/A -- upstream test_automatic_backfill_on_restart.

    The pair is asserted in one test on purpose: they share one outage, and
    splitting them would double a three-minute test while making the control
    depend on a separate outage being comparable.
    """
    names, keys = misfire_schedules

    # Nothing is running, so nothing can fire. Both schedules accrue a backlog.
    #
    # Deliberately NOT asserting zero during the outage: `worker.sh stop` stops
    # the fixture service as well as the worker (it calls stop_worker AND
    # stop_fixture), so the recorder is unreachable here -- an attempt to check
    # it fails with a connection refusal that reads like a product defect. The
    # baseline is taken in the fixture instead, before the stop, and the outage
    # is guaranteed by construction: nothing is running that could fire.
    time.sleep(OUTAGE_SECONDS)

    # Align the restart to just after a minute boundary, so `skip`'s next
    # future instant is ~57s away rather than an unknown amount. Without this
    # the control's validity is a coin flip -- see FIRST_TICK_SECONDS.
    time.sleep((60 - time.time() % 60) + RESTART_OFFSET_SECONDS)

    worker.restart()

    # ONE tick is enough to separate the policies, and taking the control here
    # rather than at the end is what keeps it a control -- see FIRST_TICK_SECONDS.
    wait_until(lambda: fixture_calls(keys["catch_up"]) >= 1, FIRST_TICK_SECONDS,
               "the catch_up schedule to deliver anything from its backlog")

    skipped = fixture_calls(keys["skip"])
    assert skipped == 0, (
        f"the skip schedule delivered {skipped} run(s) while the catch_up one "
        f"was still on its first delivery. misfire_policy=skip must resume at "
        f"the next FUTURE instant and deliver none of what it missed -- "
        f"otherwise the catch_up assertion is about the scheduler waking up, "
        f"not about the policy."
    )

    # And the backlog is a BACKLOG: more than the single firing a schedule with
    # no catch-up handling would produce on its next instant. This is the half
    # that needs two ticks, and it is asserted after the control precisely
    # because waiting for it would invalidate the control.
    wait_until(lambda: fixture_calls(keys["catch_up"]) >= 2, DRAIN_SECONDS,
               f"the catch_up schedule to deliver a second missed instant "
               f"(saw {fixture_calls(keys['catch_up'])} of >=2)")
