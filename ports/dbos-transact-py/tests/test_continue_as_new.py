"""Continue-as-new: a workflow that restarts itself with fresh input.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS uses this to keep a long-running workflow's history bounded -- the point
is that the run ends and a successor begins with the same identity and a
smaller history, rather than one run accumulating events forever.

The assertion is the fixture's call count, not the returned value. Each
iteration announces itself under the same key, so the count is the number of
iterations that actually executed. A returned value cannot make this claim: the
final run's result is identical whether it was the third iteration or the
first, so a chain that silently stopped after one would look exactly like a
complete one.
"""

import json
import time
import uuid

import pytest

from conftest import wait_until

ITERATIONS = 3


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_workflow_can_continue_as_new_and_every_iteration_runs(
    cleat, continue_as_new_workflow, fixture_calls
):
    key = f"can-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(
        continue_as_new_workflow, {"key": key, "remaining": ITERATIONS}
    )
    assert status == 201, f"start rejected: {status} {started}"

    wait_until(
        lambda: fixture_calls(key) >= ITERATIONS,
        timeout=90.0,
        what=f"all {ITERATIONS} iterations to run",
    )

    # Settle, so an extra iteration would be visible rather than merely late.
    time.sleep(2.0)
    assert fixture_calls(key) == ITERATIONS, (
        f"{fixture_calls(key)} iterations ran, expected {ITERATIONS}. More than "
        "asked for means the chain does not terminate; fewer means a link was "
        "dropped and the workflow reported success without doing the work."
    )


def test_the_chain_is_followable_to_the_run_carrying_the_result(
    cleat, continue_as_new_workflow, fixture_calls
):
    """A caller can reach the outcome of a continue-as-new chain.

    This test was skipped as a GAP (cleat#826) and asserted the opposite:
    that the workflow ID survives the transition, as it does in DBOS and
    Temporal. It does not, and that is now a decision rather than an omission.

    What was chosen instead: `GetWorkflowByID` keeps meaning "the row with this
    id", and a separate `GET /api/workflows/{id}/terminal` walks the
    `continued_from` chain forward. Making the existing read follow the chain
    was the other option and was rejected deliberately -- four call sites and
    the admin dashboard would have started receiving a different row, with a
    different id, than they asked for.

    So BOTH halves are asserted, and the first is not a residue:

      - polling the original id still reports done with an empty result,
        because that is what that row honestly contains
      - /terminal from the same id returns the run that carries the result

    A change that made the first line return the successor's result would be
    the rejected option arriving by the back door, and would fail here.
    """
    key = f"can-id-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(continue_as_new_workflow, {"key": key, "remaining": 2})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", f"the chain did not complete: {final!r}"

    # The row the caller named. Its result is empty because a run that
    # continues never returned a value -- correct, and useless on its own.
    body = _body(final)
    assert body == {} or body.get("outcome") != "finished", (
        f"the original run reported a finished outcome: {body!r}. The run that "
        f"finishes is a later one in the chain; this row returning its result "
        f"would mean GetWorkflowByID had started following the chain, which was "
        f"the rejected option."
    )

    # The run that actually finished, reached from the id the caller holds.
    #
    # POLLED, not read once, and the reason is worth stating because the first
    # version of this test got it wrong for a documented reason.
    #
    # /terminal returns the last link recorded SO FAR, which while the chain is
    # still running is the link currently executing: status 'running', empty
    # result. The interface doc shipped in #896 said it returns "the one
    # carrying the result the caller is waiting for", which is false for most of
    # the window in which a caller would call it. This test read .result
    # immediately, believed that sentence, and dereferenced a nil.
    #
    # I first diagnosed that as a timing bug in this test. It is one -- but the
    # reason the timing was surprising is that the method was documented as
    # returning an OUTCOME when it returns a POSITION. WS-3 corrected the doc in
    # three places once this surfaced.
    #
    # The trap underneath it: THE FIRST RUN OF A CHAIN REACHES A TERMINAL STATUS
    # THE INSTANT IT CONTINUES. So await_terminal on the id you started returns
    # almost immediately and says nothing about whether the work finished --
    # which is the whole reason /terminal exists.
    terminal = None
    deadline = time.time() + 90.0
    while time.time() < deadline:
        code, terminal = cleat.api(f"/api/workflows/{started['id']}/terminal")
        assert code == 200, (
            f"/terminal answered {code}: {terminal!r}. This is the endpoint that "
            f"makes a continue-as-new chain retrievable at all (cleat#887)."
        )
        if terminal.get("status") == "done" and terminal.get("result"):
            break
        time.sleep(0.5)
    else:
        pytest.fail(
            f"the chain never reached a run carrying a result within 90s; last "
            f"terminal run was {terminal!r}"
        )
    assert terminal.get("id") != started["id"], (
        f"/terminal returned the run that was asked for rather than the last in "
        f"the chain: {terminal!r}"
    )

    result = terminal.get("result")
    result = json.loads(result) if isinstance(result, str) else result
    assert result.get("outcome") == "finished", (
        f"the terminal run does not carry the finished result: {result!r}"
    )


