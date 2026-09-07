// Package main is the parent workflow for the child fan-out tests.
package main

import (
	"encoding/json"
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleFanout spawns `n` children and waits on them.
//
//	mode == 0  AwaitAllChildren -- every child, results in order
//	mode != 0  AwaitAnyChild    -- the first to finish, the rest abandoned
//
// Both are covered from one deploy because each is a separate host call with
// separate replay handling, and AwaitAnyChild in particular is worth exercising
// end to end: its event type was the one absent from the compaction map, so a
// history containing it was silently relabelled a durable call
// (cleat-team/cleat#772).
//
// Children are staggered by their index so "the first to finish" is determined
// by the sleep rather than by scheduling luck, which is what makes the
// AwaitAnyChild assertion stable rather than flaky.
func HandleFanout(h cleat.HostCalls, n int, ms int, mode int) (string, error) {
	runIDs := make([]string, 0, n)
	for i := 0; i < n; i++ {
		input := fmt.Sprintf(`{"ms":%d,"tag":"child-%d"}`, ms*(i+1), i)
		runID, err := h.ChildWorkflow("child_leaf", input)
		if err != nil {
			return "", fmt.Errorf("spawn child %d: %w", i, err)
		}
		runIDs = append(runIDs, runID)
	}

	if mode != 0 {
		runID, result, err := h.AwaitAnyChild(runIDs)
		if err != nil {
			return "", fmt.Errorf("await any: %w", err)
		}
		return fmt.Sprintf(`{"mode":"any","run_id":%q,"result":%s,"spawned":%d}`,
			runID, result, len(runIDs)), nil
	}

	results, err := h.AwaitAllChildren(runIDs)
	if err != nil {
		return "", fmt.Errorf("await all: %w", err)
	}
	encoded, err := json.Marshal(results)
	if err != nil {
		return "", fmt.Errorf("encode results: %w", err)
	}
	return fmt.Sprintf(`{"mode":"all","results":%s,"spawned":%d}`,
		string(encoded), len(runIDs)), nil
}
