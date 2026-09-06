"""Promise settlement from another workflow.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS's `set_event`/`get_event` pair lets one workflow publish a value another
waits for. Cleat's promises are the same shape with the roles explicit: a
workflow creates a promise and awaits it, and something else resolves or
rejects it by id.

These tests are the runtime half of cleat#806, which wired `h.ResolvePromise`
and `h.RejectPromise` after finding a public method and a host export with
nothing between them. That fix was verified at the import section of the
compiled binary; this is the part that asks whether settling a promise actually
releases the workflow waiting on it.

The answer is no, and writing them found three separate defects:

- cleat#812 -- the worker never wired the promise store at all, so every
  `CreatePromise` skipped its insert and returned success and every await
  suspended forever. Fixed.
- cleat#813 -- a promise is keyed by the workflow that created it, so no other
  workflow can settle one. A settler child ran to `done` while the parent's row
  stayed `pending`.
- cleat#814 -- an await re-arms its deadline on every wake, so a timeout never
  fires. A 5s timeout was observed at generation 31, three minutes in.

All three are left as skips rather than deleted, because these are the
assertions a reader expects of a promise and their absence would read as
coverage. They are the first tests to exercise promises from Go end to end;
nothing else could, before cleat#806.
"""

import json
import uuid

import pytest

# Long enough that a settling child, which has to be scheduled and run, is not
# racing the timeout -- and short enough that the timeout case does not dominate
# the suite.
TIMEOUT_MS = 20_000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _run(cleat, workflow, mode, timeout_ms=TIMEOUT_MS):
    status, started = cleat.start(workflow, {"mode": mode, "timeoutMs": timeout_ms})
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"run did not complete: {final!r}"
    return _body(final)


@pytest.mark.skip(
    reason="GAP: a promise is keyed by the workflow that created it, so the "
           "settler child writes under its own id and the parent's row stays "
           "pending. The child runs to done and has no effect. cleat#813."
)
def test_a_promise_resolved_by_another_workflow_releases_the_waiter(
    cleat, promise_workflow
):
    body = _run(cleat, promise_workflow, "resolve")

    assert body["outcome"] == "resolved", (
        f"the parent awaited a promise its child resolved and got {body!r}. "
        "Settling a promise must release the workflow waiting on it."
    )
    assert "settled" in body["result"], (
        f"the awaited value did not survive the round trip: {body!r}. "
        "A promise that releases the waiter but loses the value is only half "
        "the mechanism."
    )


@pytest.mark.skip(
    reason="GAP: same scoping defect as the resolve case -- the rejection is "
           "written under the settler's workflow id and never reaches the "
           "waiter. cleat#813."
)
def test_a_rejected_promise_does_not_come_back_as_a_value(cleat, promise_workflow):
    """Rejection must be distinguishable from resolution.

    This is the half that matters more: a waiter told nothing when the thing it
    waits for has failed waits forever, and a waiter told "success" with an
    empty value acts on it.
    """
    body = _run(cleat, promise_workflow, "reject")

    assert body["outcome"] != "resolved", (
        f"a rejected promise came back as a resolved one: {body!r}. The waiter "
        "cannot tell failure from success, which is worse than not being told."
    )
    assert body["outcome"] in ("error", "timedout"), f"unexpected outcome: {body!r}"


@pytest.mark.skip(
    reason="GAP: an await re-arms its deadline on every wake, so the timeout "
           "never fires. Measured: a 5s timeout still ready at generation 31 "
           "three minutes later, burning a worker slot per wake. cleat#814."
)
def test_an_unsettled_promise_times_out(cleat, promise_workflow):
    """The control. Without it the two tests above are not evidence.

    If an await returned immediately regardless, "resolved" would be what a
    never-settled promise looked like too, and neither assertion above would be
    measuring settlement.
    """
    body = _run(cleat, promise_workflow, "timeout", timeout_ms=5_000)

    assert body["outcome"] == "timedout", (
        f"a promise nothing ever settled did not time out: {body!r}. An await "
        "that does not wait makes every other assertion here vacuous."
    )
