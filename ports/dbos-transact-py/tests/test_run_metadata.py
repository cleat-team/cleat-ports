"""What a run records about itself: its clock, and what a repeat submission is.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Its own module rather than an addition to `test_queues.py`, which is where the
sibling deduplication test lives and would have been the friendlier place to
read it. The inventory in README.md credits a whole module to ONE upstream file
(`scripts/count-queue-cases.py`, `MAPPING`), and `test_queues.py` is credited to
upstream `test_queue.py`. This case comes from `test_dbos.py`, so filing it
there would have added a point to the wrong upstream file's Ported column --
and WORKLIST.md's `test_dbos.py` section names exactly two portable cases, so
the survey and the inventory would have disagreed about which file this is.
"""

import uuid


def test_a_repeated_start_is_not_counted_as_a_recovery(cleat, retry_workflow):
    """A re-submitted job is deduplicated, not recovered, and its clock is sane.

    Ported from upstream's `test_simple_workflow_attempts_counter`, which runs
    the same workflow id ten times and asserts `recovery_attempts == 1` and
    `updated_at >= created_at` throughout.

    The counters start from different places and mean the same thing: DBOS
    counts attempts from one, cleat counts *reclaims* from zero, so upstream's
    "still 1" is cleat's "still 0". Both say a repeat submission must not look
    like a worker having died.

    This is the companion to `test_queues.py::test_the_same_idempotency_key
    _starts_one_run`, and the distinction is worth stating because the two are
    easy to conflate. That test proves the body runs once. This one proves the
    engine does not record the second submission as a *failure recovery* -- a
    run whose reclaim_count climbed on ordinary client retries would make the
    dead-letter threshold a function of how twitchy the caller is.

    The timestamp half only became assertable today. `GET /api/workflows/:id`
    reported `created_at` as `0001-01-01T00:00:00Z` for every run until
    cleat#1105 -- present, parseable and wrong -- so `started_at - created_at`,
    which is the queue latency cleat#1090 exists to expose, had the year 1 as an
    operand. This test was run against a worker built from the commit before
    that fix and fails on exactly that string.
    """
    key = f"norecover-{uuid.uuid4().hex[:8]}"
    idem = f"idem-{uuid.uuid4().hex[:8]}"
    payload = {"service": "flaky", "key": key, "attempts": 1, "intervalMs": 50,
               "failTimes": 0, "failStatus": 0}

    status, first = cleat.start(retry_workflow, payload, idempotency_key=idem)
    assert status == 201, f"first start rejected: {status} {first}"
    run_id = first["id"]

    # Upstream submits ten times. Two repeats distinguish "does not count
    # repeats" from "counts them"; the other eight only make the suite slower
    # without making the claim stronger.
    for i in range(2):
        code, again = cleat.start(retry_workflow, payload, idempotency_key=idem)
        assert code == 200, f"repeat {i + 1} answered {code}, not 200: {again!r}"

    final = cleat.await_terminal(run_id, timeout=90.0)
    assert final["status"] == "done", f"the run did not complete: {final!r}"

    # `.get("reclaim_count", 0)` would pass when the field is ABSENT, letting
    # the default supply the answer the test claims to have measured.
    assert "reclaim_count" in final, (
        f"the run carries no reclaim_count at all, so this test would otherwise "
        f"pass on a default rather than on a measurement: {final!r}"
    )
    assert final["reclaim_count"] == 0, (
        f"reclaim_count is {final['reclaim_count']!r} after two repeat "
        "submissions, want 0. A repeat start is deduplication, not recovery: "
        "nothing was reclaimed from a worker that stopped heartbeating. If this "
        "climbs with client retries, the dead-letter threshold becomes a "
        "function of caller behaviour rather than of failure."
    )

    created = final.get("created_at")
    started = final.get("started_at")
    completed = final.get("completed_at")
    assert created and not created.startswith("0001-"), (
        f"created_at is {created!r}. A year-one timestamp is not an absent "
        "value -- it parses and compares, so every latency computed from it is "
        "silently wrong (cleat#1105)."
    )
    assert started, f"started_at is absent on a completed run: {final!r}"
    assert completed, f"completed_at is absent on a completed run: {final!r}"

    # Ordering only. All three are stamped by the DATABASE, so asserting a
    # duration would be measuring this machine rather than the engine.
    assert created <= started <= completed, (
        f"the run's clock is out of order: created={created!r} "
        f"started={started!r} completed={completed!r}. These are ISO-8601 UTC "
        "from one clock, so string order is time order, and out of order means "
        "queue latency or execution time comes out negative."
    )
