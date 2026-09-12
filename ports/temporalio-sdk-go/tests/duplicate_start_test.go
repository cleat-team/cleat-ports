package tests

// What a duplicate start says about the run that won, ported from
// temporalio/sdk-go `test/integration_test.go`'s `TestWorkflowIDReuse*`
// cluster.
//
// Derived from the upstream assertions, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md.
//
// WHAT UPSTREAM ASSERTS. Temporal offers four reuse policies and a separate
// conflict policy, and the cluster walks them: REJECT_DUPLICATE,
// ALLOW_DUPLICATE, ALLOW_DUPLICATE_FAILED_ONLY (twice, once against a winner
// that succeeded and once against one that failed), IGNORE_DUPLICATE_WHILE_
// RUNNING, and TestWorkflowIDConflictPolicy's FAIL / USE_EXISTING /
// TERMINATE_EXISTING.
//
// The half that ports is not the policy selection -- cleat has exactly one
// policy and no knob -- it is the OBSERVATION every one of those cases turns
// on: *the second start is answered with what became of the first run*.
// Upstream reads it out of the error, and the assertion it makes is a string
// prefix on a typed error: `WorkflowExecutionAlreadyStarted` whose message
// begins "Workflow execution already finished". Finished, specifically, rather
// than "already started" -- the winner's OUTCOME is the payload.
//
// cleat carries the same fact in the duplicate response's `status`, alongside
// `error` and `error_code` when the winner failed (cleat#1151). So the three
// arms below are upstream's distinction expressed with the fields cleat has:
// a caller retrying a start it is not sure landed must be able to tell "poll
// this" from "fetch the result" from "this will never succeed".
//
// WHAT WAS ALREADY COVERED, AND WHY THAT IS NOT THIS. cleat core covers all
// four arms in cmd/cleat-worker/duplicate_start_reports_the_outcome_test.go.
// Those are handler tests over a mock store, and the mock decides BOTH facts
// under test: `winnerStore(t, &engine.WorkflowInstance{Status: "failed",
// Error: "downstream refused", ErrorCode: "E_DOWNSTREAM"})` hands the handler
// a winner it invented, and a stub `StartNewRun` decides that the second start
// was a duplicate at all.
//
// That is the right shape for a handler test and it cannot answer the question
// this file asks: whether a REAL key, over a real store, still resolves after
// the run it names has reached each of those states, and whether the values it
// then reports are the run's own. Measured while writing these cases, the
// production engine writes `error_code: "unknown"` for an ordinary workflow
// failure -- so the core test's `E_DOWNSTREAM` is a value no run produces, and
// nothing outside these cases would have said so.
//
// WHAT IS NOT HERE. The fourth arm, `status: "unknown"` for a winner that has
// been deleted, is reachable but only through a defect: dead-letter retention
// deletes the run and leaves the key (cleat#1324, filed from this port). It is
// deliberately not pinned here -- a test asserting today's answer would have to
// be rewritten by the fix, and the fix is the point.

