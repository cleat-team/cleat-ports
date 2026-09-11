package tests

// Upstream: tests/backend_test.go, Test_PurgeOrchestrationState.
//
// Upstream purges one instance and then asserts THREE things, of which only the
// first is obvious:
//
//	be.PurgeOrchestrationState(ctx, instanceID)              -> no error
//	be.GetOrchestrationMetadata(ctx, instanceID)             -> api.ErrInstanceNotFound
//	state.NewEvents() == 0 && state.OldEvents() == 0         -> the HISTORY is gone too
//	be.PurgeOrchestrationState(ctx, instanceID) (again)      -> api.ErrInstanceNotFound
//
// The third is the one worth porting. A purge that removes the metadata row and
// leaves the history behind reads as success from every direction: the run is
// unfindable, the count of runs falls, and the rows that remain are unreachable
// rather than merely retained. That is exactly what cleat did -- on SQL Server
// all six child tables survived a sweep (cleat#1265), and on every dialect the
// idempotency key did (cleat#1255), so a retry was answered already_started with
// a workflow_id that no longer existed.
//
// TWO DIVERGENCES FROM UPSTREAM, both deliberate.
//
// cleat has no per-instance purge. Upstream takes an instance id; cleat's
// equivalent is a retention SWEEP over everything past a window, driven by
// POST /api/admin/retention/sweep. So this asserts the same postconditions
// about one run without being able to name it in the request, and the sweep is
// necessarily destructive of other completed runs in the same database. Safe
// here because this port declares no t.Parallel() and every test settles its own
// run before the next begins -- checked, not assumed.
//
// And the fourth assertion does not port. A second purge of a named instance is
// ErrInstanceNotFound upstream; a second SWEEP has nothing to be not-found
// about and correctly reports zero. What is asserted instead is that the second
// sweep is a clean no-op rather than an error, which is the nearest true
// statement.

import (
	"net/http"
	"testing"
	"time"
)

// sweep drives the operator endpoint. older_than is required here: the
// configured window is a whole day and every run this suite creates completed
// seconds ago.
func sweep(t *testing.T, olderThan string) response {
	t.Helper()
	return call(t, http.MethodPost, "/api/admin/retention/sweep",
		map[string]any{"older_than": olderThan}, nil)
}

// skippedArms reports which arms the sweep declined to run because their flag
// is 0. The endpoint reports this separately from the counts precisely so that
// a zero is never ambiguous between "disabled" and "found nothing" -- without
// it, a test against an unconfigured worker fails describing the engine when
// the fault is the configuration.
func skippedArms(r response) []string {
	raw, ok := r.Body["skipped"].([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func TestASweepRemovesACompletedRunFromTheReadPath(t *testing.T) {
	runID := startedRunID(t, start(t, emptyWorkflow(t), map[string]any{
		"marker": "purge-" + time.Now().Format("150405.000000000"), "n": 1,
	}))
	awaitTerminal(t, runID, 60*time.Second)

	// Preconditions. Each of these can fail for a reason that has nothing to do
	// with purging, and each would otherwise make the assertions below pass
	// while measuring nothing.
	if r := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil); r.Status != http.StatusOK {
		t.Fatalf("precondition: the completed run reads %d before any sweep, want 200: %s",
			r.Status, r.Raw)
	}
	// Upstream's third assertion does not port, and the reason is worth
	// recording rather than quietly dropping.
	//
	// It asserts the runtime state holds zero events after the purge -- that
	// the HISTORY goes with the metadata. cleat exposes no history read path
	// for a run in this state: /api/workflows/{id}/events and
	// /api/instances/{id}/history both answer 404 while the run plainly
	// exists, which the DBOS port had already recorded before this one was
	// written. And cleat deletes a done/failed run's event_history at FINALIZE
	// time in finalize_workflow_status -- --retention-days' own flag help says
	// so -- so by the time a run is sweepable there is nothing left for the
	// sweep to remove and nothing outside the engine that could observe it
	// either way.
	//
	// The first version of this test asserted a 404 on those paths after the
	// sweep. Its precondition caught it: they 404 BEFORE the sweep too, so the
	// assertion would have held without retention running at all. That is the
	// failure this whole file is about -- a check that passes for a reason
	// unrelated to its subject -- so it is called out here rather than deleted
	// silently. The engine-side coverage for the history half is cleat#1265's
	// test, which reads the tables directly.

	r := sweep(t, "1ms")
	if r.Status != http.StatusOK {
		t.Fatalf("sweep answered %d, want 200: %s", r.Status, r.Raw)
	}
	for _, arm := range skippedArms(r) {
		if arm == "completed_workflows" || arm == "completed" {
			t.Fatalf("the sweep skipped the completed-workflows arm, so nothing below "+
				"measures purging. That is a CONFIGURATION fault, not an engine one: the "+
				"worker needs -completed-workflow-retention-days, which scripts/env.sh "+
				"sets by default via CLEAT_PORTS_WORKER_EXTRA_FLAGS. Response: %s", r.Raw)
		}
	}

	// Upstream's first two assertions: the instance is not found afterwards.
	if got := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil); got.Status != http.StatusNotFound {
		t.Errorf("after the sweep the run reads %d, want 404. A purged run must be gone "+
			"from the read path, not merely unlisted: %s", got.Status, got.Raw)
	}

	// Upstream purges twice and expects the second to say not-found. A sweep has
	// no instance to be not-found about, so the true statement is that repeating
	// it is a clean no-op rather than an error.
	if again := sweep(t, "1ms"); again.Status != http.StatusOK {
		t.Errorf("a second sweep answered %d, want 200; repeating a sweep must not be an "+
			"error: %s", again.Status, again.Raw)
	}
}
