package tests

// A quorum counts voters, not votes.
//
// ISSUES.md entry 5 recorded that cleat had no "await these N distinct signals"
// primitive: AwaitSignals returns on the FIRST of a set, and
// AwaitSignalsWithQuorum's minCount counted DELIVERIES, so three copies of one
// signal satisfied a quorum of three. That is why workflows/awaitsignals/main.go
// loops over AwaitSignals once per name instead of using quorum.
//
// cleat#1132 recorded it with a reproduction; cleat#1135 fixed it by narrowing
// the awaited set as each distinct name arrives. These two cases assert the
// fixed behaviour from outside the engine, on every dialect, so it cannot
// regress into the counting the workaround exists to avoid.
//
// Measured across the fix, with the same fixture and the same three sends:
//
//	before  {"got":3,"names":"alpha,alpha,alpha","outcome":"quorum"}
//	after   {"got":1,"outcome":"timedOut"}

import (
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	quorumOnce sync.Once
	quorumWF   string
)

func quorumWorkflow(t *testing.T) string {
	t.Helper()
	quorumOnce.Do(func() { quorumWF = deploy(t, "quorum", "sg_quorum") })
	if quorumWF == "" {
		t.Fatal("the quorum workflow failed to deploy; see the first failure above")
	}
	return quorumWF
}

// startParked starts the quorum workflow and returns once it is AT its await.
//
// Waiting on the fixture call rather than sleeping: a signal sent before the
// workflow parks is queued rather than awaited, which exercises the delivery
// path instead of the quorum path and would pass for the wrong reason.
func startParked(t *testing.T, key, names string, need, timeoutMs int) string {
	t.Helper()
	runID := startedRunID(t, start(t, quorumWorkflow(t), map[string]any{
		"key": key, "names": names, "need": need, "timeoutMs": timeoutMs,
	}))
	waitForCall(t, key+"-waiting", "quorum.waiting", 60*time.Second)
	return runID
}

// resultOf decodes the workflow's result string.
//
// samples-go's neighbours assert with strings.Contains on the raw result, which
// is enough when the assertion is "this token appears". Here the assertions are
// about a COUNT and about which names were collected, so the value is decoded
// rather than pattern-matched -- `"got":1` and `"got":11` both contain `"got":1`.
func resultOf(t *testing.T, final map[string]any) map[string]any {
	t.Helper()
	raw, ok := final["result"].(string)
	if !ok {
		t.Fatalf("terminal row carries no string result: %#v", final)
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		t.Fatalf("result is not JSON (%v): %q", err, raw)
	}
	return out
}

func TestRepeatsOfOneSignalDoNotReachAQuorum(t *testing.T) {
	key := key(t)
	runID := startParked(t, key, "alpha,beta,gamma", 3, 20_000)

	// Three sends, one name. Under the old counting this reached quorum and
	// returned names "alpha,alpha,alpha".
	for i := 0; i < 3; i++ {
		if r := signal(t, runID, "alpha", `{}`); r.Status != 200 {
			t.Fatalf("delivering alpha #%d answered %d: %s", i+1, r.Status, r.Raw)
		}
		time.Sleep(300 * time.Millisecond)
	}

	final := awaitTerminal(t, runID, 60*time.Second)
	b := resultOf(t, final)

	if b["outcome"] != "timedOut" {
		t.Errorf("three copies of one signal reached a quorum of three: %#v.\n"+
			"A quorum counts DISTINCT names; counting deliveries lets one voter "+
			"vote three times, which is what cleat#1135 fixed.", b)
	}
	if got, _ := b["got"].(float64); got != 1 {
		t.Errorf("the wait collected %v signals, want 1: repeats of a name already "+
			"counted must not add to the tally. %#v", b["got"], b)
	}
}

func TestDistinctSignalsReachAQuorum(t *testing.T) {
	key := key(t)
	runID := startParked(t, key, "alpha,beta,gamma", 3, 30_000)

	// The control for the case above. Without it, a quorum that never completed
	// at all -- a fix that narrowed the set to nothing, say -- would satisfy the
	// first test and be indistinguishable from correct.
	for _, name := range []string{"alpha", "beta", "gamma"} {
		if r := signal(t, runID, name, `{}`); r.Status != 200 {
			t.Fatalf("delivering %s answered %d: %s", name, r.Status, r.Raw)
		}
		time.Sleep(300 * time.Millisecond)
	}

	final := awaitTerminal(t, runID, 60*time.Second)
	b := resultOf(t, final)

	if b["outcome"] != "quorum" {
		t.Fatalf("three distinct signals did not reach a quorum of three: %#v", b)
	}
	names, _ := b["names"].(string)
	for _, want := range []string{"alpha", "beta", "gamma"} {
		if !strings.Contains(names, want) {
			t.Errorf("the quorum did not collect %q: names=%q. Each awaited name "+
				"must appear exactly once, and the set is what the quorum counts.",
				want, names)
		}
	}
}