import (
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

// idReuseWorkflow deploys the one workflow all three arms share, once.
//
// One definition rather than three is deliberate: the arms differ only in what
// the winner is DOING when the duplicate arrives, and three definitions would
// leave "the answer differed because the workflow differed" open.
var (
	idReuseOnce sync.Once
	idReuseWF   string
)

func idReuseWorkflow(t *testing.T) string {
	t.Helper()
	idReuseOnce.Do(func() { idReuseWF = deploy(t, "idreuse", "tsg_id_reuse") })
	if idReuseWF == "" {
		t.Fatal("the shared idreuse deploy failed in an earlier test")
	}
	return idReuseWF
}

// idemKey returns a key no other test in any port can collide with.
//
// The worker is shared by every port in a run, and the key space is global to
// the tenant: a fixed string would make these cases depend on the order the
// ports happen to run in, which is the kind of green that stops meaning
// anything.
func idemKey(t *testing.T) string {
	t.Helper()
	return fmt.Sprintf("tsg-%s-%d", t.Name(), time.Now().UnixNano())
}

// The winner has not finished. Upstream's IGNORE_DUPLICATE_WHILE_RUNNING case
// asserts that the second start gets back the FIRST run -- same id, same run id
// -- because the first was not done when the second arrived.
//
// This is also the control for the two cases below: `sleepMs` is what holds the
// winner open, and if it failed to bind (a mis-cased input key binds nothing
// and leaves the zero value) this case reads `done` and fails, while the other
// two would pass having raced nothing.
//
// THE ASSERTION IS A SET, NOT "running", and that is a finding rather than a
// hedge. cleat#1151's contract is written as `winner running -> poll or wait`,
// and core's test supplies the winner it expects --
// `winnerStore(t, &engine.WorkflowInstance{Status: "running"})` -- so nothing
// there can disagree about which statuses actually occur. A real run parked in
// a durable sleep is `ready`: migrations/postgres/003_procedures.sql sets
// status='ready' with a next_wake_at when a segment suspends. Polled every
// 500ms across an 8-second sleep, twenty consecutive samples read `ready` and
// none read `running`.
//
// cleat's own docs/reference/workflow-lifecycle.md says so in bold -- "a
// sleeping workflow is `ready`, not `suspended`", with the `ready` row reading
// "covers both 'never started' and 'sleeping until next_wake_at'". So the
// handler comment disagrees with the reference document rather than merely
// omitting a value, and it is the only place the duplicate response's meaning
// is written down.
//
// This case was written expecting `running` and failed. Filed as cleat#1325;
// the set below is the true statement in the meantime, and it is still a real
// assertion because it is CLOSED -- `done`, `failed`, a missing field or a
// status this port has not seen all fail it.
func TestADuplicateStartOfAnUnfinishedWinnerNamesItAndSaysItIsNotDone(t *testing.T) {
	wf := idReuseWorkflow(t)
	k := idemKey(t)

	// Long enough that the duplicate cannot arrive after the winner settles on
	// a loaded machine. The run is parked in a DURABLE sleep, so this costs a
	// database row and no worker slot.
	const sleepMs = 20000
	first := start(t, wf, k, map[string]any{"marker": "running-arm", "sleepMs": sleepMs, "fail": 0})
	firstID := startedRunID(t, first)

	// ESTABLISH THAT THE WINNER IS ACTUALLY MID-FLIGHT before asking about it,
	// and do it against the run row rather than against the duplicate's answer.
	//
	// This guard is the test, and it is here because its absence was measured,
	// not imagined. Written without it, mis-casing `sleepMs` to `sleepms` --
	// the exact fault start()'s doc warns about, which unbinds the parameter
	// and leaves the zero value -- left all three cases GREEN. `ready` covers
	// both "parked in a durable sleep" and "not claimed by a worker yet", so a
	// run that finished in 50ms was indistinguishable from one sleeping for
	// twenty seconds, and the arm proved nothing about a live winner.
	awaitParked(t, firstID, sleepMs/2*time.Millisecond, 30*time.Second)

	dup := start(t, wf, k, map[string]any{"marker": "running-arm", "sleepMs": sleepMs, "fail": 0})
	if dup.Status != http.StatusOK {
		t.Fatalf("the duplicate start answered %d, want 200: %s", dup.Status, dup.Raw)
	}
	if got, _ := dup.Body["already_started"].(string); got != "true" {
		t.Fatalf("the retry was not recognised as a duplicate (already_started=%q): %s", got, dup.Raw)
	}
	if got, _ := dup.Body["workflow_id"].(string); got != firstID {
		t.Errorf("the duplicate names run %q, the first start created %q -- a dedup that "+
			"returned a DIFFERENT run would satisfy already_started and be the failure "+
			"idempotency exists to prevent", got, firstID)
	}

	// The engine's non-terminal statuses, listed rather than expressed as
	// "not terminal": a status this port has never seen should fail here and
	// be read, not be waved through by a negation.
	unfinished := map[string]bool{"ready": true, "running": true, "terminating": true}
	if got, _ := dup.Body["status"].(string); !unfinished[got] {
		t.Errorf("the duplicate reports status %q, want one of ready/running/terminating.\n\n"+
			"A caller that cannot tell a run it should wait for from one whose result is "+
			"already available needs a second request to find out, and one that skips it "+
			"either polls a finished run forever or reads a running one as complete.\n%s",
			got, dup.Raw)
	}
	// An `error` on a running winner is the cleat#1115 ambiguity one layer up:
	// a failure indistinguishable from a result nobody has written yet.
	if _, present := dup.Body["error"]; present {
		t.Errorf("a RUNNING winner carried an error field: %s", dup.Raw)
	}
}

// The winner finished. This is upstream's
// TestWorkflowIDReuseRejectDuplicateNoChildWorkflow, whose assertion is
// specifically that the message begins "Workflow execution already
// **finished**" -- not merely that the second start was refused.
func TestADuplicateStartOfAFinishedWinnerSaysItIsDone(t *testing.T) {
	wf := idReuseWorkflow(t)
	k := idemKey(t)

	firstID := startedRunID(t, start(t, wf, k,
		map[string]any{"marker": "done-arm", "sleepMs": 0, "fail": 0}))
	final := awaitTerminal(t, firstID, 60*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the winner settled as %q rather than done, so there is nothing to ask "+
			"about a finished winner: %#v", got, final)
	}

	dup := start(t, wf, k, map[string]any{"marker": "done-arm", "sleepMs": 0, "fail": 0})

	// The key must still resolve AFTER the run finished. It is the half a mock
	// store cannot answer: core's double reports alreadyExisted from its own
	// state, so a real key that stopped resolving on completion would pass
	// there and fail here.
	if got, _ := dup.Body["already_started"].(string); got != "true" {
		t.Fatalf("after the winner finished, the same key started a NEW run rather than "+
			"resolving to the old one: %s", dup.Raw)
	}
	if got, _ := dup.Body["workflow_id"].(string); got != firstID {
		t.Errorf("the duplicate names %q, the winner is %q", got, firstID)
	}

	const wantStatus = "done"
	if got, _ := dup.Body["status"].(string); got != wantStatus {
		t.Errorf("the duplicate reports status %q, want %q: %s", got, wantStatus, dup.Raw)
	}
	if _, present := dup.Body["error"]; present {
		t.Errorf("a SUCCESSFUL winner carried an error field: %s", dup.Raw)
	}
}

