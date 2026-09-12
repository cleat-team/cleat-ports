"""What priority does a child workflow get?

`cleat/runtime_children.go:22-25` documents the contract in a comment:

    Priority controls scheduling order. 0 = highest priority; lower numbers are
    scheduled first. Children do NOT inherit the parent's priority.

`test_priority_order.py` established that priority genuinely orders dispatch for
TOP-LEVEL runs, and did the work to separate "recorded" from "honoured". This
file asks the question one level down, and it is a different question with a
sharper answer than the comment gives.

"Do not inherit" says what does not happen. `engine/children.go:16` says what
does: the no-options `ChildWorkflow` path passes priority as a literal `0`, and
every claim query orders `priority ASC` -- `migrations/postgres/023`, `040`,
`055`, and both SQL Server paths in `engine/mssql_lifecycle.go`. So a child
started the ordinary way does not merely fail to inherit. IT IS GIVEN THE BEST
PRIORITY THERE IS, and a low-priority parent's children jump the queue ahead of
that parent's own peers. A reader of the comment alone would not predict that,
and might reasonably guess children default to the middle, or to the same value
as an unprioritised top-level start.

Nothing in any of the four ports set `ChildWorkflowOptions.Priority` before this
file, and nothing asserted the default, so both halves were a documented promise
with no test behind it.

WHY THIS ASSERTS RECORDED VALUES AND NOT OBSERVED ORDER, which is the opposite
of what test_priority_order.py concluded for top-level runs. That file needed an
ordering assertion because the alternative hypothesis was live: priority might
have been a column nothing read. It is no longer live -- that test demonstrated
the claim query honours the column, on the same code path children are claimed
through. What is unknown here is narrower: WHICH VALUE a child is given. Once
that is pinned, ordering follows from a result already in this suite, and paying
for a second saturation run (60 enqueued workflows, ~9s holds) to re-derive it
would be buying an answer twice.

The risk in that reasoning is that children might be claimed by a different
query than top-level runs. They are not: `engine/children.go` writes a row into
`workflow_instances` like any other start, and the claim queries do not
distinguish. If that ever changes, this file's reasoning expires and the
ordering assertion has to be paid for.
"""

import json
import uuid

import pytest


PARENT_PRIORITY = 5     # middling, and deliberately not 0: the plain child's
                        # expected value must not be a number the parent could
                        # have handed down, or inheritance and the literal 0
                        # would be indistinguishable.
EXPLICIT_PRIORITY = 7   # and not 5 either, for the same reason in reverse.
CHILD_MS = 200


def _result(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


@pytest.fixture(scope="module")
def spawned(cleat, child_priority_workflow):
    """One parent at PARENT_PRIORITY, two children, both run IDs read back.

    Module-scoped: the three assertions below are about one spawn, and starting
    a parent per test would triple the wait for no additional evidence.
    """
    tag = uuid.uuid4().hex[:6]
    status, started = cleat.start(
        child_priority_workflow,
        {"tag": tag, "childMs": CHILD_MS, "explicitPriority": EXPLICIT_PRIORITY},
        priority=PARENT_PRIORITY,
    )
    assert status == 201, f"start rejected: {status} {started}"
    parent_id = started["id"]

    final = cleat.await_terminal(parent_id, timeout=120.0)
    assert final["status"] == "done", f"the parent did not complete: {final}"

    ids = _result(final)
    plain = cleat.await_terminal(ids["plain"], timeout=120.0)
    explicit = cleat.await_terminal(ids["explicit"], timeout=120.0)
    return {"parent": final, "plain": plain, "explicit": explicit}


def test_the_parent_kept_the_priority_it_was_started_with(spawned):
    """The control, and it is not ceremony.

    Both assertions below are of the form "the child's priority is NOT the
    parent's". If the parent's own priority were silently dropped -- a start
    that ignored the argument, a default applied over it -- the parent would
    read 0, both children would differ from it for the wrong reason, and both
    tests would pass while measuring nothing about children at all.
    """
    assert spawned["parent"]["priority"] == PARENT_PRIORITY, (
        f"the parent came back at priority {spawned['parent']['priority']}, not the "
        f"{PARENT_PRIORITY} it was started with. Nothing below is evidence about "
        "children until this holds -- the child assertions are both comparisons "
        "against this number."
    )


def test_a_child_started_without_options_gets_priority_zero(spawned):
    """The plain path, and the assertion the comment does not make.

    `engine/children.go:16` passes a literal 0. Asserted as `== 0` rather than
    `!= PARENT_PRIORITY`, because the weaker form passes for a child that
    inherited nothing and got any arbitrary value -- 3, or the tenant default,
    or whatever a future change substitutes -- while the behaviour that makes
    this worth documenting is specifically that children outrank everything.
    """
    got = spawned["plain"]["priority"]
    assert got == 0, (
        f"a child started through the no-options ChildWorkflow path came back at "
        f"priority {got}, not 0. The parent was started at {PARENT_PRIORITY}. "
        f"If this is {PARENT_PRIORITY} the child inherited, which "
        "cleat/runtime_children.go:22-25 says it must not; if it is anything else "
        "then engine/children.go:16 no longer passes a literal 0 and the "
        "documented 'children outrank their parent's peers' consequence has "
        "changed with it."
    )


def test_an_explicit_child_priority_is_carried_through(spawned):
    """The other half: the field is not merely accepted, it arrives.

    Without this, the test above is consistent with `Priority` being ignored
    entirely on the child path -- every child would read 0, including one asked
    for 7, and the plain-path assertion would still pass.
    """
    got = spawned["explicit"]["priority"]
    assert got == EXPLICIT_PRIORITY, (
        f"a child started with ChildWorkflowOptions{{Priority: {EXPLICIT_PRIORITY}}} "
        f"came back at priority {got}. At 0 the option is being dropped between "
        "cleat.ChildWorkflowOptions and the workflow_instances row, which would "
        "also make the plain-path test above pass for the wrong reason."
    )
