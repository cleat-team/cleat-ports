// Package main is the minimal reproduction for cleat-team/cleat#933.
//
// It is deliberately not part of the await-signals sample. It contains two
// straight-line AwaitSignals calls and nothing else -- no loop, no query
// state, no fixture call, no map, no slice -- so a failure here cannot be
// attributed to anything the port does.
//
// That mattered. The first version of this investigation reported a checksum
// defect from the port's own looping workflow, and the loop turned out to be
// load-bearing: two awaits and three awaits fail DIFFERENTLY (#933 A and B).
// Isolating them needed a workflow with no second explanation available.
//
// It ships with the port rather than living in a scratch directory because a
// reproduction nobody can run is a claim, not evidence.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleTwoAwaits awaits the same two-name set twice and reports what each
// call returned.
//
// The second parameter is unused and exists only because a workflow with a
// SINGLE string parameter receives the raw input JSON instead of a bound
// field -- so `tag` would arrive as `{"tag": "..."}` rather than the value.
// A second parameter restores binding by name.
func HandleTwoAwaits(h cleat.HostCalls, tag string, unused int) (string, error) {
	names := []string{"a", "b"}

	first := h.AwaitSignals(names, 20*time.Second)
	if first.Err != nil {
		return "", fmt.Errorf("first: %w", first.Err)
	}
	second := h.AwaitSignals(names, 20*time.Second)
	if second.Err != nil {
		return "", fmt.Errorf("second: %w", second.Err)
	}

	return fmt.Sprintf(`{"tag":%q,"first":%q,"firstTimedOut":%t,"second":%q,"secondTimedOut":%t}`,
		tag, first.Name, first.TimedOut, second.Name, second.TimedOut), nil
}
