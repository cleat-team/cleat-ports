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
import uuid

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


# The child must outlast the parent's first segment. AwaitChild has an
# "already completed" path that records the result and never suspends, so a
# fast child never reaches the case below.
SLOW_CHILD_MS = 2500


def test_awaiting_one_child_survives_the_parent_suspending(cleat, await_one_child_workflow):
    """`AwaitChild` — the singular call, which nothing else here exercises.

    DBOS's single-child case is `handle.get_result()`, and the natural port of
    it is `AwaitAllChildren([runID])` — which is what
    test_a_single_child_round_trips above does. So cleat's `AwaitChild` had no
    coverage at all, under a name that sounds like it did, and cleat#845 lived
    there: when the child completed, the engine wrote its result into the
    **parent's** `await_child` event row and left that row's checksum stale, so
    the parent failed its next segment with a checksum mismatch and never
    resumed. Measured before the fix: 3 runs of 3 failed with

        checksum verification failed: verify events: workflow <id> step 1:
        checksum mismatch (expected a0212ee0fc7b6167, got d66082e106bc2725)

    The event type the injection matched, `await_child`, is written by this
    call and by no other — which is why every fan-out test passed throughout.
    """
    tag = f"aoc-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(await_one_child_workflow, {"ms": SLOW_CHILD_MS, "tag": tag})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the parent did not complete: {final.get('error') or final!r}. "
        "A checksum mismatch here means something rewrote the parent's recorded "
        "events while it was suspended."
    )

    # The parent must actually have suspended, or this test proves nothing:
    # a child that finished inside the first segment takes AwaitChild's
    # "already completed" path and the defect above is never reached. A
    # suspension bumps the generation, so generation > 1 is the evidence that
    # the run went through resume rather than straight through.
    assert final.get("generation", 1) > 1, (
        f"the parent completed in one segment (generation {final.get('generation')}), "
        f"so it never suspended and this test did not exercise the resume path. "
        f"Raise SLOW_CHILD_MS above {SLOW_CHILD_MS}."
    )

    body = _body(final)
    child = body["child"]
    if isinstance(child, str):
        child = json.loads(child)
    assert child["tag"] == tag, f"the child's result did not round-trip: {body!r}"
