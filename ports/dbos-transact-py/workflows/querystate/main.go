// Package main is the workflow under test for externally readable query state.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleQueryState publishes query state on both sides of a suspension.
//
// The sleep is the point. Query state exists so a caller can ask "what is this
// workflow doing" without anything running -- docs/determinism.md says the
// value is readable "regardless of whether any worker currently has the
// workflow loaded". A suspended workflow is that case, and it was the one case
// that returned nothing: finalize_workflow_status wrote query_state on its
// 'done' and 'failed' branches and not on 'ready', so a value reached the
// database only once the workflow had finished and its result was available
// anyway. cleat#844.
//
// Two keys, because they fail differently. `phase` changes across the
// suspension, so it shows that a reader sees the CURRENT value rather than the
// final one. `tag` is set once before the sleep and never again, so it shows
// that a value published in an earlier segment survives into later ones.
func HandleQueryState(h cleat.HostCalls, tag string, sleepMs int) (string, error) {
	h.SetQueryState("phase", "started")
	h.SetQueryState("tag", tag)

	h.DurableSleepMs(int64(sleepMs))

	h.SetQueryState("phase", "finished")
	return fmt.Sprintf(`{"tag":%q}`, tag), nil
}
