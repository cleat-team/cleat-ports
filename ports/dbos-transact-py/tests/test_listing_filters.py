r"""Filtering the run listing.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

PORTED FROM CADENCE, not from DBOS. `uber/cadence`'s
`dbVisibilityPersistenceTest.go` asks a question no ported suite asked before:
not "does the listing contain this run" but "does the listing return the RIGHT
runs when asked a question". cleat#1182 and cleat#1183 both came out of reading
three of those cases; this ports the filtering half properly.

THE RE-EXPRESSION IS THE WORK, because the two engines model this differently
and a transliteration would assert nothing. Cadence keeps open and closed
executions in separate visibility records, so its cases read
`RecordWorkflowExecutionStarted` -> appears in `ListOpenWorkflowExecutions`,
then `RecordWorkflowExecutionClosed` -> leaves open, enters closed. cleat has
ONE row per run in `workflow_instances` carrying a `status`, so the same
property is "the run is selected by status=running and stops being selected
once it is done". Same assertion about behaviour; different mechanism entirely.

WHAT IS DELIBERATELY NOT PORTED, and why, so the gaps are a record rather than
an omission:

  * `TestCronVisibility` asserts a listed execution reports `IsCron`. cleat
    exposes no cron or schedule flag on a listed run -- `grep -n "IsCron\|
    is_cron\|from_schedule" engine/store_types.go cmd/cleat-worker/server.go`
    returns nothing. Not portable, and arguably a gap; not filed here because
    whether a listing should carry provenance is a product question.
  * `TestClosedWithoutStarted` records a CLOSE with no prior START and asserts
    it is queryable. cleat's row is created at start, so the state does not
    exist -- inexpressible rather than missing.
  * `TestMultipleUpserts` and `TestUpsertWorkflowExecution` exercise Cadence's
    visibility upsert API with memo and search attributes. No counterpart.
  * `TestFilteringByWorkflowID` filters by the business workflow id, which
    Cadence tracks separately from the run id. cleat has one id per run, so
    `id_prefix` answers a different question; the analogous property is ported
    below under that name rather than pretended to be the same one.
"""

import uuid

import pytest


