"""The read API a caller actually operates cleat through.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream files: `tests/test_workflow_management.py` (list, inspect) and
`tests/test_client.py` (the client surface). DBOS exposes these through a
Python client; cleat exposes them over HTTP, so the assertions transfer and the
mechanism does not.

This file exists because **nothing had ever called most of these endpoints from
a test.** The first probe of them found cleat#899 -- `/api/workflows/{id}/dag`
returned a raw SQL driver error for every workflow that is not a DAG, which is
nearly all of them, because a NULL `dag_spec` was scanned into a
`json.RawMessage` that cannot hold one. It had three unit tests and none
covered a NULL column.

The per-run sub-resources are split across two prefixes, measured rather than
read off the route table:

    /api/instances/{id}/events     /api/instances/{id}/state
    /api/workflows/{id}/history    /api/workflows/{id}/promises

`/api/workflows/{id}/events` and `/api/instances/{id}/history` both 404.
"""

import json
import time
import uuid

import pytest


def test_the_workflow_list_contains_a_run_that_was_started(cleat, retry_workflow):
    """A started run appears in the collection, not only at its own URL.

    Listing and fetching are different code paths -- cleat#830 was seven routes
    registered on a table the binary never served, so an endpoint answering at
    all is worth asserting separately from what it answers.
    """
    key = f"list-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"
    cleat.await_terminal(started["id"], timeout=60.0)

    code, listing = cleat.api("/api/workflows")
    assert code == 200, f"the workflow list answered {code}: {listing!r}"
    assert isinstance(listing, list), f"expected a list, got {type(listing).__name__}"

    ids = {row.get("id") for row in listing}
    assert started["id"] in ids, (
        f"run {started['id']} completed but is absent from /api/workflows "
        f"({len(listing)} rows returned)"
    )


def test_the_definition_list_reports_a_deployed_workflow(cleat, retry_workflow):
    """A deployed definition is visible with the fields a caller needs.

    `version` and `min_version` are asserted present because the engine
    validates a run against them (cleat#861 was deploy-workflow writing a
    version the binary did not report), so a definition list that omits them
    cannot answer the question it exists for.
    """
    code, defs = cleat.api("/api/definitions")
    assert code == 200, f"the definition list answered {code}: {defs!r}"

    row = next((d for d in defs if d.get("name") == retry_workflow), None)
    assert row is not None, (
        f"{retry_workflow!r} was deployed but is not in /api/definitions: "
        f"{[d.get('name') for d in defs]}"
    )
    for field in ("version", "abi_version", "min_version"):
        assert field in row, f"the definition record has no {field!r}: {row!r}"


def test_the_plugin_list_reports_what_the_binary_linked(cleat):
    """The plugin list is the worker's own account of its import block.

    This is the HTTP counterpart of `--list-plugins`, added in cleat#857
    because "the import block is the feature set" -- a plugin registers via
    init(), so what is linked is not otherwise discoverable at runtime. The
    assertion is on llm specifically, since that is the one this suite drives
    in test_plugins.py.
    """
    code, plugins = cleat.api("/api/plugins")
    assert code == 200, f"the plugin list answered {code}: {plugins!r}"

    names = {p.get("name") for p in plugins}
    assert "llm" in names, (
        f"the llm plugin is linked into cleat-worker and driven by "
        f"test_plugins.py, but /api/plugins does not report it: {sorted(names)}"
    )


def test_recorded_events_are_readable_while_a_workflow_is_suspended(
    cleat, signal_pair, fixture_calls
):
    """The event history is readable, ordered, and gone once the run completes.

    Both halves are measured, and the second is why the first needs a SUSPENDED
    workflow. Events are buffered within a segment and written when it ends, and
    the history is purged at completion -- so a workflow that runs start to
    finish in one segment reports zero events at every moment a test could look,
    both while running and after.

    An earlier version of this test used a single-segment workflow and asserted
    events existed. It failed, and the failure was the test's premise, not the
    engine's behaviour.

    Steps must be strictly increasing: the history IS the replay order, and
    cleat#846 was a child rewriting its parent's recorded event and leaving the
    checksum stale, so an intact sequence is not a given.
    """
    receiver, sender = signal_pair
    key = f"events-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(receiver, {"key": key, "timeoutMs": 30000})
    assert status == 201, f"start rejected: {status} {started}"

    # The receiver announces itself before awaiting, so this waits for the
    # segment that carries the announcement to have ended.
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if fixture_calls(f"{key}-waiting") > 0:
            break
        time.sleep(0.2)
    else:
        pytest.fail("the receiver never announced itself, so nothing has been recorded yet")

    code, events = cleat.api(f"/api/instances/{started['id']}/events")
    assert code == 200, f"the event list answered {code}: {events!r}"
    assert events, (
        "a suspended workflow that made a durable call before suspending has no "
        "recorded events"
    )

    steps = [e["step"] for e in events]
    assert steps == sorted(steps), f"events are not in step order: {steps}"
    assert len(steps) == len(set(steps)), f"a step number repeats: {steps}"
    assert any(e.get("type") == "call" for e in events), (
        f"the workflow made a durable call and no event records it: "
        f"{[e.get('type') for e in events]}"
    )

    # Release it, and the history goes.
    cleat.signal(started["id"], "go", '{"via":"http"}')
    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"the receiver did not complete: {final!r}"

    code, after = cleat.api(f"/api/instances/{started['id']}/events")
    assert code == 200 and after == [], (
        f"history is purged on completion, so a terminal run should report no "
        f"events; got {code} {after!r}"
    )


