// Package main is the workflow under test for bulk cancellation.
//
// Upstream's test_bulk_cancel starts several workflows that each complete a
// first step, block, and would then run a second. It cancels them all and
// asserts the first step ran on every one and the second on none -- so the
// assertion is about a DURABLE SIDE EFFECT that did not happen, not about a
// status field.
//
// That is why this is a separate fixture from workflows/cancellation. That one
// answers "does a polling workflow observe cancellation" and reports an outcome
// string; it has no steps, so it cannot say whether work downstream of the
// cancel was skipped. A port reusing it would asserts statuses and quietly drop
// the half of the upstream case that matters.
//
// Each step is a durable call to the fixture service, which counts calls per
// key. Counting there rather than in the workflow's result is deliberate: a
// result is written by the run that is being cancelled, so a cancelled run
// reporting "I did not run step two" is the defendant testifying. The fixture
// is a third party and its count survives whatever the run reports.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleBulkCancelSteps runs step one, then polls for cancellation for up to
// `ms`, then runs step two.
//
// The poll loop is what makes cancellation observable at all: cleat's
// cancellation is cooperative (PollCancellation returns a bool the workflow
// decides what to do with), so a workflow that never asks runs to completion.
// See workflows/cancellation for the case that pins that.
func HandleBulkCancelSteps(h cleat.HostCalls, key string, ms int) (string, error) {
	const step = 250

	if _, err := h.DurableCall("steps", "one",
		fmt.Sprintf(`{"key":%q}`, key+"-one")); err != nil {
		return fmt.Sprintf(`{"outcome":"step_one_failed","error":%q}`,
			fmt.Sprintf("%v", err)), nil
	}

	elapsed := 0
	for elapsed < ms {
		if cancelled, reason := h.PollCancellation(); cancelled {
			h.DurableLog("bulk-cancel: observed cancellation: " + reason)
			// Return WITHOUT running step two. That omission is the whole
			// assertion; a workflow that ran it anyway would be the defect
			// upstream's test exists to catch.
			return fmt.Sprintf(`{"outcome":"cancelled","reason":%q,"elapsed_ms":%d}`,
				reason, elapsed), nil
		}
		h.DurableSleepMs(step)
		elapsed += step
	}

	if _, err := h.DurableCall("steps", "two",
		fmt.Sprintf(`{"key":%q}`, key+"-two")); err != nil {
		return fmt.Sprintf(`{"outcome":"step_two_failed","error":%q}`,
			fmt.Sprintf("%v", err)), nil
	}
	return fmt.Sprintf(`{"outcome":"completed","elapsed_ms":%d}`, elapsed), nil
}
