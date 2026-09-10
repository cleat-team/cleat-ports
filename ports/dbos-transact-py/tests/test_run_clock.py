"""The three timestamps a run reports, and their order.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream's `test_simple_queue` ends with `assert status.dequeued_at >=
status.created_at`, and `durabletask-go`'s `Test_SingleTimer` asserts
`metadata.LastUpdatedAt >= metadata.CreatedAt`. Both say the same thing: a run
knows when it was asked for and when it was picked up, and those are ordered.

**This was recorded as impossible here, twice, and is not.** ISSUES entry 30
says cleat records no start time and that a schema-wide search for
`start|claim|dequeue|first_run` returns only `reclaim_count`, so queue latency
and execution time are both unavailable and `completed_at - created_at`
collapses them into one number. That was true when written. It is not true now:

  cleat#1094  added `started_at` -- "when a worker FIRST began executing this
              run" -- on all three dialects
  cleat#1106  fixed `GetWorkflowByID`, which had been selecting `created_at`
              and several other fields into locals and never assigning them, so
              a single GET returned `0001-01-01T00:00:00Z` while the LIST
              endpoint returned the real value

Both landed today. The entry is now closed and this is the coverage it was
filed to make possible.

**The order is the assertion, not the values.** A run is created, then claimed
by a worker, then finishes; each step is caused by the previous one, so the
timestamps cannot legitimately go backwards. Equality is allowed throughout --
these are three writes in quick succession and a coarse clock can collapse two
of them -- so the assertion is `<=` rather than `<`. Measured on a real run:
`created_at` 00:15:06.179793, `started_at` .187747, `completed_at` .536338, so
the gaps here are 8ms and 349ms.

**What this catches that a status assertion does not.** Every other test in this
suite reads `status` and `result`. A regression that stopped populating
`started_at`, or reverted #1106's assignment, leaves both of those correct and
every existing test green -- which is exactly how the #1106 class survived: four
fields wrong or absent on one endpoint, "found separately and every one by
accident, all within a day", per its own commit message.
"""

import json
import uuid
from datetime import datetime

import pytest

# The zero time a Go `time.Time` serialises to when nothing assigned it. This is
# the specific value #1106 was fixing, and naming it makes a regression report
# itself rather than showing up as an unparseable date.
GO_ZERO_TIME = "0001-01-01T00:00:00Z"


def _ts(record, field):
    """Parse one timestamp, failing with the reason rather than a ValueError."""
    raw = record.get(field)
    assert raw is not None, (
        f"`{field}` is absent from the run record entirely: {sorted(record)}. "
        "ISSUES 30 recorded that as the state of the world before cleat#1094 "
        "and cleat#1106; its return would reopen that entry."
    )
    assert raw != GO_ZERO_TIME, (
        f"`{field}` is the Go zero time, so something selected it and never "
        "assigned it -- the cleat#1106 shape, where GetWorkflowByID lost five "
        "fields while the LIST endpoint returned them correctly."
    )
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def test_a_run_reports_created_started_and_completed_in_that_order(
        cleat, retry_workflow):
    """The three clocks exist, are real, and do not go backwards."""
    key = f"clock-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0, "failStatus": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"the run did not complete: {final}"

    created = _ts(final, "created_at")
    began = _ts(final, "started_at")
    finished = _ts(final, "completed_at")

    # `<=`, not `<`: three writes inside a few hundred milliseconds, and a
    # coarse clock may collapse two of them. Ordering is the claim; distinctness
    # is not.
    assert created <= began, (
        f"the run reports being started BEFORE it was created: created_at="
        f"{created.isoformat()} started_at={began.isoformat()}. A worker cannot "
        "claim a row that does not exist, so this is a clock or an assignment "
        "defect rather than a race."
    )
    assert began <= finished, (
        f"the run reports finishing BEFORE it started: started_at="
        f"{began.isoformat()} completed_at={finished.isoformat()}."
    )


def test_the_single_get_agrees_with_the_list_about_when_a_run_was_created(
        cleat, retry_workflow):
    """The two endpoints must not disagree about the same field.

    This is cleat#1106 exactly, and it is worth its own case because the
    disagreement is invisible from either endpoint alone. `GET
    /api/workflows/{id}` returned `0001-01-01T00:00:00Z` while
    `GET /api/workflows` returned the true value for the same run -- so a test
    reading one of them, or a caller using one of them, sees nothing wrong.

    Found by measuring a run against a stale binary and being unable to
    reconcile it with the source, which is a slower route to the same place.
    """
    key = f"clock2-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0, "failStatus": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]
    cleat.await_terminal(run_id, timeout=90.0)

    code, single = cleat.api(f"/api/workflows/{run_id}")
    assert code == 200, f"single GET answered {code}: {single!r}"

    code, listing = cleat.api("/api/workflows?limit=50")
    assert code == 200, f"list answered {code}: {listing!r}"
    rows = listing if isinstance(listing, list) else listing.get(
        "workflows", listing.get("items", []))
    match = [r for r in rows if r.get("id") == run_id]
    assert match, (
        f"the run is missing from the first 50 rows of the list, so this test "
        f"cannot compare the two views. run={run_id}"
    )

    assert _ts(single, "created_at") == _ts(match[0], "created_at"), (
        f"the two endpoints disagree about created_at for the same run: single "
        f"GET says {single.get('created_at')!r}, list says "
        f"{match[0].get('created_at')!r}. That is cleat#1106's shape and it is "
        "silent from either side on its own."
    )
