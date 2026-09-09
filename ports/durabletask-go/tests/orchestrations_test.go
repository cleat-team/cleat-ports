package tests

// The first two orchestration cases, ported from microsoft/durabletask-go
// `tests/orchestrations_test.go`.
//
// Derived from the upstream assertions, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md.
//
// THESE TWO EXIST TO ESTABLISH THE HARNESS. They are the simplest assertions
// upstream makes, chosen because a first port has to prove the whole path --
// build a WASM workflow, deploy it, start it, read its terminal row -- before
// anything subtle is worth writing. The substantive cases are enumerated in
// README.md with what each needs, and they follow separately.
//
// Workflow names carry a `dtg_` prefix. Every port in a run shares ONE worker
// and one database, so an unprefixed `single_timer` would collide with any
// other port that wanted the same obvious name -- and the collision would
// present as a workflow behaving unlike its own source.

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	emptyOnce sync.Once
	emptyWF   string
	timerOnce sync.Once
	timerWF   string
)

func emptyWorkflow(t *testing.T) string {
	t.Helper()
	emptyOnce.Do(func() { emptyWF = deploy(t, "emptyorch", "dtg_empty_orch") })
	if emptyWF == "" {
		t.Fatal("the empty-orchestration workflow failed to deploy; see the first failure above")
	}
	return emptyWF
}

func timerWorkflow(t *testing.T) string {
	t.Helper()
	timerOnce.Do(func() { timerWF = deploy(t, "singletimer", "dtg_single_timer") })
	if timerWF == "" {
		t.Fatal("the single-timer workflow failed to deploy; see the first failure above")
	}
	return timerWF
}

// key returns a marker unique to one test and one run, so a body that ran with
// another test's input is visible rather than merely wrong. Same shape as the
// samples-go port's helper; the prefix differs so the two never collide in the
// shared fixture log.
func key(t *testing.T) string {
	t.Helper()
	return fmt.Sprintf("dtg-%s-%d",
		strings.NewReplacer("/", "-", " ", "-").Replace(t.Name()), time.Now().UnixNano())
}

func body(t *testing.T, final map[string]any) map[string]any {
	t.Helper()
	raw, ok := final["result"].(string)
	if !ok {
		t.Fatalf("terminal row carries no string result: %#v", final)
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		t.Fatalf("result is not JSON: %v (%q)", err, raw)
	}
	return out
}

// Test_EmptyOrchestration: an orchestration that does no work still completes.
//
// Upstream asserts that "nothing to do" is a normal terminal outcome carrying
// an output, rather than a stall, an error, or a run that never leaves ready.
//
// The marker is what stops this passing vacuously. `status == "done"` alone
// would be satisfied by an engine that completed the run without executing the
// body at all -- which is not a hypothetical failure here, it is precisely
// what a deploy that bound the wrong entry point would look like.
func Test_EmptyOrchestration(t *testing.T) {
	marker := key(t)
	runID := startedRunID(t, start(t, emptyWorkflow(t), map[string]any{"marker": marker, "n": 7}))
	final := awaitTerminal(t, runID, 60*time.Second)

	if got := final["status"]; got != "done" {
		t.Fatalf("status = %v, want done: %#v", got, final)
	}
	b := body(t, final)
	if b["outcome"] != "empty" {
		t.Errorf("outcome = %v, want empty: %#v", b["outcome"], b)
	}
	if b["marker"] != marker {
		t.Errorf("marker = %v, want %q -- the body did not run, or ran with "+
			"another test's input", b["marker"], marker)
	}
}

// Test_SingleTimer: an orchestration whose only step is a durable timer
// completes after the timer fires.
//
// Upstream's subject is that the timer is durable state rather than a parked
// thread. The `resumed` marker is produced AFTER the sleep, so a run that
// returned without waiting could not carry it.
//
// NO WALL-CLOCK ASSERTION. The obvious addition -- that the run took at least
// sleepMs -- would be measuring this machine, and the port's sibling
// (ports/dbos-transact-py/tests/test_replay.py) already covers that the
// virtual clock advances across a sleep. What is asserted here is the thing a
// duration cannot show: that the code after the timer ran.
func Test_SingleTimer(t *testing.T) {
	marker := key(t)
	runID := startedRunID(t, start(t, timerWorkflow(t), map[string]any{
		"marker": marker, "sleepMs": 1000,
	}))
	final := awaitTerminal(t, runID, 90*time.Second)

	if got := final["status"]; got != "done" {
		t.Fatalf("status = %v, want done: %#v", got, final)
	}
	b := body(t, final)
	if b["outcome"] != "resumed" {
		t.Errorf("outcome = %v, want resumed -- the run finished without "+
			"executing the step after the timer: %#v", b["outcome"], b)
	}
	if b["marker"] != marker {
		t.Errorf("marker = %v, want %q", b["marker"], marker)
	}
}
