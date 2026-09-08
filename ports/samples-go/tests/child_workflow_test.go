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

// TestAnUnrecognisedPolicyMeansDifferentThingsOnDifferentDialects is two
// findings that were only visible together.
//
// THE VALIDATION GAP. enforceParentClosePolicy matches exact string literals
// and ABANDON has no arm -- it is the ABSENCE of an update -- so a value that
// is not one of the recognised spellings silently means ABANDON.
// ParentClosePolicy is a string type, so the typed constants are easy to
// bypass, and the column DEFAULTs to 'ABANDON', so a wrong value and a missing
// one are indistinguishable afterwards.
//
// THE DIVERGENCE, cleat-team/cleat#936. String equality is collation
// dependent, and the dialects disagree:
//
//	mysql>      SELECT 'terminate' = 'TERMINATE';   1     (utf8mb4_0900_ai_ci)
//	postgres=#  SELECT 'terminate' = 'TERMINATE';   f
//
// So the same workflow with the same policy string TERMINATES its children on
// MySQL and ABANDONS them on PostgreSQL. Nothing in the workflow, the metadata
// or the logs differs.
//
// The two mask each other, which is why this test is dialect-aware rather than
// asserting one answer. On MySQL the mis-cased policy "works", so the
// validation gap is invisible; on PostgreSQL it fails open, so the collation
// difference is invisible. Only running both shows either -- and a
// single-dialect version of this test would have reported the other dialect's
// correct-for-itself behaviour as a regression.
func TestAnUnrecognisedPolicyMeansDifferentThingsOnDifferentDialects(t *testing.T) {
	k := key(t)
	parentID, childID := runUnderPolicy(t, k, "terminate", 8000)
	awaitParentCloseWithChildRunning(t, k, parentID)

	child := awaitTerminal(t, childID, 30*time.Second)
	got := fixtureCalls(t, k)
	finished := false
	for _, c := range got {
		if c == "child.Finished" {
			finished = true
		}
	}

	// Case-insensitive collations honour the mis-cased value; case-sensitive
	// ones do not. MySQL and SQL Server default to _ci_ / _CI_; PostgreSQL
	// compares exactly.
	caseInsensitive := dialect() == "mysql" || dialect() == "mssql"

	if caseInsensitive {
		if finished {
			t.Errorf("on %s a mis-cased policy no longer matches TERMINATE: the child ran "+
				"to completion (status %v, calls %v). If the predicate now compares "+
				"case-sensitively, cleat#936 is half-fixed -- check the other dialect "+
				"before updating this test.", dialect(), child["status"], got)
		} else {
			t.Logf("cleat#936 present on %s: policy %q matched TERMINATE through a "+
				"case-insensitive collation; child status %v, calls %v.",
				dialect(), "terminate", child["status"], got)
		}
		return
	}

	if !finished {
		t.Errorf("on %s a mis-cased policy now stops the child (status %v, calls %v). "+
			"Either the policy is being validated or normalised at start -- which would "+
			"close cleat#936 properly -- or the comparison changed. Update this test.",
			dialect(), child["status"], got)
		return
	}
	t.Logf("cleat#936 present on %s: policy %q fell through to ABANDON and the child "+
		"completed; status %v, calls %v.", dialect(), "terminate", child["status"], got)
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