def _start(cleat, workflow, key):
    """Start one retry-workflow run that completes immediately."""
    status, started = cleat.start(workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0, "failStatus": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"
    return started["id"]


def _list(cleat, query=""):
    code, rows = cleat.api(f"/api/workflows{query}")
    assert code == 200, f"the workflow list answered {code}: {rows!r}"
    assert isinstance(rows, list), f"expected a list, got {type(rows).__name__}"
    return rows


def test_a_completed_run_is_selected_by_its_status_and_not_by_another(
    cleat, retry_workflow
):
    """PINS the property Cadence splits across two record types.

    Upstream records a start, finds it in the OPEN list, records a close, and
    finds it gone from open and present in closed. cleat has one row whose
    status changes, so the equivalent is: after completion the run is returned
    when asking for `done` and not when asking for `running`.

    The negative half is the half that matters. "Filtering by done returns it"
    passes on an engine that ignores the filter entirely and returns every run,
    which is exactly the failure this is built to catch -- so the same run must
    also be ABSENT under a status it does not have.
    """
    key = f"filt-{uuid.uuid4().hex[:8]}"
    run_id = _start(cleat, retry_workflow, key)
    final = cleat.await_terminal(run_id, timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"

    done_ids = {r.get("id") for r in _list(cleat, "?status=done&limit=200")}
    assert run_id in done_ids, (
        f"run {run_id} finished with status 'done' and is absent from "
        f"?status=done ({len(done_ids)} rows). Either the filter excludes rows "
        "it should keep, or the terminal status written is not the one the "
        "filter matches."
    )

    running_ids = {r.get("id") for r in _list(cleat, "?status=running&limit=200")}
    assert run_id not in running_ids, (
        f"run {run_id} is 'done' and was still returned by ?status=running. A "
        "filter that returns rows not matching it is indistinguishable from no "
        "filter at all, and the positive assertion above would pass either way."
    )


def test_filtering_by_definition_name_excludes_other_definitions(
    cleat, retry_workflow, own_identity_workflow
):
    """Cadence's TestFilteringByType, re-expressed.

    Upstream lists by workflow TYPE and asserts only the matching execution
    comes back. cleat's equivalent axis is `def_name`.

    Two DIFFERENT definitions are deployed and started deliberately. With one,
    "every row matches" and "the filter works" are the same observation.
    """
    key = f"deffilt-{uuid.uuid4().hex[:8]}"
    mine = _start(cleat, retry_workflow, key)
    cleat.await_terminal(mine, timeout=60.0)

    status, other_started = cleat.start(own_identity_workflow, {"holdMs": 0})
    assert status == 201, f"start rejected: {status} {other_started}"
    other = other_started["id"]
    cleat.await_terminal(other, timeout=60.0)

    rows = _list(cleat, f"?def_name={retry_workflow}&limit=200")
    ids = {r.get("id") for r in rows}
    assert mine in ids, (
        f"run {mine} is a {retry_workflow!r} run and ?def_name={retry_workflow} "
        f"did not return it ({len(rows)} rows)."
    )
    assert other not in ids, (
        f"run {other} is a {own_identity_workflow!r} run and was returned by "
        f"?def_name={retry_workflow}. The filter is not discriminating."
    )
    names = {r.get("def_name") for r in rows if r.get("def_name") is not None}
    assert names <= {retry_workflow}, (
        f"?def_name={retry_workflow} returned rows for {sorted(names)}."
    )


def test_limit_and_offset_walk_the_listing_without_repeating_or_skipping(
    cleat, retry_workflow
):
    """Cadence's TestVisibilityPagination, re-expressed.

    Upstream pages with PageSize plus an opaque NextPageToken. cleat pages with
    `limit` and `offset`, so the token mechanism does not port -- but the
    property does, and it is the property that has value: walking the listing a
    page at a time yields each run once.

    Asserted over THREE runs of this test's own making rather than over the
    whole table, because the table is shared with every other test in the suite
    and a global assertion would be flaky by construction.
    """
    keys = [f"page-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    mine = []
    for k in keys:
        rid = _start(cleat, retry_workflow, k)
        cleat.await_terminal(rid, timeout=60.0)
        mine.append(rid)

    seen, offset, pages = [], 0, 0
    while pages < 100:
        page = _list(cleat, f"?status=done&limit=1&offset={offset}")
        pages += 1
        if not page:
            break
        assert len(page) == 1, f"limit=1 returned {len(page)} rows"
        seen.append(page[0].get("id"))
        offset += 1
        if len(seen) >= 200:
            break

    assert len(seen) == len(set(seen)), (
        "paging with limit=1 returned the same run twice: "
        f"{[i for i in seen if seen.count(i) > 1][:3]}. An unstable sort makes "
        "offset paging repeat and omit rows, which is invisible to a test that "
        "only counts the total."
    )
    missing = [r for r in mine if r not in seen]
    assert not missing, (
        f"{len(missing)} of this test's 3 runs were never returned while paging "
        f"the whole listing one row at a time: {missing}."
    )


def test_the_time_window_is_half_open_so_adjacent_windows_tile(
    cleat, retry_workflow
):
    """Cadence's TestBasicVisibilityTimeSkew, re-expressed onto cleat's bounds.

    Upstream bounds the query with EarliestTime/LatestTime. cleat's equivalents
    are `started_after` and `started_before`, and they are NOT symmetric --
    `engine/store_types.go:391` documents a half-open interval, inclusive of
    after and exclusive of before, "so adjacent windows tile without
    double-counting a row on the boundary". `workflow_list_query.go:49` is
    `created_at >= after`; :52 is the strict form for before.

    THIS TEST FIRST ASSERTED THE OPPOSITE AND FAILED, correctly. I wrote it
    expecting a run created AT the boundary to be excluded by
    `started_after=boundary`; it is returned, because the bound is inclusive by
    design. The engine was right. Recorded here rather than silently corrected,
    because "the filter looked wrong" and "the interval is half-open on purpose"
    produce the same red test and only one of them is a defect.

    Pinning the tiling property is also a stronger assertion than the one it
    replaces: it needs a single run rather than two, so it cannot be made flaky
    by the ordering of two runs created milliseconds apart.
    """
    run_id = _start(cleat, retry_workflow, f"win-{uuid.uuid4().hex[:8]}")
    cleat.await_terminal(run_id, timeout=60.0)

    code, row = cleat.api(f"/api/workflows/{run_id}")
    assert code == 200, f"fetching the run answered {code}: {row!r}"
    t = row.get("created_at") or row.get("createdAt")
    assert t, (
        f"the run record carries no created_at, so this test cannot build a "
        f"window from it: {sorted(row)}"
    )

    after = {r.get("id") for r in _list(cleat, f"?started_after={t}&limit=200")}
    assert run_id in after, (
        f"run {run_id} was created at {t} and ?started_after={t} did not return "
        "it. The lower bound is documented inclusive (store_types.go:391, "
        "`created_at >= after`), so a row exactly on it must be selected."
    )

    before = {r.get("id") for r in _list(cleat, f"?started_before={t}&limit=200")}
    assert run_id not in before, (
        f"run {run_id} was created at {t} and ?started_before={t} returned it. "
        "The upper bound is documented EXCLUSIVE, and that asymmetry is the "
        "whole point: if both edges included the boundary, two adjacent windows "
        "would each return this run and any count over them would double-count "
        "it."
    )


def test_an_id_prefix_selects_only_runs_whose_id_starts_with_it(
    cleat, retry_workflow
):
    """The nearest expressible form of Cadence's TestFilteringByWorkflowID.

    NOT the same question. Cadence filters by the business workflow id, which
    it tracks separately from the run id; cleat has one id per run, so there is
    nothing to group by. `id_prefix` is a LIKE prefix over the run id
    (engine/workflow_list_query.go:46, case-sensitive by design), and the
    analogous property is that it selects on that prefix and nothing else.

    Named for what it does rather than for the upstream case, so nobody later
    reads it as evidence that cleat has workflowID/runID separation.
    """
    run_id = _start(cleat, retry_workflow, f"pfx-{uuid.uuid4().hex[:8]}")
    cleat.await_terminal(run_id, timeout=60.0)

    prefix = run_id[:8]
    rows = _list(cleat, f"?id_prefix={prefix}&limit=200")
    ids = {r.get("id") for r in rows}
    assert run_id in ids, (
        f"run {run_id} was not returned by ?id_prefix={prefix}, which is its "
        f"own first 8 characters."
    )
    bad = [i for i in ids if not str(i).startswith(prefix)]
    assert not bad, (
        f"?id_prefix={prefix} returned {len(bad)} run(s) whose id does not "
        f"start with it, e.g. {bad[:3]}."
    )
