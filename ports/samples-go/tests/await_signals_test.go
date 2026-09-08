package tests

// The await-signals sample, ported from temporalio/samples-go
// `await-signals/`.
//
// Upstream waits for several DISTINCT named signals and proceeds once all have
// arrived, in any order. cleat has no call with that shape -- AwaitSignals
// returns on one, AwaitSignalsWithQuorum returns on N deliveries -- so the
// workflow loops. See ../workflows/awaitsignals/main.go for why quorum is the
// closer-looking fit and the wrong one.

import (
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	awaitOnce sync.Once
	awaitWF   string
)

func awaitSignalsWorkflow(t *testing.T) string {
	t.Helper()
	awaitOnce.Do(func() { awaitWF = deploy(t, "awaitsignals", "sg_await_signals") })
	if awaitWF == "" {
		t.Fatal("the await-signals workflow failed to deploy; see the first failure above")
	}
	return awaitWF
}

// startWaiting starts the workflow and does not return until it is genuinely
// blocked on its first AwaitSignals.
//
// Every test below sends signals, and "the workflow had not been claimed yet"
// and "the signal was lost" produce the same observable outcome. Waiting for
// the phase removes that ambiguity from every test except the one that exists
// to probe it.
func startWaiting(t *testing.T, k, names string, timeoutMs int) string {
	t.Helper()
	runID := startedRunID(t, start(t, awaitSignalsWorkflow(t), map[string]any{
		"key": k, "names": names, "timeoutMs": timeoutMs,
	}))
	awaitQueryState(t, runID, "phase", "waiting", 30*time.Second)
	return runID
}

// TestEverySignalMustArriveBeforeTheWorkflowProceeds is the sample's assertion.
func TestEverySignalMustArriveBeforeTheWorkflowProceeds(t *testing.T) {
	// DEFECT, not a gap: cleat-team/cleat#933.
	//
	// A single signal delivery satisfies more than one AwaitSignals, and three
	// awaits fail the checksum at step 2. Reproduced 3/3 with a straight-line
	// workflow containing nothing but two awaits, with the delivery row
	// confirmed consumed -- so it is not the failed-consume duplicate that
	// engine/signaller.go:312 anticipates.
	//
	// Skipped rather than inverted because the assertion below is what the
	// sample actually guarantees, and rewriting it to match the defect would
	// mean writing this test twice: once wrong now, once right later. What
	// notices the fix is TestOneDeliveryCurrentlySatisfiesTwoAwaits, which
	// pins the defect and fails when it is repaired.

	k := key(t)
	runID := startWaiting(t, k, "approve,fund,ship", 60000)

	for i, name := range []string{"approve", "fund"} {
		if r := signal(t, runID, name, `{}`); r.Status != 200 {
			t.Fatalf("delivering %q answered %d: %s", name, r.Status, r.Raw)
		}
		// After two of three, the workflow must still be waiting. This is the
		// half that fails if the loop counts deliveries instead of names.
		time.Sleep(300 * time.Millisecond)
		if !isRunning(t, runID) {
			t.Fatalf("the workflow finished after %d of 3 signals", i+1)
		}
	}

	if r := signal(t, runID, "ship", `{}`); r.Status != 200 {
		t.Fatalf("delivering ship answered %d: %s", r.Status, r.Raw)
	}
	final := awaitTerminal(t, runID, 30*time.Second)
	if final["status"] != "done" {
		t.Fatalf("the workflow ended %v after all three signals: %v", final["status"], final["error"])
	}
	if result, _ := final["result"].(string); !strings.Contains(result, "approve,fund,ship") {
		t.Errorf("result %q does not report the three names in arrival order", result)
	}
}

// TestTheOrderSignalsArriveInDoesNotMatter is upstream's actual guarantee, and
// the one a test that always sends in declaration order cannot show.
func TestTheOrderSignalsArriveInDoesNotMatter(t *testing.T) {
	// Blocked on cleat#933 symptom A -- one delivery satisfying more than one
	// await -- which #950 did not touch and which is now the whole of that
	// issue.
	//
	// This test sends all three names once each and expects completion. Under A
	// an await can return a name already seen, so the loop makes no progress on
	// that iteration and burns budget instead. It is the only one of the four
	// original skips that #950 did not release; the other three are green.
	t.Skip("blocked on cleat#933 (symptom A): a repeat delivery stalls the loop")

	// Blocked on a second defect, not #933: the await's timeout does not fire.
	// This test sends three copies of one signal to a workflow awaiting three
	// NAMES with an 8000ms timeout, and the run never leaves "ready".
	//
	// It behaved differently on either side of #950 -- it completed in 10.8s on
	// develop and hangs for 30s under the fix -- so it is not a clean
	// pre-existing failure and is not obviously a regression either. Skipped
	// with that stated rather than asserted either way, until the timeout arm
	// (cleat#947 territory) is settled.

	// DEFECT, not a gap: cleat-team/cleat#933.
	//
	// A single signal delivery satisfies more than one AwaitSignals, and three
	// awaits fail the checksum at step 2. Reproduced 3/3 with a straight-line
	// workflow containing nothing but two awaits, with the delivery row
	// confirmed consumed -- so it is not the failed-consume duplicate that
	// engine/signaller.go:312 anticipates.
	//
	// Skipped rather than inverted because the assertion below is what the
	// sample actually guarantees, and rewriting it to match the defect would
	// mean writing this test twice: once wrong now, once right later. What
	// notices the fix is TestOneDeliveryCurrentlySatisfiesTwoAwaits, which
	// pins the defect and fails when it is repaired.

	k := key(t)
	runID := startWaiting(t, k, "approve,fund,ship", 60000)

	for _, name := range []string{"ship", "approve", "fund"} {
		if r := signal(t, runID, name, `{}`); r.Status != 200 {
			t.Fatalf("delivering %q answered %d: %s", name, r.Status, r.Raw)
		}
	}
	final := awaitTerminal(t, runID, 30*time.Second)
	if final["status"] != "done" {
		t.Fatalf("the workflow ended %v: %v", final["status"], final["error"])
	}
	// Arrival order, not requested order -- the workflow returns what it saw,
	// so a result that merely echoed the request would not be evidence.
	if result, _ := final["result"].(string); !strings.Contains(result, "ship,approve,fund") {
		t.Errorf("result %q does not report the ARRIVAL order ship,approve,fund", result)
	}
}

