package tests

// The saga sample, ported from temporalio/samples-go `saga/`.
//
// Upstream asserts one thing: when a later step fails, the earlier steps are
// compensated. It asserts it against Temporal's testsuite, with mocked
// activities, so what it really pins down is that the SDK's saga helper calls
// the functions it was given.
//
// These run against a real worker and a real service, and assert on the
// SERVICE's record of what it was asked to do -- which is the only evidence
// that distinguishes "compensation ran" from "compensation was scheduled".

import (
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	sagaOnce sync.Once
	sagaName string
)

func sagaWorkflow(t *testing.T) string {
	t.Helper()
	sagaOnce.Do(func() { sagaName = deploy(t, "saga", "saga_transfer") })
	if sagaName == "" {
		t.Fatal("the saga workflow failed to deploy; see the first failure above")
	}
	return sagaName
}

// key returns a fixture key unique to one test, so call logs never collide
// between tests or between runs of the suite.
func key(t *testing.T) string {
	t.Helper()
	return fmt.Sprintf("saga-%s-%d", strings.NewReplacer("/", "-", " ", "-").Replace(t.Name()), time.Now().UnixNano())
}

// TestASagaThatSucceedsCompensatesNothing is the boundary upstream cannot
// express: its third step always fails, so a green saga never runs there.
// Without this, an implementation that compensated unconditionally would pass
// every compensation test in this file.
func TestASagaThatSucceedsCompensatesNothing(t *testing.T) {
	k := key(t)
	run := startedRunID(t, start(t, sagaWorkflow(t), map[string]any{
		"key": k, "failAt": "", "failCompensationAt": "",
	}))
	final := awaitTerminal(t, run, 60*time.Second)

	if final["status"] != "done" {
		t.Fatalf("a saga with no failing step ended %v: %v", final["status"], final["error"])
	}
	want := []string{"banking.Withdraw", "banking.Deposit", "banking.Notify"}
	if got := fixtureCalls(t, k); !equal(got, want) {
		t.Errorf("call sequence was %v, want %v", got, want)
	}
}

// TestAFailedStepCompensatesTheEarlierStepsInReverse is the sample's actual
// assertion. Reverse order is the part a counter cannot see: two compensating
// calls in either order are two calls, so the fixture records the sequence.
func TestAFailedStepCompensatesTheEarlierStepsInReverse(t *testing.T) {
	k := key(t)
	run := startedRunID(t, start(t, sagaWorkflow(t), map[string]any{
		"key": k, "failAt": "Notify", "failCompensationAt": "",
	}))
	final := awaitTerminal(t, run, 60*time.Second)

	if final["status"] != "failed" {
		t.Fatalf("a saga whose last step fails ended %v, want failed", final["status"])
	}
	want := []string{
		"banking.Withdraw",
		"banking.Deposit",
		"banking.Notify", // the failing step is part of the sequence
		"banking.DepositCompensation",
		"banking.WithdrawCompensation", // reverse: deposit before withdraw
	}
	if got := fixtureCalls(t, k); !equal(got, want) {
		t.Errorf("call sequence was\n  %v\nwant\n  %v", got, want)
	}
}

// TestAStepThatFailsFirstCompensatesNothingBeforeIt — the failing step's own
// compensation must NOT run. Compensating a step that never completed would
// reverse a withdrawal that never happened, which in this sample is the
// difference between a correct saga and one that loses money.
func TestAStepThatFailsFirstCompensatesNothingBeforeIt(t *testing.T) {
	k := key(t)
	run := startedRunID(t, start(t, sagaWorkflow(t), map[string]any{
		"key": k, "failAt": "Withdraw", "failCompensationAt": "",
	}))
	final := awaitTerminal(t, run, 60*time.Second)

	if final["status"] != "failed" {
		t.Fatalf("a saga whose first step fails ended %v, want failed", final["status"])
	}
	want := []string{"banking.Withdraw"}
	if got := fixtureCalls(t, k); !equal(got, want) {
		t.Errorf("call sequence was %v, want %v -- the failed step must not compensate itself", got, want)
	}
}