def test_a_signal_delivered_over_http_reaches_the_workflow(cleat, signal_pair):
    """A signal can be delivered by an operator, not only by another workflow.

    test_signals.py covers the cross-workflow path. This is the HTTP one, which
    is a different handler and a different authorisation story -- and the field
    is `signal_name`, not `name`; `name` is a 400.
    """
    receiver, _ = signal_pair
    key = f"httpsig-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(receiver, {"key": key, "timeoutMs": 30000})
    assert status == 201, f"start rejected: {status} {started}"

    code, body = cleat.signal(started["id"], "go", '{"via":"http"}')
    assert code == 200, f"the signal was not accepted: {code} {body!r}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", f"the receiver did not complete: {final!r}"

    result = final["result"]
    result = json.loads(result) if isinstance(result, str) else result
    assert result.get("outcome") == "signalled", (
        f"the workflow was signalled over HTTP and did not observe it: {result!r}"
    )
    assert result.get("payload") == '{"via":"http"}', (
        f"the payload did not round-trip: {result!r}"
    )


def test_an_unknown_run_is_a_clean_404_on_every_read_path(cleat):
    """Every per-run read answers 404 for an id that does not exist.

    Not 500, and not 200. The 200 case is why this is worth asserting on each
    path rather than one: under cleat#830 these fell through to the SPA
    handler, which answers 200 with HTML for any unmatched path, so a client
    got a web page where it expected JSON.

    This test used to be split in two. Three of the five paths -- events,
    history and promises -- answered 200 with an empty list for a run that did
    not exist, so a caller could not tell "no events" from "no such workflow"
    and a typo in an id looked like a healthy empty result. That half asserted
    the WRONG behaviour on purpose, with a note saying to update it if the
    paths ever started answering 404, and it is what found cleat#900.

    They 404 now. cleat#917 landed the fix and this test failed in CI the same
    day, which is the whole point of pinning current behaviour rather than
    skipping it: the assertion was the thing that noticed.

    Note the empty list was never a safe thing to accept even as a placeholder.
    An empty collection is a NORMAL state here -- event history is buffered
    within a segment and purged at completion, so a legitimately finished run
    also reports [] -- and 200 [] therefore meant three different things at
    once, with nothing to separate them.
    """
    missing = str(uuid.uuid4())
    for path in (
        f"/api/workflows/{missing}",
        f"/api/instances/{missing}/state",
        f"/api/instances/{missing}/events",
        f"/api/workflows/{missing}/history",
        f"/api/workflows/{missing}/promises",
    ):
        code, body = cleat.api(path)
        assert code == 404, (
            f"{path} answered {code} for a nonexistent run: {body!r}. "
            f"200 means either the SPA fallback served it (cleat#830) or the "
            f"collection endpoints have regressed to reporting empty rather "
            f"than absent (cleat#900); 500 means the status came from an error "
            f"message (cleat#832)."
        )


def test_an_empty_collection_on_a_real_run_is_still_200(cleat, retry_workflow):
    """The control on the test above.

    Making the five paths 404 for an unknown run is only correct if a run that
    DOES exist and genuinely has nothing still answers 200. Without this, an
    implementation that 404'd every empty collection -- including on live runs,
    where empty is normal -- would pass every assertion above.

    That is not hypothetical: cleat#900's fix is one shared `runExists` helper
    in front of all three collections, so a wrong lookup there fails in exactly
    this direction and nothing else in this suite would catch it.
    """
    key = f"empty-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    for path in (
        f"/api/instances/{run_id}/events",
        f"/api/workflows/{run_id}/history",
        f"/api/workflows/{run_id}/promises",
    ):
        code, body = cleat.api(path)
        assert code == 200, (
            f"{path} answered {code} for a run that EXISTS: {body!r}. "
            f"An empty collection on a live run is normal -- history is "
            f"buffered per segment and purged at completion -- so this must "
            f"stay 200 while an unknown run 404s."
        )


def test_a_workflow_without_a_dag_reports_no_dag_rather_than_an_error(cleat, retry_workflow):
    """A non-DAG workflow answers cleanly rather than leaking a scan error.

    This is the assertion that found #899, and it is kept now that the fix has
    landed rather than deleted: the endpoint returned

        load dag_spec: sql: Scan error on column index 0, name "dag_spec":
        unsupported Scan, storing driver.Value type <nil> into type *jsontext.Value

    straight to the client, for every workflow in this suite.
    """
    key = f"dag-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 1,
        "intervalMs": 50, "failTimes": 0,
    })
    assert status == 201, f"start rejected: {status} {started}"

    code, body = cleat.api(f"/api/workflows/{started['id']}/dag")
    assert code in (200, 404), (
        f"a workflow with no DAG answered {code}: {body!r}"
    )
    if code == 200:
        assert not isinstance(body, dict) or "error" not in body, (
            f"a 200 carrying an error field: {body!r}"
        )
