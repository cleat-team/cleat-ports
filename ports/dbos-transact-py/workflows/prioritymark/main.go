// Package main marks its own start in the fixture's ordered call log, then
// occupies a worker slot.
//
// It exists to answer the question test_priority_is_accepted_and_recorded
// explicitly declined: the claim query orders by `priority ASC, created_at` on
// all three dialects, and nothing checks that the ordering is observable.
//
// The mark comes FIRST so the log records the moment the workflow was claimed
// and began running. The sleep after it holds the slot, so the first batch of
// claims is still occupying the worker when the test reads the log -- without
// it, fast workflows finish and free slots, later ones start, and the log stops
// describing claim order at all.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePriorityMark records "<key>.p<priority>" and then sleeps.
//
// The priority is passed in rather than read back from the run, because the
// point is to correlate the fixture's arrival order with the value the caller
// asked for -- reading it from the engine would let a bug that drops the value
// agree with itself.
func HandlePriorityMark(h cleat.HostCalls, key string, priority int, holdMs int) (string, error) {
	if _, err := h.DurableCall("queue", fmt.Sprintf("p%02d", priority),
		fmt.Sprintf(`{"key":%q}`, key)); err != nil {
		return "", fmt.Errorf("marking: %w", err)
	}
	h.DurableSleepMs(int64(holdMs))
	return fmt.Sprintf(`{"key":%q,"priority":%d}`, key, priority), nil
}
