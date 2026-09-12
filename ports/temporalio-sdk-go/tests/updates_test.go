package tests

// Workflow updates, ported from temporalio/sdk-go `test/integration_test.go`'s
// `TestUpdate*` cluster.
//
// Derived from the upstream assertions, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md. The cluster was read case by case in
// ../../docs/temporalio-sdk-go-updates-survey.md, which gives all 27 methods a
// verdict; these are the seven it calls gaps.
//
// WHAT AN UPDATE IS, IN BOTH SYSTEMS. A request/reply call into a RUNNING
// workflow -- the only external interaction that both changes workflow state
// and returns a value to the caller. Upstream's client blocks on a handle;
// cleat answers `202 {"promise_id":...}` and settles that promise later, which
// the caller reads from `GET /api/workflows/:id/promises`.
//
// TWO STRUCTURAL DIFFERENCES DECIDE WHICH CASES SURVIVE, and both are the
// reason a case below looks smaller than its upstream original:
//
//   - **There is no wait stage.** Upstream's `WaitForStage: Accepted |
//     Completed` is what half the cluster turns on. cleat has only pending and
//     settled, so the distinction is not expressible, not merely untested.
//   - **There is no update id.** Upstream addresses a request by an id
//     independent of its name and hands that id to the handler. cleat keys a
//     request by `(workflow_id, update_name)` and gives the handler the payload
//     and nothing else.
//
// WHAT WAS COVERED BEFORE THIS FILE: nothing. `POST /api/workflows/:id/update/
// :name` had never been called from any test in this repository, across three
// ports -- which is why the cluster was picked. The bucketing that found it is
// in the survey.

import (
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	updatesOnce sync.Once
	updatesWF   string
)

func updatesWorkflow(t *testing.T) string {
	t.Helper()
	updatesOnce.Do(func() { updatesWF = deploy(t, "updates", "tsg_updates") })
	if updatesWF == "" {
		t.Fatal("the shared updates deploy failed in an earlier test")
	}
	return updatesWF
}

// startUpdatable starts a run that stays alive long enough to service updates
// and returns its id.
//
// `slices` is generous on purpose. Every case here sends its updates and then
// waits for the RUN to finish so it can read the workflow's own account of what
// happened, and a run that ended before the update arrived would fail with
// "cannot accept updates" -- a true statement about the wrong thing.
func startUpdatable(t *testing.T, slices int) string {
	t.Helper()
	wf := updatesWorkflow(t)
	return startedRunID(t, start(t, wf, "", map[string]any{
		"marker": t.Name(), "slices": slices,
	}))
}

// The round trip. Upstream's TestUpdateBasic sends an update to a running
// workflow and reads the handler's return value back.
//
// Both halves are asserted, and they are different claims: the PROMISE carries
// what the handler returned, and the WORKFLOW RESULT carries the state the
// handler changed. An implementation that ran the handler and dropped its
// return value would pass the second and fail the first; one that answered from
// the request row without running anything would do the reverse.
func TestAnUpdateRunsItsHandlerAndReturnsTheHandlersValue(t *testing.T) {
	runID := startUpdatable(t, 12)

	pid := updatePromiseID(t, sendUpdate(t, runID, "apply_one", map[string]any{"n": 1}))
	p := awaitPromise(t, runID, pid, 60*time.Second)

	if p.Status != "resolved" {
		t.Fatalf("the update settled %q, want resolved: %+v", p.Status, p)
	}
	if !strings.Contains(p.Result, `"handled":"apply_one"`) {
		t.Errorf("the promise carries %q, which does not contain the handler's return "+
			"value. The point of an update over a signal is that the caller gets a "+
			"value back.", p.Result)
	}

	final := awaitTerminal(t, runID, 90*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the run settled %q rather than done: %#v", got, final)
	}
	body := workflowResult(t, final)
	if n, ok := body["applied"].(float64); !ok || n != 1 {
		t.Errorf("the workflow reports applied=%v, want 1 -- the handler's effect on "+
			"workflow state did not survive, or ran more than once across the run's "+
			"replays: %#v", body["applied"], body)
	}
}