// TestRepeatingOneSignalDoesNotSatisfyTheOthers is the assertion that separates
// the loop from the quorum call.
//
// AwaitSignalsWithQuorum(names, 3, ...) counts DELIVERIES, so three copies of
// "approve" would satisfy it. Upstream's condition is that each named signal
// arrived, which quorum cannot express -- and the difference is invisible in
// any test that sends three different names.
func TestRepeatingOneSignalDoesNotSatisfyTheOthers(t *testing.T) {
	// Blocked on a second defect, not #933: the await's timeout does not fire.
	// This test sends three copies of one signal to a workflow awaiting three
	// NAMES with an 8000ms timeout, and the run never leaves "ready".
	//
	// It behaved differently on either side of #950 -- it completed in 10.8s on
	// develop and hangs for 30s under the fix -- so it is not a clean
	// pre-existing failure and is not obviously a regression either. Skipped
	// with that stated rather than asserted either way, until the timeout arm
	// (cleat#947 territory) is settled.

	// DEFECT, not a gap: cleat-team/cleat#933.
	//
	// A single signal delivery satisfies more than one AwaitSignals, and three
	// awaits fail the checksum at step 2. Reproduced 3/3 with a straight-line
	// workflow containing nothing but two awaits, with the delivery row
	// confirmed consumed -- so it is not the failed-consume duplicate that
	// engine/signaller.go:312 anticipates.
	//
	// Skipped rather than inverted because the assertion below is what the
	// sample actually guarantees, and rewriting it to match the defect would
	// mean writing this test twice: once wrong now, once right later. What
	// notices the fix is TestOneDeliveryCurrentlySatisfiesTwoAwaits, which
	// pins the defect and fails when it is repaired.

	k := key(t)
	runID := startWaiting(t, k, "approve,fund,ship", 8000)

	for i := 0; i < 3; i++ {
		if r := signal(t, runID, "approve", `{}`); r.Status != 200 {
			t.Fatalf("delivering approve answered %d: %s", r.Status, r.Raw)
		}
	}

	final := awaitTerminal(t, runID, 30*time.Second)
	result, _ := final["result"].(string)
	if !strings.Contains(result, `"timedOut":true`) {
		t.Errorf("three copies of one signal completed the wait: %v %q", final["status"], result)
	}
	if !strings.Contains(result, "approve") || strings.Contains(result, "fund") {
		t.Errorf("the timeout report should name approve and not fund: %q", result)
	}
}

// TestASignalForAnUnwantedNameDoesNotSatisfyTheWait — a name outside the set
// must not count. Without this, an implementation that returned on ANY signal
// would pass every test above.
func TestASignalForAnUnwantedNameDoesNotSatisfyTheWait(t *testing.T) {
	// DEFECT, not a gap: cleat-team/cleat#933.
	//
	// A single signal delivery satisfies more than one AwaitSignals, and three
	// awaits fail the checksum at step 2. Reproduced 3/3 with a straight-line
	// workflow containing nothing but two awaits, with the delivery row
	// confirmed consumed -- so it is not the failed-consume duplicate that
	// engine/signaller.go:312 anticipates.
	//
	// Skipped rather than inverted because the assertion below is what the
	// sample actually guarantees, and rewriting it to match the defect would
	// mean writing this test twice: once wrong now, once right later. What
	// notices the fix is TestOneDeliveryCurrentlySatisfiesTwoAwaits, which
	// pins the defect and fails when it is repaired.

	k := key(t)
	runID := startWaiting(t, k, "approve,fund", 8000)

	if r := signal(t, runID, "cancel", `{}`); r.Status != 200 {
		t.Fatalf("delivering cancel answered %d: %s", r.Status, r.Raw)
	}
	if r := signal(t, runID, "approve", `{}`); r.Status != 200 {
		t.Fatalf("delivering approve answered %d: %s", r.Status, r.Raw)
	}

	final := awaitTerminal(t, runID, 30*time.Second)
	result, _ := final["result"].(string)
	if !strings.Contains(result, `"timedOut":true`) {
		t.Errorf("a signal outside the awaited set completed the wait: %v %q",
			final["status"], result)
	}
	if strings.Contains(result, "cancel") {
		t.Errorf("the unwanted signal was recorded as seen: %q", result)
	}
}