def test_a_delivered_but_unconsumed_signal_does_not_cross_a_continue_as_new(
        cleat, continue_as_new_signal_workflow, fixture_calls):
    """A signal left unconsumed at the boundary is not visible to the new run.

    Upstream's `Test_ContinueAsNew_Events` carries such events across, behind an
    explicit opt-in — `task.WithKeepUnprocessedEvents()`. cleat has no
    counterpart, so the upstream case is not portable as written. What cleat can
    answer is what happens by default, and nothing here asked.

    **The storage explains the answer and is worth stating, because the test
    would otherwise look like it is hunting a bug.** `workflow_signals` is keyed
    `(workflow_id, signal_name)`, and `ContinueAsNew` mints a NEW run id without
    touching that table — zero mentions of `workflow_signals` inside the
    function, on all three dialects. So the row stays attached to the run that
    has just finished.

    **This asserts cleat's behaviour, not upstream's.** It is a divergence
    nobody has adjudicated: matching upstream's *default* (which also drops
    them) while lacking upstream's opt-in. If cleat ever grows one, this test
    should fail, and that failure is the point.

    **Ordering is the whole fixture.** `carried` is delivered FIRST, while
    iteration one is still parked on `go`. That is what makes it
    already-delivered-and-unconsumed at the boundary rather than a signal that
    simply arrived too late — two situations with the same visible outcome and
    entirely different meanings.

    **The control is built in, and it needs saying, because the obvious way for
    this test to pass for the wrong reason is that signals never arrive at
    all.** A test asserting a timeout is satisfied by a broken delivery path.

    It cannot happen here: reaching iteration two at all requires `go` to have
    been delivered and consumed by iteration one. If the signal path were
    broken, iteration one would time out, return `never-released`, and never
    continue — so `/terminal` would still be the run we started, and the
    `final.get("id") != run_id` assertion below fails first. The path this test
    depends on is exercised by the test itself, one step before the assertion.
    """
    key = f"cansignal-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(continue_as_new_signal_workflow,
                                  {"key": key, "timeoutMs": 8000, "second": 0})
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    wait_until(lambda: fixture_calls(f"{key}-first") >= 1, timeout=60.0,
               what="iteration 1 to reach its await")

    # Delivered while iteration 1 is parked on a DIFFERENT name, so it is
    # pending and unconsumed when the boundary is crossed.
    status, _ = cleat.signal(run_id, "carried", json.dumps({"from": "iteration-1"}))
    assert status in (200, 202), f"delivering `carried` failed: {status}"

    status, _ = cleat.signal(run_id, "go", "{}")
    assert status in (200, 202), f"releasing iteration 1 failed: {status}"

    # The second iteration must actually START, or "no signal seen" would be
    # indistinguishable from "the chain stopped".
    wait_until(lambda: fixture_calls(f"{key}-second") >= 1, timeout=60.0,
               what="iteration 2 to start")

    # NOT await_terminal on the id we started. The first run of a chain reaches
    # a terminal status the INSTANT it continues, so that call returns almost
    # immediately with an empty result and says nothing about the second
    # iteration -- which is what this test is about. That trap is documented at
    # length in test_the_chain_is_followable_to_the_run_carrying_the_result
    # above, and I walked into it anyway: the first version of this test failed
    # with KeyError: 'outcome' on the original run's empty body.
    #
    # /terminal walks `continued_from` forward, and returns the last link
    # recorded SO FAR -- a POSITION, not an outcome -- so it has to be polled
    # until that link is itself done and carrying a result.
    final = None
    deadline = time.time() + 90.0
    while time.time() < deadline:
        code, final = cleat.api(f"/api/workflows/{run_id}/terminal")
        assert code == 200, f"/terminal answered {code}: {final!r}"
        if final.get("status") == "done" and final.get("result"):
            break
        time.sleep(0.5)
    else:
        pytest.fail(f"the chain never reached a run carrying a result: {final!r}")

    assert final.get("id") != run_id, (
        f"/terminal returned the run we asked for rather than the second "
        f"iteration: {final!r}"
    )

    body = _body(final)
    assert body["outcome"] == "timedout", (
        f"iteration 2 reported {body['outcome']!r}: {body}. `carried` means the "
        "signal crossed the boundary — which would be a change in behaviour, "
        "since ContinueAsNew does not touch workflow_signals on any dialect and "
        "the table is keyed by workflow_id."
    )
    assert body["iteration"] == 2, f"the wrong iteration answered: {body}"