// The winner failed. Upstream's ALLOW_DUPLICATE_FAILED_ONLY pair exists to
// distinguish a failed winner from a successful one, because a caller's next
// move differs; cleat has no policy to select, so what ports is the
// distinction being VISIBLE in the answer.
func TestADuplicateStartOfAFailedWinnerCarriesThatRunsOwnError(t *testing.T) {
	wf := idReuseWorkflow(t)
	k := idemKey(t)

	// A marker that could have come from nowhere else. Without it "the error is
	// non-empty" is satisfied by a generic string the handler could have
	// written without ever reading the run.
	marker := fmt.Sprintf("marker-%d", time.Now().UnixNano())

	firstID := startedRunID(t, start(t, wf, k,
		map[string]any{"marker": marker, "sleepMs": 0, "fail": 1}))
	final := awaitTerminal(t, firstID, 60*time.Second)
	if got, _ := final["status"].(string); got != "failed" {
		t.Fatalf("the winner settled as %q rather than failed: %#v", got, final)
	}

	dup := start(t, wf, k, map[string]any{"marker": marker, "sleepMs": 0, "fail": 1})

	const wantStatus = "failed"
	if got, _ := dup.Body["status"].(string); got != wantStatus {
		t.Fatalf("the duplicate reports status %q, want %q.\n\n"+
			"Surfacing a failed winner is the arm that saves a caller from waiting for a "+
			"result that will never improve.\n%s", got, wantStatus, dup.Raw)
	}

	gotErr, _ := dup.Body["error"].(string)
	if !strings.Contains(gotErr, marker) {
		t.Errorf("the duplicate's error is %q and does not contain %q.\n\n"+
			"The marker is the discriminator: an error that does not carry it was not read "+
			"from THIS run, and the whole point of the field is that the retry learns what "+
			"happened without a second request.", gotErr, marker)
	}
	if gotErr != "" && gotErr != final["error"] {
		t.Errorf("the duplicate reports error %q; the run row says %q -- two sources for "+
			"one fact, which is the shape cleat#1213 was", gotErr, final["error"])
	}

	// Asserted as PRESENT, not as a particular value. Measured on
	// develop@6ca1670 it is "unknown" for an ordinary workflow failure, which
	// is cleat#1009's subject: the field is returned and carries no
	// information. Pinning "unknown" here would record that as intended.
	code, present := dup.Body["error_code"].(string)
	if !present || code == "" {
		t.Errorf("the duplicate carried no error_code for a failed winner: %s", dup.Raw)
	}
	if code != "" && code != final["error_code"] {
		t.Errorf("the duplicate reports error_code %q; the run row says %q",
			code, final["error_code"])
	}
}

