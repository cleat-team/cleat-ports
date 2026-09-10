"""A cron expression's wall-clock fields are read in a named zone.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Maps to `test_backfill_with_timezone` and `test_backfill_naive_datetime` in
upstream's `tests/test_scheduler.py`. Upstream reaches the property through a
backfill CALL, which cleat has no counterpart for; the property underneath it
is the one ported -- that a schedule carrying an IANA zone means an instant in
THAT zone, and that a schedule carrying none means a documented default rather
than something ambiguous.

WHY THESE ASSERT ON next_run_at RATHER THAN WAITING FOR A FIRE. Every other
test in this suite that cares about a schedule waits for the workflow to
actually run, deliberately, because "the row exists" is exactly the assertion
that passes against a scheduler that never fires. That reasoning does not
transfer here: a zone changes WHEN a schedule fires, and the smallest
observable difference is one hour. A test that waited would take an hour to
distinguish its two hypotheses, and `* * * * *` -- the expression that fires
soon enough to wait for -- is the one expression whose next instant is
identical in every zone on earth. So the property is unobservable by waiting
and exact by reading.

What that costs is stated rather than hidden: these pin the instant cleat
COMPUTES, not the instant at which a workflow starts. `test_scheduling.py`
already pins that the computed instant is acted on at all, and cleat#998 is
the case where it was not -- a handler that left NextRunAt unset stored year 1
and every schedule fired on the next tick. These would not have caught that;
`test_a_newly_created_schedule_is_not_already_due` does, and it is the reason
these can be narrow.
"""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

# A daily noon cron. Chosen because it is the simplest expression whose
# instant DIFFERS between zones -- which `* * * * *` and `0 * * * *` do not,
# since every zone's offset from UTC is a whole number of minutes and most are
# a whole number of hours.
NOON_DAILY = "0 12 * * *"

# New York rather than a fixed-offset zone on purpose. A test that used
# Etc/GMT+5 would pass against an engine that parsed the offset out of the
# name and never opened tzdata, which is the implementation this is most
# worth distinguishing from. New York's offset is a property of the date.
ZONE = "America/New_York"


