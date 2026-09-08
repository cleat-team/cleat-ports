// Package main is the cleat port of temporalio/samples-go `query/` and
// `query-workflow/`.
//
// The two engines answer a query in structurally different ways, and that
// difference is what this workflow is shaped to expose.
//
//	Temporal   a registered handler is INVOKED when the query arrives, and
//	           computes its answer from live workflow state at that moment.
//	cleat      SetQueryState PUBLISHES a value; the reader gets whatever was
//	           published last.
//
// Push versus pull. Everything else follows from it: cleat cannot answer a
// question the workflow did not anticipate, and a value goes stale the moment
// the state it described moves on without a republish.
//
// So this workflow deliberately lets one value go stale. `counter` is
// republished at each step; `firstSeen` is published once and never again,
// while the thing it describes keeps changing. A Temporal handler reading the
// same field would return the current value at query time; cleat returns the
// old one, correctly, by its own model.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleQueryTarget counts up to `steps`, sleeping `stepMs` between each.
//
// Parameters bind by exact name: {"key": ..., "steps": ..., "stepMs": ...}.
func HandleQueryTarget(h cleat.HostCalls, key string, steps int, stepMs int) (string, error) {
	// Published once, before anything moves. Its whole purpose is to be stale
	// later -- it names step 0 forever, while `counter` tracks the truth.
	h.SetQueryState("firstSeen", "0")
	h.SetQueryState("phase", "running")

	for i := 0; i < steps; i++ {
		h.SetQueryState("counter", fmt.Sprintf("%d", i))
		h.DurableSleepMs(int64(stepMs))
	}

	h.SetQueryState("counter", fmt.Sprintf("%d", steps))
	h.SetQueryState("phase", "finished")
	return fmt.Sprintf(`{"key":%q,"counter":%d}`, key, steps), nil
}