// awaitParked polls until the run is demonstrably parked on a durable sleep of
// at least `minPark`, and fails loudly instead of waiting if it has finished.
//
// POLLING, not a single check, and that is a bug this test had. `started_at` is
// written when a worker CLAIMS the run; `next_wake_at` only moves when the
// segment suspends. Between those two moments a claimed run looks exactly like
// an unparked one, so a helper that waited for `started_at` and then checked
// the interval once would fail whenever the claim-to-suspend window happened to
// straddle the read. It did: green in isolation and on repeat, red once in a
// full-suite run right after a redeploy -- when the first module load widens
// that window. A test that is right 90% of the time is a test that will be
// disbelieved the one time it is right about something.
//
// The `completed_at` branch is what keeps this from hanging, and it is the arm
// that catches an unbound `sleepMs`: with the parameter dropped the run settles
// in ~50ms and never parks, so waiting for a park would spin for the whole
// timeout and report it as slowness. It reports the cause instead.
func awaitParked(t *testing.T, runID string, minPark, timeout time.Duration) map[string]any {
	t.Helper()
	deadline := time.Now().Add(timeout)
	var last map[string]any
	var lastErr error
	for time.Now().Before(deadline) {
		r := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil)
		last = r.Body
		if got, _ := last["completed_at"].(string); got != "" {
			t.Fatalf("the winner finished (completed_at=%q) without ever parking on a "+
				"sleep of at least %s, so this case cannot say anything about an "+
				"unfinished winner. The usual cause is `sleepMs` not binding: the input "+
				"key is matched by exact Go parameter name.\n%#v", got, minPark, last)
		}
		if lastErr = parkedFor(last, minPark); lastErr == nil {
			return last
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("run %s never parked on a sleep of at least %s within %s (%v): %#v",
		runID, minPark, timeout, lastErr, last)
	return nil
}

// parkedFor reports whether the run's wake-up is at least `min` after it
// started -- i.e. whether the durable sleep it is parked on is the one the test
// asked for rather than an artefact of scheduling.
func parkedFor(row map[string]any, min time.Duration) error {
	startedRaw, _ := row["started_at"].(string)
	wakeRaw, _ := row["next_wake_at"].(string)
	if startedRaw == "" || wakeRaw == "" {
		return fmt.Errorf("started_at=%q next_wake_at=%q: one of them is missing", startedRaw, wakeRaw)
	}
	started, err := time.Parse(time.RFC3339Nano, startedRaw)
	if err != nil {
		return fmt.Errorf("parsing started_at %q: %w", startedRaw, err)
	}
	wake, err := time.Parse(time.RFC3339Nano, wakeRaw)
	if err != nil {
		return fmt.Errorf("parsing next_wake_at %q: %w", wakeRaw, err)
	}
	if got := wake.Sub(started); got < min {
		return fmt.Errorf("next_wake_at is only %s after started_at, want at least %s", got, min)
	}
	return nil
}
