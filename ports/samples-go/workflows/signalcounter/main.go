// Package main is the cleat port of temporalio/samples-go `signal-counter/`.
//
// Upstream accumulates a running total from repeated deliveries of ONE signal
// name and completes on a terminal signal. The guarantee is that every delivery
// counts exactly once: the total equals the number of signals sent.
//
// That makes it the sharpest available test of cleat#933 symptom A. A defect
// where one delivery satisfies more than one await is an oddity in a test that
// waits for three distinct names; in a counter it is a wrong number. Upstream's
// sample is, by construction, the shape that turns A into a visible arithmetic
// error rather than a scheduling curiosity.
package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSignalCounter counts deliveries of "tick" until "done" arrives.
//
// The count is published as query state after every increment so a test can
// watch it climb while the workflow is still running -- the interesting value
// is mid-run, and a caller that waits for completion has already missed the
// intermediate states.
//
// budgetMs is a TOTAL budget rather than a per-call timeout. The distinction
// cost this port a wrong finding: passing the same value to every AwaitSignals
// in a loop gives each call its own fresh deadline, so any delivery that does
// not advance the loop restarts the clock and the workflow can be kept alive
// indefinitely by whoever is sending.
func HandleSignalCounter(h cleat.HostCalls, key string, budgetMs int) (string, error) {
	giveUpAt := h.Now().Add(time.Duration(budgetMs) * time.Millisecond)

	count := 0
	h.SetQueryState("count", "0")
	h.SetQueryState("phase", "counting")

	var seen []string
	for {
		remaining := giveUpAt.Sub(h.Now())
		if remaining <= 0 {
			return fmt.Sprintf(`{"key":%q,"count":%d,"timedOut":true,"seen":%q}`,
				key, count, strings.Join(seen, ",")), nil
		}

		res := h.AwaitSignals([]string{"tick", "done"}, remaining)
		if res.Err != nil {
			return "", fmt.Errorf("await: %w", res.Err)
		}
		if res.TimedOut {
			return fmt.Sprintf(`{"key":%q,"count":%d,"timedOut":true,"seen":%q}`,
				key, count, strings.Join(seen, ",")), nil
		}

		seen = append(seen, res.Name)
		if res.Name == "done" {
			h.SetQueryState("phase", "finished")
			return fmt.Sprintf(`{"key":%q,"count":%d,"timedOut":false,"seen":%q}`,
				key, count, strings.Join(seen, ",")), nil
		}

		count++
		h.SetQueryState("count", fmt.Sprintf("%d", count))
	}
}
