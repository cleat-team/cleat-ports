package tests

// A panicking workflow, ported from temporalio/sdk-go
// `test/integration_test.go::TestPanicFailWorkflow`.
//
// Derived from the upstream assertion, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md.
//
// WHAT UPSTREAM ASSERTS. A workflow panics; the run fails, and the error the
// caller receives contains the panic's own text ("simulated").
//
// WHY THIS ONE IS HERE AND NOT IN ANOTHER PORT. `grep -rli panic ports/*/tests/`
// returns **nothing** across all four ports. A guest panic is about as
// fundamental as engine behaviour gets -- it is what happens when workflow code
// is simply wrong -- and no port asserts anything about it. That absence is why
// this case survived the cross-port check in
// ../../docs/temporalio-sdk-go-cancellation-survey.md's method, applied to the
// 39-case bucket the survey left unread.
//
// WHAT CLEAT DOES, measured before this test was written: `status: "failed"`,
// with the panic text carried through to `error`:
//
//	host: workflow <id>: execution failed: host: export "handle_panic_wf" failed:
//	simulated panic: <marker>
//
// So cleat passes upstream's assertion. This pins it rather than reporting it.

import (
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	panicOnce sync.Once
	panicWF   string
)

func panicWorkflow(t *testing.T) string {
	t.Helper()
	panicOnce.Do(func() { panicWF = deploy(t, "panicwf", "tsg_panic") })
	if panicWF == "" {
		t.Fatal("the shared panicwf deploy failed in an earlier test")
	}
	return panicWF
}

func TestAPanickingWorkflowFailsAndSaysWhat(t *testing.T) {
	wf := panicWorkflow(t)
	marker := fmt.Sprintf("panic-marker-%d", time.Now().UnixNano())

	runID := startedRunID(t, start(t, wf, "", map[string]any{
		"marker": marker, "shouldPanic": 1,
	}))
	final := awaitTerminal(t, runID, 90*time.Second)

	// `failed`, and specifically NOT `dead_lettered`. Those are different
	// outcomes with different operator consequences: a dead-lettered run is
	// retained for someone to re-drive, a failed one is not. cleat reaches the
	// DLQ on retry exhaustion (engine records RetriesExhausted); a panic is not
	// that, and a panic landing there would mean the discriminator had widened.
	const wantStatus = "failed"
	got, _ := final["status"].(string)
	if got != wantStatus {
		t.Fatalf("a panicking workflow settled %q, want %q.\n\n"+
			"`dead_lettered` in particular would be a different claim: that is the "+
			"retry-exhaustion outcome, kept for an operator to re-drive, and a panic is "+
			"not an exhausted retry.\n%#v", got, wantStatus, final)
	}

	errMsg, _ := final["error"].(string)
	if !strings.Contains(errMsg, marker) {
		t.Errorf("the failure reads %q and does not contain the panic's own marker %q.\n\n"+
			"The marker is the discriminator: a generic \"workflow failed\" satisfies the "+
			"status assertion above and tells whoever is debugging nothing. Upstream "+
			"asserts the same property by looking for its own panic text.", errMsg, marker)
	}
}

// The control, and it is not decoration: every assertion above is satisfied by a
// definition that cannot run at all.
//
// This is the lesson from the update port's validator case, applied before the
// fact rather than after. There, "nothing was applied" passed against a handler
// that recorded nothing, because a zero-valued assertion cannot distinguish the
// thing not happening from the detector not working. "The run failed" has the
// same shape: a deploy that produced a broken module, a harness pointed at the
// wrong worker, or an input that binds nothing would all produce it.
//
// Same definition, same start path, one input byte different.
func TestTheSamePanicWorkflowSucceedsWhenItDoesNotPanic(t *testing.T) {
	wf := panicWorkflow(t)
	marker := fmt.Sprintf("no-panic-%d", time.Now().UnixNano())

	runID := startedRunID(t, start(t, wf, "", map[string]any{
		"marker": marker, "shouldPanic": 0,
	}))
	final := awaitTerminal(t, runID, 90*time.Second)

	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the non-panicking branch settled %q, want done.\n\n"+
			"Without this, the case above cannot tell \"panicking fails the run\" from "+
			"\"this definition fails the run\".\n%#v", got, final)
	}
	body := workflowResult(t, final)
	if got, _ := body["marker"].(string); got != marker {
		t.Errorf("the successful run carries marker %q, want %q -- the input did not "+
			"bind, so the panicking case's input may not have bound either: %#v",
			got, marker, body)
	}
}
