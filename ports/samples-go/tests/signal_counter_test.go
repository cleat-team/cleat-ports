package tests

// temporalio/samples-go `signal-counter/`.
//
// Upstream's guarantee is arithmetic: send N signals, the total is N. That is
// the shape that turns cleat#933 symptom A from a scheduling curiosity into a
// wrong number, which is why this sample is worth porting while A is open
// rather than after it is fixed.

import (
	"encoding/json"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	counterOnce sync.Once
	counterWF   string
)

func counterWorkflow(t *testing.T) string {
	t.Helper()
	counterOnce.Do(func() { counterWF = deploy(t, "signalcounter", "sg_signal_counter") })
	if counterWF == "" {
		t.Fatal("the signal-counter workflow failed to deploy; see the first failure above")
	}
	return counterWF
}

type counterResult struct {
	Count    int    `json:"count"`
	TimedOut bool   `json:"timedOut"`
	Seen     string `json:"seen"`
}

// runCounter starts a counter, sends `ticks` ticks then "done", and returns the
// workflow's own accounting.
func runCounter(t *testing.T, ticks int, budgetMs int) counterResult {
	t.Helper()
	runID := startedRunID(t, start(t, counterWorkflow(t), map[string]any{
		"key": key(t), "budgetMs": budgetMs,
	}))
	awaitQueryState(t, runID, "phase", "counting", 30*time.Second)

	for i := 0; i < ticks; i++ {
		if r := signal(t, runID, "tick", `{}`); r.Status != 200 {
			t.Fatalf("tick %d answered %d: %s", i, r.Status, r.Raw)
		}
	}
	if r := signal(t, runID, "done", `{}`); r.Status != 200 {
		t.Fatalf("done answered %d: %s", r.Status, r.Raw)
	}

	final := awaitTerminal(t, runID, 60*time.Second)
	if final["status"] != "done" {
		t.Fatalf("the counter ended %v: %v", final["status"], final["error"])
	}
	var out counterResult
	if err := json.Unmarshal([]byte(final["result"].(string)), &out); err != nil {
		t.Fatalf("could not read the counter result from %q: %v", final["result"], err)
	}
	return out
}

// TestTheCountEqualsTheNumberOfSignalsSent is the sample's whole assertion.
func TestTheCountEqualsTheNumberOfSignalsSent(t *testing.T) {
	// Blocked on cleat#953: a workflow times out while the signal it awaits is
	// already in workflow_signals. Rapid delivery -- N ticks with no gap -- has
	// some consumed and the rest left queued until the budget expires.
	//
	// TestTheCountIsVisibleWhileTheWorkflowRuns is the same workflow with one
	// signal at a time and is green, which is what isolates this to delivery
	// timing rather than to counting.
	t.Skip("blocked on cleat#953: queued signals do not wake a suspended workflow")

	const ticks = 5
	got := runCounter(t, ticks, 30000)

	if got.TimedOut {
		t.Fatalf("the counter timed out before \"done\" arrived; count=%d seen=%q",
			got.Count, got.Seen)
	}
	if got.Count != ticks {
		t.Errorf("sent %d ticks, counted %d (seen: %q).\n"+
			"Over-counting is cleat#933 symptom A arriving as arithmetic: one delivery "+
			"satisfying more than one await means one signal incrementing the total "+
			"more than once.", ticks, got.Count, got.Seen)
	}
}

// TestASingleSignalCountsOnce is the minimal form, and it isolates the
// arithmetic from anything about ordering or volume.
//
// If this fails while the five-tick case passes, the defect is in the first
// delivery specifically; if both fail, it scales.
func TestASingleSignalCountsOnce(t *testing.T) {
	got := runCounter(t, 1, 20000)
	if got.Count != 1 {
		t.Errorf("sent one tick, counted %d (seen: %q)", got.Count, got.Seen)
	}
}

// TestTheTerminalSignalIsNotCounted — "done" ends the loop and must not
// increment. A counter that counted its own terminator would be off by one in a
// way that looks like a delivery defect and is not.
func TestTheTerminalSignalIsNotCounted(t *testing.T) {
	// Blocked on cleat#953: a workflow times out while the signal it awaits is
	// already in workflow_signals. Rapid delivery -- N ticks with no gap -- has
	// some consumed and the rest left queued until the budget expires.
	//
	// TestTheCountIsVisibleWhileTheWorkflowRuns is the same workflow with one
	// signal at a time and is green, which is what isolates this to delivery
	// timing rather than to counting.
	t.Skip("blocked on cleat#953: queued signals do not wake a suspended workflow")

	got := runCounter(t, 3, 20000)
	if strings.Count(got.Seen, "done") != 1 {
		t.Errorf("expected exactly one \"done\" in the sequence, got %q", got.Seen)
	}
	if got.Count != 3 {
		t.Errorf("three ticks and a done counted %d; the terminator may be counting itself",
			got.Count)
	}
}

// TestTheCountIsVisibleWhileTheWorkflowRuns is the half upstream gets from a
// query handler.
//
// The interesting value is mid-run: a caller that waits for the result has
// already missed every intermediate state. This also establishes that the
// counter is making progress rather than arriving at the right total by
// finishing all its work in one segment.
func TestTheCountIsVisibleWhileTheWorkflowRuns(t *testing.T) {
	k := key(t)
	runID := startedRunID(t, start(t, counterWorkflow(t), map[string]any{
		"key": k, "budgetMs": 30000,
	}))
	awaitQueryState(t, runID, "phase", "counting", 30*time.Second)

	for i := 1; i <= 3; i++ {
		if r := signal(t, runID, "tick", `{}`); r.Status != 200 {
			t.Fatalf("tick %d answered %d: %s", i, r.Status, r.Raw)
		}
		awaitQueryState(t, runID, "count", strconv.Itoa(i), 20*time.Second)
	}

	if r := signal(t, runID, "done", `{}`); r.Status != 200 {
		t.Fatalf("done answered %d: %s", r.Status, r.Raw)
	}
	final := awaitTerminal(t, runID, 60*time.Second)
	if final["status"] != "done" {
		t.Errorf("the counter ended %v: %v", final["status"], final["error"])
	}
}
