package tests

// Re-using a run id, ported from microsoft/durabletask-go
// `tests/orchestrations_test.go::Test_SingleActivity_ReuseInstanceIDIgnore`.
//
// Derived from the upstream assertion, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md.
//
// WHAT UPSTREAM ASSERTS AND WHY ONLY PART OF IT PORTS. durabletask-go offers
// four reuse policies and this case exercises the opt-in `IGNORE` one: start
// twice under one id, the second start is dropped, and the surviving run is the
// first -- including its `CreatedAt`.
//
// cleat has exactly one reuse policy and it IS this one, reached through the
// `Idempotency-Key` start header. So the *policy selection* half does not port
// (there is nothing to select) and the *behaviour* half ports directly.
//
// WHAT WAS ALREADY COVERED, AND WHAT WAS NOT, because the difference is the
// whole reason this file exists. ports/dbos-transact-py already asserts that
// one key yields one run and one side effect
// (`test_queues.py::test_the_same_idempotency_key_starts_one_run`) and that the
// binding outlives the run (`test_a_completed_run_still_answers_for_its_
// idempotency_key`).
//
// Both send the SAME payload on both starts. That is a real gap rather than a
// stylistic one: identical input cannot distinguish "returned the first run"
// from "started a second run that happens to look identical". The two
// assertions below are the ones a differing payload makes available, and
// neither exists anywhere in this repo:
//
//   - the surviving run carries the FIRST start's input
//   - the surviving run reports the FIRST start's created_at
//
// The second is the one upstream names explicitly and it is not decoration: a
// dedup implemented as "overwrite the row and return its id" would pass every
// existing assertion here and fail this one.

import (
	"net/http"
	"testing"
	"time"
)

// reuseWorkflow is the empty orchestration: it echoes `marker` and `n` into its
// result without making a host call, which is exactly what is needed to see
// WHICH start's input the surviving run kept.
func reuseWorkflow(t *testing.T) string {
	t.Helper()
	return emptyWorkflow(t)
}

// startWithKey starts a workflow under an Idempotency-Key.
//
// The header spelling is the engine's: cmd/cleat-worker/server.go does
// `r.Header.Get("Idempotency-Key")` with no trimming, which
// ports/dbos-transact-py/tests/test_idempotency_key_form.py pins separately.
func startWithKey(t *testing.T, name, key string, input map[string]any) response {
	t.Helper()
	return call(t, http.MethodPost, "/api/workflows/"+name+"/start",
		map[string]any{"input": input}, map[string]string{"Idempotency-Key": key})
}

// cleat DIVERGES from upstream here, deliberately, and these tests assert
// cleat's contract rather than upstream's.
//
// Upstream's reuse policy is IGNORE: a second start under a live id is silently
// dropped and the first run stands, whatever payload the second carried. cleat
// (cleat#1170, merged 2026-09-11) refuses a reused key carrying a DIFFERENT
// input with 409 `idempotency_key_input_mismatch` instead of replaying it.
//
// The decision was taken here on 2026-09-11 (cleat-ports#214): cleat is right.
// A caller who changed the payload almost certainly did not mean to reuse the
// token, and answering them with a different request's result is the failure
// mode cleat#1167 and cleat#1255 were both about -- a retry handed someone
// else's run, or a run that no longer exists.
//
// What upstream is actually protecting survives intact and is still asserted:
// THE FIRST RUN IS NEVER DISTURBED. Upstream gets that by ignoring the second
// start; cleat gets it by refusing. Either way a second payload cannot reach a
// run that already exists, which is the property both suites care about.
//
// The same-input case still deduplicates on both sides, and is covered below --
// without it, nothing here would show that cleat dedupes at all, only that it
// refuses.