// The caller's payload reaches the handler. Not an upstream case on its own --
// upstream gets this for free from typed Args -- and it is here because cleat
// binds the payload as an opaque JSON string, so "the handler ran" and "the
// handler saw what I sent" are separable and only one of them was asserted
// above.
func TestAnUpdatePayloadReachesTheHandler(t *testing.T) {
	runID := startUpdatable(t, 12)

	marker := fmt.Sprintf("payload-%d", time.Now().UnixNano())
	pid := updatePromiseID(t, sendUpdate(t, runID, "echo", map[string]any{"marker": marker}))
	p := awaitPromise(t, runID, pid, 60*time.Second)

	if p.Status != "resolved" {
		t.Fatalf("the echo update settled %q, want resolved: %+v", p.Status, p)
	}
	if !strings.Contains(p.Result, marker) {
		t.Errorf("the handler echoed %q, which does not contain the marker %q that was "+
			"sent. A handler receiving an empty or stale payload would satisfy every "+
			"other assertion in this file.", p.Result, marker)
	}
}

// An update naming a handler that was never registered. Upstream's
// TestUpdateWithNoHandlerRejected and TestUpdateWithWrongHandleRejected both
// assert two things: the caller learns, and the WORKFLOW IS UNHARMED.
//
// cleat differs from upstream on WHERE the rejection happens, and the
// difference is asserted rather than smoothed over: upstream refuses at
// admission, cleat accepts the request (202) and rejects the promise when the
// workflow reaches a dispatch point and finds no handler. Both tell the caller;
// only cleat's answer requires a second read.
func TestAnUpdateWithNoHandlerIsRejectedAndTheRunIsUnharmed(t *testing.T) {
	runID := startUpdatable(t, 12)

	accepted := sendUpdate(t, runID, "no_such_handler", map[string]any{})
	if accepted.Status != http.StatusAccepted {
		t.Fatalf("an update for an unregistered handler answered %d, want 202 -- cleat "+
			"admits it and rejects the promise later, which is the behaviour this case "+
			"pins: %s", accepted.Status, accepted.Raw)
	}
	p := awaitPromise(t, runID, updatePromiseID(t, accepted), 60*time.Second)

	if p.Status != "rejected" {
		t.Fatalf("an update for an unregistered handler settled %q, want rejected. An "+
			"update that is accepted and never settles is the failure mode the whole "+
			"feature exists to prevent: %+v", p.Status, p)
	}
	if !strings.Contains(p.ErrorMsg, "no_such_handler") {
		t.Errorf("the rejection reads %q and does not name the handler that was missing. "+
			"A caller cannot tell a typo from an outage without it.", p.ErrorMsg)
	}

	// Upstream's half that matters as much as the rejection.
	final := awaitTerminal(t, runID, 90*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the run settled %q after an unhandled update, want done -- an update "+
			"nobody can service must not take the workflow down: %#v", got, final)
	}
	body := workflowResult(t, final)
	if n, ok := body["applied"].(float64); !ok || n != 0 {
		t.Errorf("the workflow applied %v updates, want 0: an update with no handler "+
			"reached one anyway: %#v", body["applied"], body)
	}
}

