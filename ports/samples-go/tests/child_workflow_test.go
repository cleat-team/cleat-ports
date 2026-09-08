package tests

// The child-workflow samples, ported from temporalio/samples-go
// `child-workflow/`.
//
// ParentClosePolicy is the reason this file exists. It is the part of
// Temporal's child model with no DBOS analogue, so the first port could not
// have covered it: DBOS children are independent runs, and "what happens to a
// running child when its parent goes away" is not a question that suite asks.
//
// cleat implements all three arms (engine/store_lifecycle.go:511 and its
// per-dialect twins) and enforces them from ten call sites, including normal
// completion -- so the tests below close the parent by letting it FINISH,
// which needs no admin endpoint and is the path most likely to be taken in
// production.
//
// Every assertion here is on whether the CHILD reached its second fixture
// call, not on the child's final status. A terminated child and a child that
// finished normally can both end up in a terminal state; only "did the second
// call arrive" separates them.

import (
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	childOnce sync.Once
	parentWF  string
)

// childPair deploys the child before the parent.
//
// Order matters: the parent spawns the child BY NAME, so a parent deployed
// against a missing child fails at run time with "start failed" rather than at
// deploy time -- a failure that reads as an engine defect and is not one.
func childPair(t *testing.T) string {
	t.Helper()
	childOnce.Do(func() {
		deploy(t, "childsleeper", "sg_child_sleeper")
		parentWF = deploy(t, "childparent", "sg_child_parent")
	})
	if parentWF == "" {
		t.Fatal("the child-workflow pair failed to deploy; see the first failure above")
	}
	return parentWF
}

// runUnderPolicy starts a parent that closes immediately, leaving its child
// asleep, and returns the child's run id.
//
// childMs is generous on purpose. The child must still be running when the
// parent closes, or an ABANDON child that was going to finish anyway proves
// nothing -- and the TERMINATE case would pass against an engine that does not
// implement TERMINATE at all.
func runUnderPolicy(t *testing.T, k, policy string, childMs int) (parentID, childID string) {
	t.Helper()
	// parentMs only has to be long enough for the child to reach its first
	// fixture call. childMs has to be long enough that the child is still
	// mid-flight when the parent closes -- and that margin is checked below
	// rather than trusted, because trusting it is how the first version of
	// this file reported a TERMINATE defect that did not exist.
	const parentMs = 1500
	parentID = startedRunID(t, start(t, childPair(t), map[string]any{
		"key": k, "policy": policy, "childMs": childMs, "parentMs": parentMs,
	}))
	childID = pollQueryState(t, parentID, "child", 30*time.Second)

	waitForCall(t, k, "child.Started", 30*time.Second)
	if !isRunning(t, parentID) {
		t.Fatalf("the parent closed before the child made its first call; parentMs=%d is "+
			"too small on this machine and nothing below would be measuring the policy",
			parentMs)
	}
	return parentID, childID
}