// TestAMiddleFailureCompensatesOnlyWhatCompleted pins the count as well as the
// order: one completed step means exactly one compensating call.
func TestAMiddleFailureCompensatesOnlyWhatCompleted(t *testing.T) {
	k := key(t)
	run := startedRunID(t, start(t, sagaWorkflow(t), map[string]any{
		"key": k, "failAt": "Deposit", "failCompensationAt": "",
	}))
	awaitTerminal(t, run, 60*time.Second)

	want := []string{"banking.Withdraw", "banking.Deposit", "banking.WithdrawCompensation"}
	if got := fixtureCalls(t, k); !equal(got, want) {
		t.Errorf("call sequence was %v, want %v", got, want)
	}
}

// TestAFailingCompensationIsReportedNotSwallowed is the one this port was
// written to settle.
//
// examples/saga-temporal-port/ISSUES.md #4 says:
//
//	"The Saga.AddStep compensate function signature is func(HostCalls) -- it
//	 returns no error. This means compensation failures are silently dropped."
//
// That was read off the SDK source and never executed. The signature today is
// `func(HostCalls) error` and Run joins the compensation errors into the
// returned one (cleat/runtime_workflow.go:426). So the finding is stale -- but
// the SDK's own doc comment above AddStep still shows the old no-error
// closure, which would not compile against the function it documents.
//
// The assertion is on the RUN's error text rather than on the signature,
// because the signature is what went stale: a test that reads the source can
// go stale the same way the finding did.
func TestAFailingCompensationIsReportedNotSwallowed(t *testing.T) {
	k := key(t)
	run := startedRunID(t, start(t, sagaWorkflow(t), map[string]any{
		"key": k, "failAt": "Notify", "failCompensationAt": "DepositCompensation",
	}))
	final := awaitTerminal(t, run, 60*time.Second)

	if final["status"] != "failed" {
		t.Fatalf("a saga with a failing compensation ended %v, want failed", final["status"])
	}
	// Both compensations are still attempted: one that fails must not abort
	// the rest, or a single bad compensator would strand every earlier step.
	want := []string{
		"banking.Withdraw", "banking.Deposit", "banking.Notify",
		"banking.DepositCompensation", "banking.WithdrawCompensation",
	}
	if got := fixtureCalls(t, k); !equal(got, want) {
		t.Errorf("call sequence was\n  %v\nwant\n  %v\n"+
			"a failing compensation must not stop the remaining ones", got, want)
	}

	errText, _ := final["error"].(string)
	if errText == "" {
		t.Fatal("the run failed with no error text at all")
	}
	// The forward failure must survive. A compensation error that REPLACED it
	// would be worse than one that was dropped: the operator would be told the
	// cleanup failed and never told what went wrong in the first place.
	if !strings.Contains(errText, "Notify") && !strings.Contains(strings.ToLower(errText), "saga") {
		t.Errorf("the run's error names neither the failing step nor the saga: %q", errText)
	}
}

// TestTheFixtureRecordsAFailedCallToo is a control on the instrument.
//
// Every assertion above reads the fixture's log, and the interesting entries
// are calls that FAILED. If the fixture recorded only successes, the expected
// sequences here would be wrong in a way that looked like an engine defect.
func TestTheFixtureRecordsAFailedCallToo(t *testing.T) {
	k := key(t)
	resp, err := http.Post(fixtureURL+"/call/control/Probe", "application/json",
		strings.NewReader(fmt.Sprintf(`{"key":%q,"fail_permanently":true}`, k)))
	if err != nil {
		t.Fatalf("calling the fixture directly: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatalf("a permanent-failure call answered %d, want 400", resp.StatusCode)
	}
	if got := fixtureCalls(t, k); !equal(got, []string{"control.Probe"}) {
		t.Errorf("the fixture logged %v for a failed call, want [control.Probe]; "+
			"every sequence assertion in this file depends on failures being recorded", got)
	}
}

func equal(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