func TestAReusedKeyWithADifferentInputIsRefused(t *testing.T) {
	wf := reuseWorkflow(t)
	idem := key(t)

	first := startWithKey(t, wf, idem, map[string]any{"marker": "first", "n": 1})
	firstID := startedRunID(t, first)

	second := startWithKey(t, wf, idem, map[string]any{"marker": "second", "n": 2})
	if second.Status != http.StatusConflict {
		t.Fatalf("a reused Idempotency-Key carrying a DIFFERENT input answered %d, "+
			"want 409. Upstream would ignore the second start; cleat refuses it "+
			"(cleat#1170), and silently replaying it instead would hand the caller "+
			"a run built from somebody else's payload: %s", second.Status, second.Raw)
	}
	if detail, _ := second.Body["detail"].(string); detail != "idempotency_key_input_mismatch" {
		t.Errorf("the refusal reports detail %q, want \"idempotency_key_input_mismatch\". "+
			"The code is what a client branches on; the prose is not: %s", detail, second.Raw)
	}

	// The property upstream's IGNORE policy exists to protect, asserted against
	// cleat's refusal: the first run is untouched. This is the assertion that
	// carries over unchanged, and it is the reason the test still belongs here.
	final := awaitTerminal(t, firstID, 60*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the first run did not finish: %#v", final)
	}

	// One constant, used by both the condition and the message. Writing the
	// expected value twice lets a later edit change one and leave the other
	// lying -- mutation-testing this file produced exactly that: a message
	// reading `carries marker "first", not "first"`.
	const wantMarker = "first"

	b := body(t, final)
	if b["marker"] != wantMarker {
		t.Errorf("the surviving run carries marker %q, not %q -- the REFUSED start's "+
			"input reached the run anyway, so the refusal is not atomic with the "+
			"payload check", b["marker"], wantMarker)
	}
	// n is checked as well as marker because they bind through different types.
	// A binder that dropped only the integer would leave marker correct.
	if n, ok := b["n"].(float64); !ok || n != 1 {
		t.Errorf("the surviving run carries n=%v, not 1: %#v", b["n"], b)
	}
}

func TestAReusedKeyWithTheSameInputReplaysTheFirstRun(t *testing.T) {
	wf := reuseWorkflow(t)
	idem := key(t)
	input := map[string]any{"marker": "same", "n": 3}

	firstID := startedRunID(t, startWithKey(t, wf, idem, input))
	second := startWithKey(t, wf, idem, input)
	secondID := startedRunID(t, second)

	// This is upstream's dedup contract in the one shape cleat still honours,
	// and it is why the refusal above is a narrowing rather than a removal.
	// Without this case the suite would show only that cleat says no, never
	// that it deduplicates.
	if secondID != firstID {
		t.Errorf("a reused key with the SAME input produced a different run "+
			"(%s vs %s); cleat#1170 narrowed dedup to matching payloads, it did "+
			"not remove it", secondID, firstID)
	}
}

func TestARefusedReuseDoesNotMoveTheFirstRunsClock(t *testing.T) {
	wf := reuseWorkflow(t)
	idem := key(t)

	firstID := startedRunID(t, startWithKey(t, wf, idem,
		map[string]any{"marker": "clock-first", "n": 1}))
	createdAfterFirst := createdAt(t, firstID)

	// A gap the clock can resolve. Without it a pass could mean "created_at was
	// preserved" or "both starts landed inside one timestamp tick", and those
	// are the two hypotheses this test exists to separate.
	time.Sleep(1100 * time.Millisecond)

	second := startWithKey(t, wf, idem, map[string]any{"marker": "clock-second", "n": 2})
	if second.Status != http.StatusConflict {
		t.Fatalf("the second start answered %d, want 409; with no refusal there is "+
			"nothing to prove about the first run's clock: %s", second.Status, second.Raw)
	}

	if createdAfterSecond := createdAt(t, firstID); createdAfterFirst != createdAfterSecond {
		t.Errorf("created_at moved from %q to %q when a duplicate start was REFUSED. "+
			"A refusal must leave the existing row alone; rewriting it and then "+
			"returning 409 passes every other assertion in this repo and fails here.",
			createdAfterFirst, createdAfterSecond)
	}
}

// createdAt reads a run's created_at from the single-run endpoint.
//
// Deliberately NOT the list endpoint: cleat#1123 records that GET
// /api/workflows and GET /api/workflows/{id} are served by different column
// lists, and while created_at is in both today, reading the one this assertion
// is about keeps the test measuring the run rather than the listing.
func createdAt(t *testing.T, runID string) string {
	t.Helper()
	r := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil)
	if r.Status != http.StatusOK {
		t.Fatalf("reading run %s answered %d: %s", runID, r.Status, r.Raw)
	}
	v, ok := r.Body["created_at"].(string)
	if !ok || v == "" {
		t.Fatalf("run %s reports no created_at, so this test cannot run: %s", runID, r.Raw)
	}
	return v
}