// awaitParentCloseWithChildRunning waits for the parent to reach a terminal
// status and reports what the child had done AT THAT MOMENT.
//
// This is the fix for the thin margin that made the first version of this file
// wrong. It reported "a TERMINATE child completed anyway" when the child had
// simply finished its own sleep first -- a 500ms gap between the two sleeps,
// which is the defect class ports#30 was opened for: a margin that is generous
// on paper and zero in practice.
//
// A test cannot tell "the policy did not fire" from "the child was already
// finished when it fired" by looking at the end state, because both leave the
// child done. So the ordering is measured instead of assumed, and a child that
// finished too early fails as a HARNESS problem, naming itself as one.
func awaitParentCloseWithChildRunning(t *testing.T, k, parentID string) map[string]any {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if !isRunning(t, parentID) {
			break
		}
		for _, c := range fixtureCalls(t, k) {
			if c == "child.Finished" {
				t.Fatalf("the child finished before its parent closed, so this run cannot "+
					"measure the close policy at all. Widen the gap between childMs and "+
					"parentMs. calls: %v", fixtureCalls(t, k))
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	parent := awaitTerminal(t, parentID, 30*time.Second)
	if parent["status"] != "done" {
		t.Fatalf("the parent ended %v, want done: %v", parent["status"], parent["error"])
	}
	return parent
}

// TestAnAbandonedChildOutlivesItsParent is the default, and the control for
// every other case in this file: if the child could not outlive its parent at
// all, TERMINATE would pass for the wrong reason.
func TestAnAbandonedChildOutlivesItsParent(t *testing.T) {
	k := key(t)
	parentID, childID := runUnderPolicy(t, k, "ABANDON", 8000)
	awaitParentCloseWithChildRunning(t, k, parentID)

	child := awaitTerminal(t, childID, 30*time.Second)
	if child["status"] != "done" {
		t.Errorf("an ABANDON child ended %v, want done: %v", child["status"], child["error"])
	}
	want := []string{"child.Started", "child.Finished"}
	if got := fixtureCalls(t, k); !equal(got, want) {
		t.Errorf("an ABANDON child made %v, want %v -- it must keep running after the parent closes", got, want)
	}
}

// TestATerminateChildIsStoppedWhenItsParentCloses is the sample's assertion.
func TestATerminateChildIsStoppedWhenItsParentCloses(t *testing.T) {
	k := key(t)
	parentID, childID := runUnderPolicy(t, k, "TERMINATE", 8000)
	awaitParentCloseWithChildRunning(t, k, parentID)

	child := awaitTerminal(t, childID, 30*time.Second)
	if child["status"] == "done" {
		t.Errorf("a TERMINATE child completed anyway (status done) after its parent closed")
	}
	// The error message is asserted because it is the evidence of CAUSE. A
	// child that failed for some other reason is a different bug wearing this
	// one's result, and the engine writes exactly this text
	// (engine/store_lifecycle.go:545).
	if msg, _ := child["error"].(string); !strings.Contains(msg, "parent workflow terminated") {
		t.Errorf("a TERMINATE child ended %v with error %q; want an error naming the parent",
			child["status"], msg)
	}
	// The load-bearing half. A status flipped to failed while the child ran on
	// is exactly the defect the generation bump at store_lifecycle.go:520 was
	// added for -- measured 4 runs of 4, every TERMINATE child completing
	// anyway while carrying the message above.
	// child.Started is guaranteed by runUnderPolicy; what must be absent is
	// child.Finished. Asserted as absence rather than as an exact sequence,
	// because a terminated child may also be stopped BEFORE its first call on
	// a slower machine -- which is a stronger result, not a failure.
	for _, c := range fixtureCalls(t, k) {
		if c == "child.Finished" {
			t.Errorf("a TERMINATE child reached child.Finished; it kept running after "+
				"being marked terminated. calls: %v", fixtureCalls(t, k))
		}
	}
}

// TestARequestCancelChildIsAskedToStop covers the third arm.
//
// REQUEST_CANCEL only sets cancellation_requested -- it does not itself end the
// run -- so this asserts the weaker guarantee the name promises, and asserts
// it on the child's own behaviour rather than on the flag: the child must not
// complete normally as though nothing was asked of it.
func TestARequestCancelChildIsAskedToStop(t *testing.T) {
	k := key(t)
	parentID, childID := runUnderPolicy(t, k, "REQUEST_CANCEL", 8000)
	awaitParentCloseWithChildRunning(t, k, parentID)

	child := awaitTerminal(t, childID, 30*time.Second)
	if child["status"] == "done" {
		t.Errorf("a REQUEST_CANCEL child ran to completion (status done); "+
			"cancellation was requested and nothing acted on it. calls: %v",
			fixtureCalls(t, k))
	}
}

// TestAMisCasedPolicyIsRefused is what cleat#936 turned into, and the history
// is the point of the test rather than a footnote.
//
// It began as TestAnUnrecognisedPolicyIsTreatedAsAbandon, pinning a validation
// gap: ABANDON is the ABSENCE of an arm, so an unrecognised policy silently
// meant ABANDON. Running that same test on MySQL failed, and the reason was
// worse than the gap:
//
//	mysql>      SELECT 'terminate' = 'TERMINATE';   1     (utf8mb4_0900_ai_ci)
//	postgres=#  SELECT 'terminate' = 'TERMINATE';   f
//
// The same workflow with the same policy string terminated its children on one
// database and abandoned them on the other. The two defects had masked each
// other -- on MySQL the mis-cased policy "worked", so the gap was invisible; on
// PostgreSQL it fell through, so the collation difference was invisible.
//
// cleat#938 closed both by refusing an unrecognised policy at the write
// boundary rather than fixing the comparison, so the value can no longer reach
// a column where three databases disagree about what it means.
//
// The test is no longer dialect-aware, and that IS the fix: there is nothing
// left for the dialects to disagree about.
func TestAMisCasedPolicyIsRefused(t *testing.T) {
	k := key(t)
	parentID := startedRunID(t, start(t, childPair(t), map[string]any{
		"key": k, "policy": "terminate", "childMs": 8000, "parentMs": 1500,
	}))

	final := awaitTerminal(t, parentID, 30*time.Second)
	if final["status"] != "failed" {
		t.Fatalf("a parent using policy %q ended %v, want failed. If it succeeded, the "+
			"refusal from cleat#938 has been lost and a mis-cased policy is reaching the "+
			"database again -- where MySQL and PostgreSQL disagree about it (cleat#936).",
			"terminate", final["status"])
	}

	// The message must name the value AND the intended spelling. "must be one
	// of ABANDON, TERMINATE, REQUEST_CANCEL" read beside "terminate" is a
	// sentence people skim, which is why the SDK offers the near-miss.
	errText, _ := final["error"].(string)
	for _, want := range []string{"terminate", "TERMINATE", "sg_child_sleeper"} {
		if !strings.Contains(errText, want) {
			t.Errorf("the refusal does not mention %q: %q", want, errText)
		}
	}

	// No child may exist. A refusal that still started the child would be worse
	// than the original defect: a run nobody can see, under a policy nobody
	// agreed on.
	if calls := fixtureCalls(t, k); len(calls) != 0 {
		t.Errorf("the child ran despite the refusal: %v", calls)
	}
}

// TestTheThreeLegalPoliciesAreStillAccepted is the control on the refusal.
//
// Without it, an over-broad validation that rejected every policy would pass
// the test above -- and the three tests before it use ABANDON, TERMINATE and
// REQUEST_CANCEL, so this states as an assertion what they depend on as a
// precondition.
func TestTheThreeLegalPoliciesAreStillAccepted(t *testing.T) {
	for _, policy := range []string{"ABANDON", "TERMINATE", "REQUEST_CANCEL", ""} {
		name := policy
		if name == "" {
			name = "unset"
		}
		t.Run(name, func(t *testing.T) {
			k := key(t)
			parentID := startedRunID(t, start(t, childPair(t), map[string]any{
				"key": k, "policy": policy, "childMs": 300, "parentMs": 0,
			}))
			final := awaitTerminal(t, parentID, 30*time.Second)
			if final["status"] != "done" {
				t.Errorf("policy %q was refused: %v %v", policy, final["status"], final["error"])
			}
		})
	}
}

// TestTheChildIsReachableByIdFromOutsideTheParent is a control on the
// instrument, not on cleat.
//
// Every test above locates the child through the parent's query state. If that
// returned a stale or wrong id, the assertions would be reading some other
// run's status and would mostly still pass -- an unrelated finished run reads
// as "done", which is what two of these tests expect.
func TestTheChildIsReachableByIdFromOutsideTheParent(t *testing.T) {
	k := key(t)
	_, childID := runUnderPolicy(t, k, "ABANDON", 500)

	child := awaitTerminal(t, childID, 30*time.Second)
	result, _ := child["result"].(string)
	if !strings.Contains(result, k) {
		t.Errorf("the run at the id published as query state returned %q, which does not "+
			"carry this test's key %q -- the tests above may be reading the wrong run",
			result, k)
	}
	if id, _ := child["id"].(string); id != "" && id != childID {
		t.Errorf("asked for run %s and got %s", childID, id)
	}
	_ = fmt.Sprint()
}
