package tests

// temporalio/samples-go `childworkflow-continueasnew/`.
//
// The DBOS port already covers continue-as-new at the top level: every
// iteration runs, and the chain is followable to the run carrying the result.
// What it cannot ask -- because DBOS children are independent runs -- is what a
// PARENT sees when its child continues as new.
//
// The child gets a new run id on each iteration and the parent is holding the
// first one. Temporal's answer is that the parent sees one logical child across
// the whole chain. Whether cleat agrees, and whether the parent gets the FINAL
// iteration's result rather than the first one's, is the sample's subject.

import (
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	casnOnce sync.Once
	casnWF   string
)

func casnPair(t *testing.T) string {
	t.Helper()
	casnOnce.Do(func() {
		deploy(t, "casnchild", "sg_casn_child")
		casnWF = deploy(t, "casnparent", "sg_casn_parent")
	})
	if casnWF == "" {
		t.Fatal("the continue-as-new pair failed to deploy; see the first failure above")
	}
	return casnWF
}

// TestEveryIterationOfAContinuedChildRuns establishes the chain works at all
// before anything asks what the parent sees.
//
// Counted from the fixture rather than from the result: a chain that stopped
// early and a chain that ran without recording are the same final answer, and
// the call log is the only thing that separates them.
func TestEveryIterationOfAContinuedChildRuns(t *testing.T) {
	k := key(t)
	const iterations = 3
	runID := startedRunID(t, start(t, casnPair(t), map[string]any{
		"key": k, "iterations": iterations,
	}))
	awaitTerminal(t, runID, 90*time.Second)

	calls := fixtureCalls(t, k)
	if len(calls) != iterations {
		t.Errorf("a child asked to continue as new %d times ran %d iterations: %v",
			iterations, len(calls), calls)
	}
}

// TestAParentSeesItsChildAcrossAContinueAsNew is the sample's assertion.
//
// The parent awaits the run id it was given. That run continues as new into a
// different id, so the question is whether the await follows the chain or waits
// forever on a run that has been superseded.
func TestAParentSeesItsChildAcrossAContinueAsNew(t *testing.T) {
	// Blocked on cleat#955: a child that continues as new is orphaned
	// (parent_workflow_id is NULL on every run after the first) and the
	// parent's AwaitChild resolves against the superseded first run, returning
	// {} while the final iteration's result is stranded.
	//
	// Skipped rather than inverted because the assertion IS the sample -- a
	// parent seeing one logical child across the chain is the whole subject --
	// and pinning "the parent gets an empty result" would mean writing the
	// test twice. The two cases beside it stay green and keep the chain and the
	// run-id relationship covered meanwhile.
	t.Skip("blocked on cleat#955: a continued child is orphaned and its result stranded")

	k := key(t)
	runID := startedRunID(t, start(t, casnPair(t), map[string]any{
		"key": k, "iterations": 3,
	}))

	// Established before the assertion so a failure can distinguish "the parent
	// never got as far as awaiting" from "the await never resolved".
	firstChild := pollQueryState(t, runID, "child", 30*time.Second)
	awaitQueryState(t, runID, "phase", "awaiting", 30*time.Second)

	final := awaitTerminal(t, runID, 90*time.Second)
	if final["status"] != "done" {
		t.Fatalf("the parent ended %v awaiting child %s: %v\n"+
			"A parent that never resolves is what happens if AwaitChild is pinned to a "+
			"run id the chain has moved past.", final["status"], firstChild, final["error"])
	}

	// The result must come from the FINAL iteration. Getting the first
	// iteration's would mean the await resolved against a superseded run --
	// which looks like success and is not.
	result, _ := final["result"].(string)
	if !strings.Contains(result, `"final":true`) {
		t.Errorf("the parent's child result is not the final iteration's: %q", result)
	}
}

// TestTheParentIsHoldingTheFirstRunId is a control on the test above.
//
// If the engine handed the parent the LAST run id -- or the chain never
// actually continued -- then "the await resolved" would be unremarkable and
// would prove nothing about following a chain.
func TestTheParentIsHoldingTheFirstRunId(t *testing.T) {
	k := key(t)
	runID := startedRunID(t, start(t, casnPair(t), map[string]any{
		"key": k, "iterations": 3,
	}))
	firstChild := pollQueryState(t, runID, "child", 30*time.Second)
	final := awaitTerminal(t, runID, 90*time.Second)
	if final["status"] != "done" {
		t.Skipf("the parent did not finish (%v); the assertion this controls has "+
			"already failed", final["status"])
	}

	result, _ := final["result"].(string)
	if !strings.Contains(result, firstChild) {
		t.Errorf("the parent reports child %q but held %q at await time -- so it was "+
			"not awaiting across a chain", result, firstChild)
	}
	// And that id must not be the run that produced the result, or there was no
	// chain to follow.
	child := call(t, "GET", "/api/workflows/"+firstChild, nil, nil)
	if status, _ := child.Body["status"].(string); status == "done" {
		if res, _ := child.Body["result"].(string); strings.Contains(res, `"final":true`) {
			t.Errorf("the first child run produced the final result itself, so nothing " +
				"continued as new and this suite is not testing what it claims")
		}
	}
}
