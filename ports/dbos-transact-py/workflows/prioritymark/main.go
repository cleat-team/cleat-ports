// Package main marks its own start in the fixture's ordered call log, then
// occupies a worker slot.
//
// It exists to answer the question test_priority_is_accepted_and_recorded
// explicitly declined: the claim query orders by `priority ASC, created_at` on
// all three dialects, and nothing checks that the ordering is observable.
//
// The mark comes FIRST so the log records the moment the workflow was claimed
// and began running: the fixture appends to the ordered log BEFORE it begins
// holding, so one call does both jobs.
//
// AND THE HOLD IS THAT SAME CALL, not a sleep. This used to end with
// DurableSleepMs, on the belief -- stated in this comment -- that it held the
// worker slot. It does the opposite: a durable sleep SUSPENDS the run, writes
// it back with a next_wake_at and releases the slot immediately. Nothing then
// backed up behind -concurrency, no queue ever formed, and a claim took
// whatever existed at that instant, which is enqueue order.
//
// Measured before the change (ports#187): all 60 runs STARTED inside the same
// 1.14s the test spent enqueueing them, every one at generation 2 -- suspended
// and resumed -- and the arrival order was 59,58,...,1,0, the perfectly
// inverted answer, on 4 runs in 7.
//
// workflows/parallelunit/main.go says this in its own header and relies on it,
// as does workflows/concurrency/main.go. The fact was already in this tree,
// one directory away, in a file that depends on it being true.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePriorityMark records "<key>.p<priority>" and holds the worker slot for
// holdMs inside that same durable call.
//
// The priority is passed in rather than read back from the run, because the
// point is to correlate the fixture's arrival order with the value the caller
// asked for -- reading it from the engine would let a bug that drops the value
// agree with itself.
//
// A plain DurableCall with no retry policy, for the reason parallelunit gives:
// a policy long enough to matter would suspend the run instead of holding the
// worker, which is the defect this function was just repaired for.
func HandlePriorityMark(h cleat.HostCalls, key string, priority int, holdMs int) (string, error) {
	if _, err := h.DurableCall("queue", fmt.Sprintf("p%02d", priority),
		fmt.Sprintf(`{"key":%q,"delay_ms":%d}`, key, holdMs)); err != nil {
		return "", fmt.Errorf("marking: %w", err)
	}
	return fmt.Sprintf(`{"key":%q,"priority":%d}`, key, priority), nil
}