def next_noon_utc(zone_name: str, now_utc: datetime) -> datetime:
    """The next 12:00 wall-clock in `zone_name`, expressed in UTC.

    Deliberately not a reimplementation of cron. It answers one expression,
    the way a reader can check by hand, so that a defect in this file cannot
    look like agreement with the engine.
    """
    zone = ZoneInfo(zone_name)
    local = now_utc.astimezone(zone)
    candidate = local.replace(hour=12, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate = (local + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
    return candidate.astimezone(timezone.utc)


def parse_next_run(raw: str) -> datetime:
    """Parse the API's next_run_at into an aware UTC datetime."""
    text = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def schedule_row(cleat, name):
    status, listing = cleat.schedules()
    assert status == 200, f"listing failed: {status} {listing}"
    rows = listing if isinstance(listing, list) else listing.get("schedules", [])
    mine = [r for r in rows if r.get("name") == name]
    assert len(mine) == 1, f"expected exactly one schedule named {name}, got {mine!r}"
    return mine[0]


@pytest.fixture
def cleanup_schedules(cleat):
    created = []
    yield created
    for name in created:
        cleat.delete_schedule(name)


def test_a_cron_in_a_named_zone_is_scheduled_on_that_zones_clock(
    cleat, cron_workflows, cleanup_schedules
):
    """`0 12 * * *` in America/New_York is noon in New York, not noon in UTC.

    The two hypotheses are four or five hours apart depending on the date, so
    nothing here depends on a tolerance: the assertion is equality to the
    minute against a value computed from tzdata on this machine.

    A UTC schedule with the IDENTICAL expression is created in the same test
    as the control. Without it, an engine that ignored the zone entirely and
    an engine that honoured it would both have to be distinguished by
    arithmetic against wall-clock, and "is this 16:00 because New York or
    because something else" is exactly the question a second row answers for
    free.
    """
    stamp = uuid.uuid4().hex[:8]
    zoned, plain = f"tz-{stamp}", f"utc-{stamp}"
    before = datetime.now(timezone.utc)

    for name, tz in ((zoned, ZONE), (plain, "UTC")):
        status, body = cleat.create_schedule(name, NOON_DAILY, "cron_target", timezone=tz)
        assert status in (200, 201), f"create {name} rejected: {status} {body}"
        cleanup_schedules.append(name)

    after = datetime.now(timezone.utc)
    zoned_row, plain_row = schedule_row(cleat, zoned), schedule_row(cleat, plain)

    assert zoned_row.get("timezone") == ZONE, (
        f"timezone read back as {zoned_row.get('timezone')!r}, want {ZONE!r}. "
        "The zone was accepted and is not in the row, so the schedule will be "
        "evaluated in UTC and the caller was told otherwise."
    )

    got = parse_next_run(zoned_row["next_run_at"])
    # `before` and `after` bracket the instant the server called time.Now().
    # Both ends must give the same answer, or the test straddles a noon
    # boundary and cannot say what the right answer was -- which is a reason
    # to skip, not to pick one.
    lo, hi = next_noon_utc(ZONE, before), next_noon_utc(ZONE, after)
    if lo != hi:
        pytest.skip("the request straddled noon in " + ZONE)

    assert got == lo, (
        f"next_run_at for `{NOON_DAILY}` in {ZONE} is {got.isoformat()}, "
        f"want {lo.isoformat()}. The engine computed the next instant of a "
        "wall-clock expression in the wrong zone, so the schedule fires at the "
        "right time in a place nobody asked about."
    )

    plain_got = parse_next_run(plain_row["next_run_at"])
    utc_lo, utc_hi = next_noon_utc("UTC", before), next_noon_utc("UTC", after)
    if utc_lo != utc_hi:
        pytest.skip("the request straddled noon UTC")
    assert plain_got == utc_lo, (
        f"the UTC control resolved to {plain_got.isoformat()}, want "
        f"{utc_lo.isoformat()} -- the disagreement is not about the zone"
    )

    # THE THIRD ASSERTION THIS USED TO MAKE IS GONE, and deliberately.
    #
    # It compared the two schedules to each other:
    #
    #     assert got - plain_got == -offset
    #
    # "the same expression in two zones must differ by exactly the offset
    # between them" -- which is true only when both next-noons land on the same
    # DATE. They do not, whenever the current time sits between the two noons.
    # At 12:08 UTC on 2026-09-10 the zoned schedule was
    #
    #     2026-09-10 16:00 UTC   (noon EDT, still ahead)
    #     2026-09-11 12:00 UTC   (noon UTC, already past, so tomorrow)
    #
    # -- twenty hours apart, both correct, and the assertion failed. It turned
    # `develop` red for the four hours between noon UTC and noon in New York,
    # and it would do so every day.
    #
    # The two straddle guards above do not cover it: they ask whether the
    # REQUEST straddled a noon, not whether the two answers landed on different
    # days, which is a different question and the one that bites.
    #
    # Removed rather than guarded, because it asserted nothing the two
    # assertions above do not already assert exactly. `got` is pinned to `lo`
    # and `plain_got` to `utc_lo`, each computed independently by
    # next_noon_utc; the relationship between them is then fully determined. A
    # third assertion derived from the same helper cannot fail unless one of
    # those two already has.


def test_a_schedule_that_names_no_zone_gets_the_documented_default(
    cleat, cron_workflows, cleanup_schedules
):
    """Omitting the zone stores 'UTC', not '' -- a default, not an absence.

    This is upstream's naive-versus-aware distinction in the shape cleat has
    it. There is no naive datetime to pass; the equivalent question is whether
    a schedule created without a zone is ambiguous about which clock it means.

    It is not, and the engine says why in two places rather than one, which is
    what makes this worth pinning: `engine.DefaultScheduleTimezone` is UTC
    "because a schedule that means 02:00 should keep meaning the same instant
    regardless of which worker in the fleet happens to pick it up", and
    `scheduleTimezoneOrDefault` writes that name into the column on all three
    dialects "so the column is never ambiguous about whether a zone was
    chosen".

    A row that came back '' would satisfy neither. It would also read as
    "no zone" to any client that had to decide, and the two clients that have
    to decide -- the scheduler and whoever renders a dashboard -- would be
    free to decide differently.
    """
    name = f"tz-default-{uuid.uuid4().hex[:8]}"
    before = datetime.now(timezone.utc)
    status, body = cleat.create_schedule(name, NOON_DAILY, "cron_target")
    assert status in (200, 201), f"create rejected: {status} {body}"
    cleanup_schedules.append(name)
    after = datetime.now(timezone.utc)

    row = schedule_row(cleat, name)
    assert row.get("timezone") == "UTC", (
        f"a schedule created with no timezone reads back {row.get('timezone')!r}, "
        "want 'UTC'. An empty zone pushes the decision to whichever reader "
        "remembers to apply the default, and the scheduler and any dashboard "
        "are then free to disagree about what 12:00 meant."
    )

    got = parse_next_run(row["next_run_at"])
    lo, hi = next_noon_utc("UTC", before), next_noon_utc("UTC", after)
    if lo != hi:
        pytest.skip("the request straddled noon UTC")
    assert got == lo, (
        f"next_run_at is {got.isoformat()}, want {lo.isoformat()}. The row says "
        "UTC and the instant was computed in some other zone, which is worse "
        "than an empty column: it is a column that reads correct and is not."
    )


def test_an_unloadable_timezone_is_refused(cleat, cron_workflows, cleanup_schedules):
    """A zone tzdata cannot resolve is a 400, not a silent fall back to UTC.

    This is what makes the two tests above mean anything. Both send a zone and
    read a value back; neither can tell "honoured" from "accepted, discarded,
    and UTC happens to be what you get". A refusal can.

    It is also the case with a real consequence behind it. The handler's own
    comment gives the reason it validates: the schedule is daily, so an
    unloadable zone "would silently fall back to UTC" and the schedule fires
    at the wrong hour for the rest of its life, with nothing at creation time
    to say so.
    """
    name = f"tz-bad-{uuid.uuid4().hex[:8]}"
    status, body = cleat.create_schedule(
        name, NOON_DAILY, "cron_target", timezone="Mars/Olympus_Mons",
    )
    if status in (200, 201):
        cleanup_schedules.append(name)
    assert status == 400, (
        f"an unloadable timezone answered {status} {body!r}, want 400. "
        "Accepting it means the schedule is stored with a zone that cannot be "
        "resolved, and every firing after that is computed in UTC while the "
        "row claims otherwise."
    )
