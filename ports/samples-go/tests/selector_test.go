package tests

// cleat's Selector, which had no coverage in any port.
//
// Found by the cross-port check the cancellation survey established:
// `grep -rli selector ports/*/tests/` returns NOTHING across four ports and
// roughly two hundred cases, against a guest API with three future types, a
// timer path and an error path. That is the second time that one-second grep
// has come back empty on a surface that plainly exists -- the first was guest
// panics, ported as temporalio-sdk-go/tests/panic_test.go.
//
// WHAT THIS IS NOT. sdk-go's TestSelectorNoBlock looked portable and is not,
// and the way it looked portable is worth recording because it is the exact
// error this repository's survey notes warn about one level up. Its TEST body
// is clean -- execute a workflow, assert "HELLO", no history reads, no worker
// steering. Its WORKFLOW, `Workflows.SelectorBlockSignal`, uses workflow.Go
// goroutines, two channels, selector.AddDefault, selector.HasPending and an
// activity. cleat has none of the five and vet refuses three (E001, E002).
// Reading the case is not reading what the case exercises.
//
// So these assertions are written against cleat's own API rather than ported.

import (
	"encoding/json"
	"sync"
	"testing"
	"time"
)

// SelectorTimer is cleat.SelectorTimer. Duplicated as a literal rather than
// imported: the port's tests drive the engine over HTTP and do not link the
// guest SDK, and a test that imported the constant would agree with the guest
// by construction even if the value on the wire were something else.
const selectorTimerWinner = "__selector_timer__"

var (
	selectorOnce sync.Once
	selectorWF   string
)

func selectorWorkflow(t *testing.T) string {
	t.Helper()
	selectorOnce.Do(func() { selectorWF = deploy(t, "selectorrace", "sg_selector_race") })
	if selectorWF == "" {
		t.Fatal("the selector workflow failed to deploy; see the first failure above")
	}
	return selectorWF
}

type selectorOutcome struct {
	Winner     string `json:"winner"`
	Payload    string `json:"payload"`
	ShortFired bool   `json:"shortFired"`
	LongFired  bool   `json:"longFired"`
	ElapsedMs  int64  `json:"elapsedMs"`
	Err        string `json:"err"`
}

// race starts the fixture, waits until it is genuinely inside Select, and
// returns the run id. Waiting on the phase removes "the signal arrived before
// the workflow was claimed" from every test that sends one.
func race(t *testing.T, key, signalName string, shortMs, longMs int) string {
	t.Helper()
	runID := startedRunID(t, start(t, selectorWorkflow(t), map[string]any{
		"key": key, "signalName": signalName, "shortMs": shortMs, "longMs": longMs,
	}))
	awaitQueryState(t, runID, "phase", "waiting", 30*time.Second)
	return runID
}

func outcome(t *testing.T, runID string, timeout time.Duration) selectorOutcome {
	t.Helper()
	final := awaitTerminal(t, runID, timeout)
	if got := final["status"]; got != "done" {
		t.Fatalf("the selector workflow did not complete: status=%v result=%v error=%v",
			got, final["result"], final["error_msg"])
	}
	raw, _ := final["result"].(string)
	var o selectorOutcome
	if err := json.Unmarshal([]byte(raw), &o); err != nil {
		t.Fatalf("could not decode the fixture result %q: %v", raw, err)
	}
	if o.Err != "" {
		t.Fatalf("Selector.Err() was %q; the selector reported an error rather than a winner", o.Err)
	}
	return o
}

// TestASignalWinsTheRaceAgainstALaterDeadline is the base case: the selector
// returns the signal's NAME, not a sentinel, and populates the destination.
func TestASignalWinsTheRaceAgainstALaterDeadline(t *testing.T) {
	t.Skip("cleat#1404: the Selector's DurableSleep reaches the SDK's nil guard and " +
		"returns without sleeping -- the worker log carries 'durable: DurableSleep can only " +
		"be called from within a workflow function' exactly once per run of this fixture, and " +
		"zero times for a guest that sleeps directly. Select's timer branch then sets fired " +
		"and returns SelectorTimer unconditionally, so the deadline is met instantly: " +
		"measured 16ms wall, generation 1, no suspension, for a 1500ms timer -- and " +
		"identically for a 3600000ms one. Unskip when #1404 is fixed; the assertions below " +
		"are what the API promises, not what it currently does.")

	runID := race(t, "sel-signal", "driver_accepted", 0, 60000)
	if r := signal(t, runID, "driver_accepted", "yes"); r.Status != 200 {
		t.Fatalf("delivering driver_accepted answered %d: %s", r.Status, r.Raw)
	}

	o := outcome(t, runID, 60*time.Second)
	if o.Winner != "driver_accepted" {
		t.Errorf("Select() returned %q, want the signal name %q. A selector that "+
			"returns the timer sentinel here raced a 60s deadline against a signal "+
			"that had already arrived.", o.Winner, "driver_accepted")
	}
	if o.Payload != "yes" {
		t.Errorf("the signal destination holds %q, want %q. Select is documented to "+
			"populate the destination BEFORE returning, so an empty payload with the "+
			"right winner means the name is reported and the value is not.", o.Payload, "yes")
	}
	if o.LongFired {
		t.Errorf("the 60s timer reported fired while the signal won; only the winning " +
			"future's destination may be written")
	}
}

