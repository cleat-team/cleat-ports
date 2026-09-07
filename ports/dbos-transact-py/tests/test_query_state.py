"""Externally readable workflow state.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS's `set_event` / `get_event` let a running workflow publish a value that a
caller outside it can read before the workflow finishes. Cleat's equivalent is
`h.SetQueryState` plus `GET /api/workflows/:id/query?key=...`, and cleat's own
docs state the property the upstream tests assert:

    the workflow proactively records queryable state to the database at points
    of its choosing, and that state is durable and externally readable ...
    regardless of whether any worker currently has the workflow loaded. It
    answers "what is this workflow's status" without needing anything to be
    running at query time.

A suspended workflow is precisely that case, and it was the one case that
returned nothing (cleat#844): the engine stored query state on the 'done' and
'failed' branches of its finalize routine and not on 'ready', so a value
reached the database only when the workflow had already finished — the moment
its result is available and the query is least useful.

The conftest helper these tests use, `poll_query`, was already there, with a
docstring naming the exact requirement: "the interesting value is published
mid-run: a caller that waits for completion first has already missed it".
Nothing called it. The harness anticipated the property; no test asserted it,
and the engine did not hold it.
"""

import json
import uuid

SLEEP_MS = 6000


def test_query_state_is_readable_while_the_workflow_is_suspended(cleat, query_state_workflow):
    """The whole point of the mechanism, and the case that did not work.

    Asserted while the workflow is asleep — no worker holds it — which is what
    the documentation promises and what cleat#844 broke.
    """
    tag = f"qs-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(query_state_workflow, {"tag": tag, "sleepMs": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # Published before the sleep, so it must be visible during it. poll_query
    # waits for a value rather than sampling once: the workflow needs a moment
    # to reach its first suspension, and a bare read races that.
    phase = cleat.poll_query(run_id, "phase", timeout=15.0)
    assert phase == "started", (
        f"query state read {phase!r} while the workflow was suspended, want 'started'.\n"
        "None means nothing was ever published. 'finished' means the value only "
        "appeared once the workflow had completed — poll_query waits for a value, so "
        "against an engine that stores query state only on its terminal branches the "
        "first value it ever sees is the final one. Either way the suspending segment "
        "did not store what the workflow had published, and the state becomes readable "
        "at the moment the result is available anyway."
    )

    # Set once, before the sleep, and never again: this is the half that shows
    # an earlier segment's value survives rather than being replaced wholesale.
    assert cleat.poll_query(run_id, "tag", timeout=5.0) == tag

    final = cleat.await_terminal(run_id, timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"


def test_a_reader_sees_the_current_value_not_the_final_one(cleat, query_state_workflow):
    """`phase` changes across the suspension, so the two reads must differ.

    Without this, a test could pass against an engine that published nothing
    until completion and then answered every read with the final value — the
    first assertion above would still fail, but only because of timing, and a
    slower machine could hide it. Comparing the two reads makes the difference
    the assertion rather than the wall clock.
    """
    tag = f"qs-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(query_state_workflow, {"tag": tag, "sleepMs": SLEEP_MS})
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    during = cleat.poll_query(run_id, "phase", timeout=15.0)

    final = cleat.await_terminal(run_id, timeout=60.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"
    after_status, after = cleat.query(run_id, "phase")
    assert after_status == 200, f"query after completion: {after_status} {after}"

    assert during == "started" and after["value"] == "finished", (
        f"phase read {during!r} while suspended and {after['value']!r} after completion; "
        "the two must differ, or the reader is not seeing the value the workflow "
        "published at the time it published it"
    )