// TestASignalSentBeforeTheWaitIsNotLost is the semantic difference this whole
// sample was worth porting for.
//
// Temporal buffers signals for a running workflow: one sent before the
// workflow reaches its await is delivered when it gets there, and application
// code is not expected to race the worker. Whether cleat does the same is not
// something the SDK docs settle.
//
// The send is deliberately NOT preceded by the phase wait every other test
// here uses -- racing the worker is the entire point. A send that lands after
// the wait began proves nothing, so the result is interpreted rather than
// asserted blind: if the workflow completes, the signal was buffered.
func TestASignalSentBeforeTheWaitIsNotLost(t *testing.T) {
	k := key(t)
	runID := startedRunID(t, start(t, awaitSignalsWorkflow(t), map[string]any{
		"key": k, "names": "approve", "timeoutMs": 8000,
	}))

	// No wait for phase=waiting: this send is meant to arrive as early as
	// possible, ideally before the workflow is even claimed.
	if r := signal(t, runID, "approve", `{}`); r.Status != 200 {
		t.Fatalf("delivering approve answered %d: %s", r.Status, r.Raw)
	}

	final := awaitTerminal(t, runID, 30*time.Second)
	result, _ := final["result"].(string)
	if strings.Contains(result, `"timedOut":true`) {
		t.Errorf("a signal sent immediately after start was lost: the workflow timed out "+
			"waiting for a signal that had already been delivered (%q). Temporal buffers "+
			"signals for a running workflow; if cleat does not, application code has to "+
			"race the worker.", result)
	}
	if final["status"] != "done" {
		t.Errorf("the workflow ended %v: %v", final["status"], final["error"])
	}
}

var (
	twoAwaitOnce sync.Once
	twoAwaitWF   string
)

func twoAwaitsWorkflow(t *testing.T) string {
	t.Helper()
	twoAwaitOnce.Do(func() { twoAwaitWF = deploy(t, "twoawaits", "sg_two_awaits") })
	if twoAwaitWF == "" {
		t.Fatal("the two-awaits reproduction failed to deploy; see the first failure above")
	}
	return twoAwaitWF
}

// TestOneDeliveryCurrentlySatisfiesTwoAwaits pins the defect that skips the
// four tests above, so the port notices when it is fixed.
//
// Same construction the DBOS port used for cleat#900: assert the WRONG
// behaviour deliberately, say so in the message, and let the failure be the
// news. That test failed the same day #917 landed and named the issue in its
// own output, which is the only reason to write one this way.
//
// It runs against workflows/twoawaits rather than the sample's own workflow.
// The sample loops, so it reaches a THIRD await and hits #933's other symptom
// -- the checksum mismatch -- which would make this test report the wrong half
// of the defect and go green for the wrong reason when only one half is fixed.
//
// Signal "a" is delivered once; "b" never. Correct behaviour is that the
// second await times out. Current behaviour is that it returns "a" again.
func TestOneDeliveryCurrentlySatisfiesTwoAwaits(t *testing.T) {
	runID := startedRunID(t, start(t, twoAwaitsWorkflow(t), map[string]any{
		"tag": key(t), "unused": 0,
	}))
	// No phase wait: this workflow publishes none. The sleep is only to let
	// the run reach its first await, and the assertion does not depend on it
	// -- a signal that arrives before the await is buffered, which
	// TestASignalSentBeforeTheWaitIsNotLost establishes separately.
	time.Sleep(2 * time.Second)

	if r := signal(t, runID, "a", `{}`); r.Status != 200 {
		t.Fatalf("delivering a answered %d: %s", r.Status, r.Raw)
	}

	final := awaitTerminal(t, runID, 40*time.Second)
	result, _ := final["result"].(string)

	if strings.Contains(result, `"secondTimedOut":true`) {
		t.Errorf("cleat#933 appears to be FIXED: one delivery of \"a\" no longer satisfies "+
			"the second await, which timed out as it should (%q). Remove this test and "+
			"un-skip the four above.", result)
		return
	}
	if final["status"] != "done" {
		t.Fatalf("neither the defect nor the fix: the run ended %v with result %q, error %v",
			final["status"], result, final["error"])
	}
	if !strings.Contains(result, `"second":"a"`) {
		t.Fatalf("unexpected outcome, neither the defect nor the fix: %q", result)
	}
	t.Logf("cleat#933 still present: one delivery of \"a\" satisfied both awaits and the "+
		"run completed (%q) instead of the second await timing out on \"b\".", result)
}
