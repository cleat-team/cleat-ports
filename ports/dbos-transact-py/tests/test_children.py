"""Child workflows and fan-in, ported from dbos-transact-py's child tests.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS spawns children with `start_workflow` and collects them through handles.
Cleat spawns by *name* — `h.ChildWorkflow("child_leaf", input)` returns a run ID
— and fans in with `AwaitAllChildren` or `AwaitAnyChild`. The assertions port;
the handle object does not.

These tests are the first coverage of the fan-in path that would notice a
**wrong answer** rather than a crash. Both defects they were written against
returned success with empty data:

* cleat#781 — every workflow that spawned a child failed checksum verification,
  because the atomic child insert omitted the `payload` column and never
  advanced the checksum chain.
* cleat#780 — every child result came back empty, because the generated guest
  adapter split the result array by scanning for `}` without modelling string
  escapes, cutting each object at the escaped brace inside its own payload.

A test asserting only "the parent completed" would have passed throughout both.
Hence the per-child result assertions below rather than a count.
"""

import json

import pytest

CHILD_MS = 500


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _await(cleat, workflow, n, mode):
    status, started = cleat.start(workflow, {"n": n, "ms": CHILD_MS, "mode": mode})
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", (
        f"run did not complete: {final.get('status')!r} "
        f"{(final.get('error') or '')[:300]!r}"
    )
    return _body(final)


def test_await_all_children_returns_every_child_s_own_result(cleat, fanout_workflow):
    """The assertion cleat#780 was silently failing.

    Each child returns a tag naming itself, so a result landing on the wrong
    child is as visible as a missing one. Checking the tags rather than the
    count is the whole point: the count was always right.
    """
    body = _await(cleat, fanout_workflow, n=3, mode=0)

    assert body["spawned"] == 3
    results = body["results"]
    assert len(results) == 3, f"expected 3 child results, got {results!r}"

    tags = []
    for i, r in enumerate(results):
        assert r.get("run_id"), f"child {i} has no run_id: {r!r}"
        assert not r.get("error"), f"child {i} reported an error: {r!r}"
        assert r.get("result"), (
            f"child {i} returned an empty result: {r!r}. This is the cleat#780 "
            "shape — run_id present, result empty, no error, workflow green."
        )
        tags.append(json.loads(r["result"])["tag"])

    assert tags == ["child-0", "child-1", "child-2"], (
        f"results are not in spawn order, or a result landed on the wrong "
        f"child: {tags!r}"
    )

    run_ids = [r["run_id"] for r in results]
    assert len(set(run_ids)) == 3, f"children share run IDs: {run_ids!r}"


def test_await_any_child_returns_one_completed_child(cleat, fanout_workflow):
    """Deliberately does NOT assert which child comes back first.

    `AwaitAnyChild` sorts run IDs and returns the lowest one that is *done*,
    not the first to complete (cleat §3.222). The children here are staggered
    500/1000/1500ms, so "the fastest returns first" is a reasonable thing to
    expect and would fail — for a real reason, but not the one this test is
    about. Asserting "some child that really ran" keeps the test honest until
    3.222 is settled; tighten it then.
    """
    body = _await(cleat, fanout_workflow, n=3, mode=1)

    assert body["spawned"] == 3
    assert body.get("run_id"), f"no run_id returned: {body!r}"

    tag = body["result"]["tag"]
    assert tag in {"child-0", "child-1", "child-2"}, (
        f"returned a child that was never spawned: {tag!r}"
    )


def test_a_single_child_round_trips(cleat, fanout_workflow):
    """The narrowest case, kept because it isolates the two fixed defects.

    With one child there is exactly one child_workflow event and one await, so
    a checksum failure here is unambiguous, and a lost result cannot be blamed
    on array splitting.
    """
    body = _await(cleat, fanout_workflow, n=1, mode=0)

    assert body["spawned"] == 1
    assert len(body["results"]) == 1
    assert json.loads(body["results"][0]["result"])["tag"] == "child-0"


def test_children_actually_ran_as_separate_workflows(cleat, fanout_workflow):
    """Guards the above from passing if the parent fabricated the results.

    Every returned run_id must be a real workflow that reached `done` — which
    also confirms the children executed rather than the parent inlining them.
    """
    body = _await(cleat, fanout_workflow, n=2, mode=0)

    for r in body["results"]:
        status, child = cleat.get(r["run_id"])
        assert status == 200, f"child {r['run_id']} not found: {status}"
        assert child["status"] == "done", (
            f"child {r['run_id']} is {child['status']!r}, but the parent "
            "reported its result"
        )
        assert child["def_name"] == "child_leaf"