// A validator refuses. Upstream's TestUpdateValidatorRejected asserts the
// caller gets an error and the workflow carries on.
//
// The stronger half, and the one upstream gets from its own architecture rather
// than by asserting: a refused update must change NOTHING. cleat's SDK
// reference says the validator "runs first (read-only), so a request it refuses
// changes nothing and does no durable work" -- and the handler under `guarded`
// appends to the same list every other case counts, so a refusal that still ran
// the handler shows up in the run's own result and not merely in the promise.
// WRITTEN AS A PAIR, AND THE SECOND HALF IS NOT DECORATION. The refusal half
// asserts `applied == 0`, and on its own that is satisfied by a handler which
// records nothing at all -- measured, not supposed: deleting the `applied =
// append(...)` line from `guarded`'s handler left this whole file GREEN. The
// accepted half is the control that makes the zero mean something, and the two
// differ in exactly one input byte.
//
// Separate RUNS rather than separate updates on one run, forced by cleat#1330:
// an update name is consumed permanently by its first use, so `guarded` can be
// sent once per workflow.
func TestAValidatorRefusalChangesNothingAndAnAcceptanceDoes(t *testing.T) {
	t.Run("refused: the caller learns and nothing is applied", func(t *testing.T) {
		runID := startUpdatable(t, 12)

		pid := updatePromiseID(t, sendUpdate(t, runID, "guarded", map[string]any{"reject": true}))
		p := awaitPromise(t, runID, pid, 60*time.Second)

		if p.Status != "rejected" {
			t.Fatalf("a refused update settled %q, want rejected: %+v", p.Status, p)
		}
		if !strings.Contains(p.ErrorMsg, "refused, reject was set") {
			t.Errorf("the rejection reads %q, which is not the validator's own message. A "+
				"generic refusal would be satisfied by a validator that was never called.",
				p.ErrorMsg)
		}

		final := awaitTerminal(t, runID, 90*time.Second)
		if got, _ := final["status"].(string); got != "done" {
			t.Fatalf("the run settled %q after a refused update, want done: %#v", got, final)
		}
		body := workflowResult(t, final)
		if n, ok := body["applied"].(float64); !ok || n != 0 {
			t.Errorf("the workflow applied %v updates, want 0 -- the validator refused and "+
				"the handler ran anyway, so the refusal is not the read-only gate its own "+
				"documentation describes: %#v", body["applied"], body)
		}
	})

	t.Run("accepted: the same handler does record", func(t *testing.T) {
		runID := startUpdatable(t, 12)

		pid := updatePromiseID(t, sendUpdate(t, runID, "guarded", map[string]any{"reject": false}))
		p := awaitPromise(t, runID, pid, 60*time.Second)

		if p.Status != "resolved" {
			t.Fatalf("an update the validator accepts settled %q, want resolved: %+v",
				p.Status, p)
		}

		final := awaitTerminal(t, runID, 90*time.Second)
		body := workflowResult(t, final)
		if n, ok := body["applied"].(float64); !ok || n != 1 {
			t.Fatalf("the workflow applied %v updates, want 1.\n\n"+
				"This is the control for the subtest above: without it, `applied == 0` "+
				"after a refusal is equally consistent with a validator that works and a "+
				"handler that records nothing. Sabotaging the handler to record nothing "+
				"left the refusal half green.", body["applied"])
		}
	})
}

// A handler that fails. Upstream's TestUpdateRejected asserts the caller gets
// the error and the run completes normally.
//
// Distinct from the validator case above by design: a validator refusal is
// meant to change nothing, while a HANDLER failure happens after the handler
// has begun, and cleat records the handler's effects up to the point it
// returned. So this case asserts the run survives and the caller learns, and
// deliberately does NOT assert applied==0 -- that would be asserting a rollback
// cleat does not claim to perform.
func TestAFailingHandlerRejectsTheCallerAndLeavesTheRunHealthy(t *testing.T) {
	runID := startUpdatable(t, 12)

	pid := updatePromiseID(t, sendUpdate(t, runID, "boom", map[string]any{}))
	p := awaitPromise(t, runID, pid, 60*time.Second)

	if p.Status != "rejected" {
		t.Fatalf("a failing handler settled %q, want rejected: %+v", p.Status, p)
	}
	if !strings.Contains(p.ErrorMsg, "failed on purpose") {
		t.Errorf("the rejection reads %q and does not carry the handler's own error. "+
			"Without it the caller cannot tell a broken handler from a missing one.",
			p.ErrorMsg)
	}

	final := awaitTerminal(t, runID, 90*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the run settled %q after a handler error, want done -- a failed update "+
			"must not fail the workflow: %#v", got, final)
	}
}

