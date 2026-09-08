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
		// Wait for the workflow to actually record the arrival before sending
		// the next one, rather than sleeping a fixed interval and hoping.
		//
		// This was a 300ms sleep, and it made the test measure DELIVERY TIMING
		// instead of its own subject. It passed on PostgreSQL and failed on
		// MySQL every run -- not a dialect defect: sending the next signal
		// before the workflow has suspended again walks into cleat#953, where a
		// signal arriving while the workflow is awake is queued without
		// scheduling a wake. MySQL is slower to come round, so 300ms was enough
		// there and not enough here.
		//
		// The same sequence with 3-second gaps completes correctly on MySQL
		// (order: approve,fund,ship), which is what identified the gap rather
		// than the dialect as the variable.
		//
		// Waiting on the published state removes the interval from the test
		// entirely. #953 keeps its own coverage in signal_counter_test.go,
		// where rapid delivery is the subject rather than an accident.
		awaitQueryState(t, runID, "seen", strings.Join([]string{"approve", "fund"}[:i+1], ","),
			30*time.Second)
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

	// Wait for each arrival to be recorded before sending the next.
	//
	// The subject here is ORDER -- the same three names in a different sequence
	// -- not delivery timing. Sending all three with no gap makes the test
	// depend on cleat#953 instead: a signal arriving while the workflow is
	// still awake handling the previous one is queued without scheduling a
	// wake, and the run sits at `ready` until its budget expires.
	//
	// That is what this was doing. It was skipped as blocked on cleat#933, and
	// when #933 was fixed it kept failing -- because #933 was never what
	// stopped it. Rapid delivery keeps its own coverage in
	// signal_counter_test.go, where it is the subject rather than an accident.
	sent := []string{}
	for _, name := range []string{"ship", "approve", "fund"} {
		if r := signal(t, runID, name, `{}`); r.Status != 200 {
			t.Fatalf("delivering %q answered %d: %s", name, r.Status, r.Raw)
		}
		sent = append(sent, name)
		awaitQueryState(t, runID, "seen", strings.Join(sent, ","), 30*time.Second)
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

// TestOneDeliverySatisfiesExactlyOneAwait was a pin and is now an assertion.
//
// It shipped asserting the WRONG behaviour on purpose -- that one delivery of
// "a" satisfied both awaits -- with its own message saying what its failure
// would mean. It failed when cleat#933 was fixed, printing:
//
//	cleat#933 appears to be FIXED: one delivery of "a" no longer satisfies the
//	second await, which timed out as it should. Remove this test and un-skip
//	the four above.
//
// Fourth time that construction has caught its own obsolescence.
//
// The issue took three shapes before it closed, and the port's measurements
// moved it twice. It began as two symptoms; #950 fixed the checksum half; the
// duplicate then stopped reproducing under #967/#968, leaving a misattribution
// -- the first await reporting a spurious timeout while the delivery landed on
// the second. What located THAT was a column nobody had looked at:
//
//	step | event_type      | created
//	   0 | await_signals   | 13:27:18.964
//	   1 | await_signals   | 13:27:18.964     <- same millisecond
//	   2 | signal_received | 13:27:21.965        three seconds later
//
// Both awaits written before any signal existed, so both were recorded in one
// segment with no history to replay. That moved the fault off the replay arm
// and onto the fresh path, where #974 found it: a suspending await returned a
// value byte-identical to a genuine timeout, the guest read it as one and ran
// on, and the second await recorded into a segment that had already ended.
func TestOneDeliverySatisfiesExactlyOneAwait(t *testing.T) {
	runID := startedRunID(t, start(t, twoAwaitsWorkflow(t), map[string]any{
		"tag": key(t), "unused": 0,
	}))
	time.Sleep(2 * time.Second)

	if r := signal(t, runID, "a", `{}`); r.Status != 200 {
		t.Fatalf("delivering a answered %d: %s", r.Status, r.Raw)
	}

	final := awaitTerminal(t, runID, 40*time.Second)
	result, _ := final["result"].(string)
	if final["status"] != "done" {
		t.Fatalf("the run ended %v: %v", final["status"], final["error"])
	}

	// The FIRST await takes the delivery. Getting it on the second while the
	// first reports a timeout is the misattribution #974 fixed, and it is
	// distinguishable from the older duplicate only by which await timed out.
	if !strings.Contains(result, `"first":"a"`) || !strings.Contains(result, `"firstTimedOut":false`) {
		t.Errorf("the first await did not receive the delivery: %q\n"+
			"A spurious timeout here with the signal landing on the second await is "+
			"cleat#933's misattribution returning.", result)
	}
	// And exactly one: the second must time out, because "b" is never sent.
	if !strings.Contains(result, `"secondTimedOut":true`) {
		t.Errorf("the second await did not time out on \"b\", which was never sent: %q\n"+
			"One delivery satisfying two awaits is cleat#933's original duplicate.",
			result)
	}
}
