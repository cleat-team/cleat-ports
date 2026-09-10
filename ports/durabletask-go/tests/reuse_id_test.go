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

func TestADeduplicatedStartKeepsTheFirstRunsInput(t *testing.T) {
	wf := reuseWorkflow(t)
	idem := key(t)

	first := startWithKey(t, wf, idem, map[string]any{"marker": "first", "n": 1})
	firstID := startedRunID(t, first)

	// A DIFFERENT payload, which is the entire point. Sending the same one --
	// as the two existing dedup tests do -- makes this assertion unavailable,
	// because a second run started with identical input is indistinguishable
	// from the first being returned.
	second := startWithKey(t, wf, idem, map[string]any{"marker": "second", "n": 2})
	secondID := startedRunID(t, second)

	if firstID != secondID {
		t.Fatalf("the second start under the same Idempotency-Key produced a "+
			"different run (%s vs %s), so cleat did not deduplicate at all and "+
			"the input assertion below would be meaningless", firstID, secondID)
	}

	final := awaitTerminal(t, firstID, 60*time.Second)
	if got, _ := final["status"].(string); got != "done" {
		t.Fatalf("the run did not finish: %#v", final)
	}

	// One constant, used by both the condition and the message. Writing the
	// expected value twice lets a later edit change one and leave the other
	// lying -- mutation-testing this file produced exactly that: a message
	// reading `carries marker "first", not "first"`.
	const wantMarker = "first"

	b := body(t, final)
	if b["marker"] != wantMarker {
		t.Errorf("the surviving run carries marker %q, not %q -- the SECOND "+
			"start's input reached the run, so deduplication returned the first "+
			"id while overwriting its payload. Every existing dedup test here "+
			"sends identical input on both starts and cannot see this.",
			b["marker"], wantMarker)
	}
	// n is checked as well as marker because they bind through different types.
	// A binder that dropped only the integer would leave marker correct.
	if n, ok := b["n"].(float64); !ok || n != 1 {
		t.Errorf("the surviving run carries n=%v, not 1: %#v", b["n"], b)
	}
}

func TestADeduplicatedStartKeepsTheFirstRunsClock(t *testing.T) {
	wf := reuseWorkflow(t)
	idem := key(t)

	first := startWithKey(t, wf, idem, map[string]any{"marker": "clock-first", "n": 1})
	firstID := startedRunID(t, first)

	createdAfterFirst := createdAt(t, firstID)

	// A gap the clock can resolve. Without it a pass could mean "created_at was
	// preserved" or "both starts landed inside one timestamp tick", and those
	// are the two hypotheses this test exists to separate.
	time.Sleep(1100 * time.Millisecond)

	second := startWithKey(t, wf, idem, map[string]any{"marker": "clock-second", "n": 2})
	if secondID := startedRunID(t, second); secondID != firstID {
		t.Fatalf("the second start produced a different run (%s vs %s); "+
			"deduplication did not happen and there is no clock to compare",
			secondID, firstID)
	}

	createdAfterSecond := createdAt(t, firstID)

	if createdAfterFirst != createdAfterSecond {
		t.Errorf("created_at moved from %q to %q when a duplicate start was "+
			"deduplicated. The surviving run must report the FIRST start's "+
			"clock; a dedup that rewrites the row and returns its id passes "+
			"every other assertion in this repo and fails here.",
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