// Two updates, both applied, in the order they were sent. Upstream's
// TestUpdateOrdering sends the same update twice and asserts the result is 2.
//
// IT CANNOT SEND THE SAME NAME TWICE HERE, and that is the divergence rather
// than a convenience: cleat consumes an update NAME permanently on first use
// (cleat#1330). So this sends two different names and asserts both the count
// and the ORDER, which is the property upstream's counter was standing in for
// and is strictly more than a count can show -- a dispatcher that applied them
// in arrival-independent order would pass on 2 and fail here.
func TestTwoUpdatesAreBothAppliedInTheOrderTheyWereSent(t *testing.T) {
	runID := startUpdatable(t, 14)

	firstPID := updatePromiseID(t, sendUpdate(t, runID, "apply_one", map[string]any{}))
	// Settled before the second is sent. Without this the two are concurrent and
	// "the order they were sent" is not a fact about the system under test.
	if p := awaitPromise(t, runID, firstPID, 60*time.Second); p.Status != "resolved" {
		t.Fatalf("the first update settled %q, want resolved: %+v", p.Status, p)
	}

	secondPID := updatePromiseID(t, sendUpdate(t, runID, "apply_two", map[string]any{}))
	if p := awaitPromise(t, runID, secondPID, 60*time.Second); p.Status != "resolved" {
		t.Fatalf("the second update settled %q, want resolved: %+v", p.Status, p)
	}

	final := awaitTerminal(t, runID, 90*time.Second)
	body := workflowResult(t, final)
	if n, ok := body["applied"].(float64); !ok || n != 2 {
		t.Errorf("the workflow applied %v updates, want 2: %#v", body["applied"], body)
	}

	const wantOrder = "apply_one,apply_two"
	if got, _ := body["order"].(string); got != wantOrder {
		t.Errorf("the handlers ran in order %q, want %q.\n\n"+
			"Order is the half a count cannot show, and it is a real question here: the "+
			"pending queue is read `ORDER BY priority ASC, created_at` on PostgreSQL and "+
			"`ORDER BY created_at` on MySQL and SQL Server, so this is one of the places "+
			"the three dialects could diverge.", got, wantOrder)
	}
}

// The two refusals at admission, which are about the REQUEST rather than the
// handler. Upstream reaches the first through a client error and has no
// equivalent of the second.
//
// One function, two subtests, because neither is worth a file and both are
// statements about what `POST .../update/:name` does before any workflow code
// runs.
func TestAnUpdateIsRefusedForAMissingRunAndForAFinishedOne(t *testing.T) {
	t.Run("a run that never existed is 404", func(t *testing.T) {
		r := sendUpdate(t, "00000000-0000-0000-0000-0000000009e9", "apply_one", map[string]any{})
		if r.Status != http.StatusNotFound {
			t.Errorf("an update for a run that does not exist answered %d, want 404: %s",
				r.Status, r.Raw)
		}
	})

	t.Run("a finished run is 409, not an unsettleable promise", func(t *testing.T) {
		runID := startUpdatable(t, 1)
		final := awaitTerminal(t, runID, 90*time.Second)
		if got, _ := final["status"].(string); got != "done" {
			t.Fatalf("the run settled %q rather than done, so there is nothing to ask "+
				"about a finished run: %#v", got, final)
		}

		r := sendUpdate(t, runID, "apply_one", map[string]any{})
		const wantStatus = http.StatusConflict
		if r.Status != wantStatus {
			t.Fatalf("an update against a finished run answered %d, want %d.\n\n"+
				"This is cleat#910: a terminal workflow has no future segment, so a "+
				"request accepted now can never be delivered and nothing sweeps it up -- "+
				"the caller would hold a promise that provably cannot settle.\n%s",
				r.Status, wantStatus, r.Raw)
		}
		if msg, _ := r.Body["error"].(string); !strings.Contains(msg, "cannot accept updates") {
			t.Errorf("the refusal reads %q; it should say why, not just refuse", msg)
		}
	})
}