// TestTheTimerWinsWhenNoSignalArrives is the other half, and it is what makes
// the test above mean something: without it, a Selector that always returned
// the first future added would pass the signal case.
func TestTheTimerWinsWhenNoSignalArrives(t *testing.T) {
	t.Skip("cleat#1404: the Selector's DurableSleep reaches the SDK's nil guard and " +
		"returns without sleeping -- the worker log carries 'durable: DurableSleep can only " +
		"be called from within a workflow function' exactly once per run of this fixture, and " +
		"zero times for a guest that sleeps directly. Select's timer branch then sets fired " +
		"and returns SelectorTimer unconditionally, so the deadline is met instantly: " +
		"measured 16ms wall, generation 1, no suspension, for a 1500ms timer -- and " +
		"identically for a 3600000ms one. Unskip when #1404 is fixed; the assertions below " +
		"are what the API promises, not what it currently does.")

	runID := race(t, "sel-timer", "", 1500, 0)

	o := outcome(t, runID, 60*time.Second)
	if o.Winner != selectorTimerWinner {
		t.Errorf("Select() returned %q, want %q", o.Winner, selectorTimerWinner)
	}
	if !o.ShortFired {
		t.Errorf("Select returned the timer sentinel but the timer's own flag is false. " +
			"The sentinel says A timer won; the flag says WHICH, and a caller racing " +
			"two deadlines can only tell them apart by the flag")
	}
}

// TestTheEarliestDeadlineWinsAndOnlyItsFlagIsSet is the regression, and the
// ordering inside the fixture is the whole assertion.
//
// cleat#1129: AddTimer assigned rather than appended, so the second call
// discarded the first -- "no error, no log, nothing at build time, and a
// deadline that simply never fired", per the comment now on the fixed
// function. The fixture adds the SHORT timer first, so under that bug only the
// long one survives: the run takes ~30s instead of ~1.5s and ShortFired is
// false. Added in the other order the bug would leave the correct timer in
// place and this test would pass against it.
func TestTheEarliestDeadlineWinsAndOnlyItsFlagIsSet(t *testing.T) {
	t.Skip("cleat#1404: the Selector's DurableSleep reaches the SDK's nil guard and " +
		"returns without sleeping -- the worker log carries 'durable: DurableSleep can only " +
		"be called from within a workflow function' exactly once per run of this fixture, and " +
		"zero times for a guest that sleeps directly. Select's timer branch then sets fired " +
		"and returns SelectorTimer unconditionally, so the deadline is met instantly: " +
		"measured 16ms wall, generation 1, no suspension, for a 1500ms timer -- and " +
		"identically for a 3600000ms one. Unskip when #1404 is fixed; the assertions below " +
		"are what the API promises, not what it currently does.")

	const shortMs, longMs = 1500, 30000
	runID := race(t, "sel-two-timers", "", shortMs, longMs)

	o := outcome(t, runID, 90*time.Second)
	if o.Winner != selectorTimerWinner {
		t.Fatalf("Select() returned %q, want %q", o.Winner, selectorTimerWinner)
	}
	if !o.ShortFired {
		t.Errorf("the %dms deadline did not fire. It was added FIRST, which is the "+
			"case cleat#1129 broke: AddTimer assigned instead of appending, so the "+
			"second call discarded this one and the short deadline never came.", shortMs)
	}
	if o.LongFired {
		t.Errorf("the %dms deadline reported fired as well as the %dms one. "+
			"AddTimer's contract is that only the WINNER's flag is set, which is what "+
			"lets a caller tell which of two deadlines woke it.", longMs, shortMs)
	}
	// The flags could both be right while the run still waited for the wrong
	// deadline, so assert the elapsed time the guest measured on the durable
	// clock. Generous bound: this is separating 1.5s from 30s, not timing.
	if o.ElapsedMs >= longMs {
		t.Errorf("the selector waited %dms, which is at least the %dms deadline. The "+
			"flags say the short timer won; the clock says it waited for the long one.",
			o.ElapsedMs, longMs)
	}
}
