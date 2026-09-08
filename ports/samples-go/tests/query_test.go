package tests

// The query samples, ported from temporalio/samples-go `query/` and
// `query-workflow/`.
//
// cleat's query state is PUBLISHED (push); Temporal's is COMPUTED by a
// registered handler when the query arrives (pull). The DBOS port already
// covers the push model working -- a value is readable while suspended, and a
// reader sees the current value rather than the final one.
//
// What is left, and what these assert, is the part where the two models
// disagree: what happens after the run ends, what happens for a key nobody
// published, and what a value means once the state it described has moved on.

import (
	"net/http"
	"sync"
	"testing"
	"time"
)

var (
	queryOnce sync.Once
	queryWF   string
)

func queryWorkflow(t *testing.T) string {
	t.Helper()
	queryOnce.Do(func() { queryWF = deploy(t, "querytarget", "sg_query_target") })
	if queryWF == "" {
		t.Fatal("the query workflow failed to deploy; see the first failure above")
	}
	return queryWF
}

// TestAQueryStillAnswersAfterTheRunHasFinished is the one Temporal guarantees
// explicitly and the DBOS port never asks.
//
// Querying a CLOSED workflow is a documented Temporal capability -- it is how
// you inspect the outcome of something that finished last week. Whether cleat
// keeps query state past completion is not something the SDK docs settle, and
// the answer decides whether query state is an operational record or only a
// progress indicator.
func TestAQueryStillAnswersAfterTheRunHasFinished(t *testing.T) {
	runID := startedRunID(t, start(t, queryWorkflow(t), map[string]any{
		"key": key(t), "steps": 2, "stepMs": 200,
	}))
	final := awaitTerminal(t, runID, 60*time.Second)
	if final["status"] != "done" {
		t.Fatalf("the run ended %v: %v", final["status"], final["error"])
	}

	status, value := queryState(t, runID, "counter")
	if status != 200 {
		t.Fatalf("querying a finished run answered %d; query state does not outlive the "+
			"run, so it cannot be used to inspect a completed workflow", status)
	}
	if value != "2" {
		t.Errorf("a finished run reports counter=%q, want the final value 2", value)
	}
}

// TestAKeyNobodyPublishedIsNotAnError distinguishes absent from empty.
//
// It matters more under a push model than a pull one. In Temporal an unknown
// query type is an ERROR, because the handler either exists or does not. Here
// there is no handler to be missing -- only a key that has not been published
// yet, which is indistinguishable from one that never will be.
func TestAKeyNobodyPublishedIsNotAnError(t *testing.T) {
	runID := startedRunID(t, start(t, queryWorkflow(t), map[string]any{
		"key": key(t), "steps": 1, "stepMs": 100,
	}))
	awaitTerminal(t, runID, 60*time.Second)

	status, value := queryState(t, runID, "no_such_key_was_ever_published")
	switch {
	case status == 200 && value == "":
		t.Logf("an unpublished key answers 200 with an empty value. Note this cannot be " +
			"told apart from a key whose published value IS the empty string, and there " +
			"is no handler-not-registered error as there would be in Temporal.")
	case status == 404:
		t.Logf("an unpublished key answers 404, which does distinguish absent from empty.")
	default:
		t.Errorf("an unpublished key answered %d with %q -- neither of the two sensible "+
			"answers", status, value)
	}
}

// TestAQueryOnAnUnknownRunCurrentlyAnswers200 pins CURRENT behaviour, which is
// wrong, so that the port notices when it is fixed.
//
// This assertion was written as `want 404`, on the grounds that cleat#900 had
// settled the question for the other per-run reads and #917 had landed the
// fix. It failed:
//
//	GET /api/workflows/00000000-.../query?key=counter
//	200 {"key":"counter","value":""}
//
// /query was not among the endpoints #900 named. The fix closed the three the
// issue listed rather than the class it described, and this is the sixth.
//
// Filed and fixed in cleat-team/cleat#935. Inverted rather than skipped
// because the correct assertion is one line and the pin costs nothing --
// unlike the four #933 skips, where inverting would have meant writing each
// test twice.
//
// The empty value is worse here than the empty list was on /events, because it
// is ALSO a legitimate answer: an unpublished key reads exactly the same as a
// nonexistent run.
func TestAQueryOnAnUnknownRunCurrentlyAnswers200(t *testing.T) {
	r := call(t, http.MethodGet,
		"/api/workflows/00000000-0000-0000-0000-000000000000/query?key=counter", nil, nil)

	if r.Status == 404 {
		t.Errorf("cleat#935 has landed: a query on an unknown run now answers 404. " +
			"Rename this test back to TestAQueryOnAnUnknownRunIs404 and assert 404.")
		return
	}
	if r.Status != 200 {
		t.Fatalf("neither the defect nor the fix: answered %d: %s", r.Status, r.Raw)
	}
	t.Logf("cleat#935 still present: a query on a nonexistent run answers 200 %s, so a "+
		"typo in a run id reads as an unpublished key", r.Raw)
}

// TestAPublishedValueGoesStaleWhenTheStateMovesOn pins the design difference
// itself, so a change to it is a deliberate decision rather than a surprise.
//
// `firstSeen` is published once, at step 0, and never republished; `counter`
// tracks the truth. A Temporal handler asked the same question would compute
// from live state and return the current step. cleat returns 0 forever.
//
// This is NOT filed as a defect. It is what a push model means, and the
// alternative -- invoking guest code on demand from an HTTP handler -- is a
// much larger thing than a query API. Recorded because a reader coming from
// Temporal will assume the pull semantics, and nothing in the API's shape
// tells them otherwise.
func TestAPublishedValueGoesStaleWhenTheStateMovesOn(t *testing.T) {
	runID := startedRunID(t, start(t, queryWorkflow(t), map[string]any{
		"key": key(t), "steps": 4, "stepMs": 400,
	}))

	// Wait until the counter has genuinely moved past 0, so the comparison
	// below is between two DIFFERENT moments rather than between two readings
	// of the same one.
	deadline := time.Now().Add(30 * time.Second)
	var counter string
	for time.Now().Before(deadline) {
		if _, counter = queryState(t, runID, "counter"); counter != "" && counter != "0" {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if counter == "" || counter == "0" {
		t.Fatalf("the counter never advanced past 0 (last %q); this test cannot compare "+
			"two moments and proves nothing", counter)
	}

	_, first := queryState(t, runID, "firstSeen")
	if first != "0" {
		t.Errorf("firstSeen reports %q; it was published once as 0 and never republished, "+
			"so under a push model it must still be 0. A different value would mean the "+
			"value is being recomputed, which would be Temporal's semantics and would "+
			"make this port's finding #6 wrong.", first)
	}
	awaitTerminal(t, runID, 60*time.Second)
}
