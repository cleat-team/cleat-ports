package tests

// What a cancelled workflow may still do, ported from temporalio/sdk-go
// `test/integration_test.go::TestCantStartChildAfterBeingCancelled`.
//
// Derived from the upstream assertion, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md. The whole fifteen-case cancellation cluster is
// scoped in ../../docs/temporalio-sdk-go-cancellation-survey.md; this is the
// only case in it that reaches a property no other port already asserts.
//
// WHAT UPSTREAM ASSERTS. A workflow is cancelled, then tries to start a child.
// The child is never started and the run ends with a `CanceledError`. Temporal
// cancellation is enforced by the server: past the cancel, the workflow cannot
// commit new work.
//
// WHAT CLEAT DOES, AND WHY THIS IS A DIFFERENCE RATHER THAN A GAP. cleat's
// cancellation is COOPERATIVE. `PollCancellation()` tells the guest; the guest
// decides. Nothing in the engine refuses work after a cancel, so the child is
// started and the run ends `done`.
//
// THIS WAS FILED AS A GAP FIRST, AND THE CORRECTION IS WORTH CARRYING. The
// survey claimed cleat had "the analogous machinery" in `stopBeforeNewWork()`.
// It does not: that gate is `deferPhase && !inDeferDrain`
// (engine/durablecalls.go:50), which is the TERMINATE defer phase, and
// termination is a different operation from cancellation. Naming a mechanism
// that exists is not the same as checking it is on the path the case is about.
//
// WHAT IS ALREADY COVERED, so that this case is not a fourth copy of it:
// `ports/dbos-transact-py/tests/test_cancellation.py` asserts that a workflow
// may ignore cancellation and still report `done`. That is "it keeps running".
// This asserts something strictly stronger and untested anywhere — a cancelled
// workflow may commit a **new durable side effect**, a child run that outlives
// the decision to stop it.

import (
	"net/http"
	"sync"
	"testing"
	"time"
)

var (
	cancelChildOnce sync.Once
	cancelChildWF   string
)

func cancelChildWorkflow(t *testing.T) string {
	t.Helper()
	cancelChildOnce.Do(func() { cancelChildWF = deploy(t, "cancelchild", "tsg_cancel_child") })
	if cancelChildWF == "" {
		t.Fatal("the shared cancelchild deploy failed in an earlier test")
	}
	return cancelChildWF
}

// cancelRun asks for cancellation and checks the request was recorded.
//
// The 200 acknowledges that the REQUEST was stored, not that the workflow has
// seen it — cleat#1351 is that no read path shows the difference. So this
// helper deliberately asserts only what the response can support, and the test
// learns whether the workflow saw it from the workflow's own result.
func cancelRun(t *testing.T, runID, reason string) {
	t.Helper()
	r := call(t, http.MethodPost, "/api/workflows/"+runID+"/cancel",
		map[string]any{"reason": reason}, nil)
	if r.Status != http.StatusOK {
		t.Fatalf("cancel answered %d, want 200: %s", r.Status, r.Raw)
	}
	if got, _ := r.Body["status"].(string); got != "cancellation_requested" {
		t.Fatalf("cancel answered status %q, want \"cancellation_requested\": %s", got, r.Raw)
	}
}

func TestACancelledWorkflowMayStillStartAChild(t *testing.T) {
	wf := cancelChildWorkflow(t)
	child := updatesWorkflow(t) // any deployed definition; the child's behaviour is not under test

	runID := startedRunID(t, start(t, wf, "", map[string]any{
		"childDef": child, "slices": 40,
	}))

	// The run must be alive and polling before the cancel, or "it never
	// observed cancellation" would be a statement about timing rather than
	// about cleat. awaitParked is reused from the duplicate-start cases for
	// exactly this: it returns only once a worker has claimed the run and
	// parked it on the sleep this test asked for.
	awaitParked(t, runID, 200*time.Millisecond, 60*time.Second)

	const reason = "port: cancelled, then asked for a child"
	cancelRun(t, runID, reason)

	final := awaitTerminal(t, runID, 90*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the run settled %q, want done.\n\n"+
			"cleat cancellation is cooperative: a workflow that observes it and returns "+
			"normally completes. A different status here means the engine started "+
			"enforcing cancellation, which is a real change and should be decided rather "+
			"than discovered.\n%#v", got, final)
	}

	body := workflowResult(t, final)
	outcome, _ := body["outcome"].(string)

	if outcome == "never-observed-cancellation" {
		// The message deliberately does NOT assert that the cancel was accepted.
		// It was, in any path reaching here legitimately -- cancelRun fatals
		// otherwise -- but a message restating a precondition it did not
		// re-check is a second, quieter copy of an assertion, and this one was
		// measured lying: under a sabotage that removed the cancel entirely it
		// still read "the cancel was accepted".
		t.Fatalf("the workflow ran to the end of its slices without ever seeing a "+
			"cancellation, so this case proved nothing. Either the request did not "+
			"reach the run or PollCancellation never reported it: %#v", body)
	}

	const wantOutcome = "child-started"
	if outcome != wantOutcome {
		t.Errorf("a cancelled workflow asked for a child and got %q, want %q.\n\n"+
			"Upstream asserts the opposite — TestCantStartChildAfterBeingCancelled "+
			"requires the child to be refused — and cleat deliberately permits it, "+
			"because cancellation here is cooperative rather than enforced. If this has "+
			"become a refusal, the divergence closed and the survey's verdict for this "+
			"case needs rewriting: %#v", outcome, wantOutcome, body)
	}

	// The child id is the evidence the side effect actually happened. Without
	// it, "child-started" is only a claim the guest made about itself.
	childID, _ := body["childId"].(string)
	if childID == "" {
		t.Fatalf("the workflow reports %q with no child id, so nothing shows a child run "+
			"exists: %#v", outcome, body)
	}
	r := call(t, http.MethodGet, "/api/workflows/"+childID, nil, nil)
	if r.Status != http.StatusOK {
		t.Errorf("the child %s named by the cancelled parent answers %d, want 200 — the "+
			"parent reported starting a run that cannot be read back: %s",
			childID, r.Status, r.Raw)
	}

	// The reason reached the guest. That is the half of cleat#1351 that WORKS,
	// and pinning it here is what keeps the issue's scope honest: the reason is
	// not lost, it is only unreadable from outside.
	if got, _ := body["reason"].(string); got != reason {
		t.Errorf("the workflow saw cancellation reason %q, want %q -- the reason is "+
			"delivered through PollCancellation even though no API route returns it "+
			"(cleat#1351)", got, reason)
	}
}
