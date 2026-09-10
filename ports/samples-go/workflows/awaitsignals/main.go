// Package main is the cleat port of temporalio/samples-go `await-signals/`.
//
// Upstream waits for several DISTINCT named signals and proceeds once all of
// them have arrived, in any order. cleat has no single call with that shape:
//
//	AwaitSignals(names, timeout)                          -> returns on ONE
//	AwaitSignalsWithQuorum(names, minCount, maxRej, tmo)  -> returns on N of them
//
// The mapping is the interesting part, so this workflow uses the LOOP over
// AwaitSignals rather than quorum. Two reasons:
//
//   - Quorum WAS the closer-looking fit and the wrong one: minCount counted
//     SIGNALS, not distinct names, so three deliveries of "approve" satisfied a
//     quorum of 3 over three different names. Recorded as ISSUES entry 5, filed
//     as cleat#1132, FIXED by cleat#1135 -- the awaited set is now narrowed as
//     each distinct name arrives, so quorum expresses upstream's guarantee.
//
//     This fixture still loops, deliberately. It is the port of upstream's
//     await-signals sample and several cases here assert its per-name timeout
//     behaviour, which the loop is what produces. The quorum call is exercised
//     by workflows/quorum and tests/quorum_test.go, which is where the fix is
//     pinned so it cannot regress.
//
//   - The loop is what a reader porting this sample would write, so it is the
//     path worth having coverage on.
//
// The port therefore records what it did NOT use, and why, in ../../ISSUES.md.
package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleAwaitSignals waits for every name in `names` (comma separated) to
// arrive at least once, then returns them in ARRIVAL order.
//
// Arrival order is returned rather than the requested order because it is the
// only part of the result that could disagree with the caller's expectation,
// and a result that can only agree is not evidence. Upstream's guarantee is
// order-independence: the same set, whatever sequence it came in.
//
// names is a comma-joined string rather than a []string. Entry-point arguments
// bind by exact parameter name from a JSON object, and a slice parameter is
// not a shape this boundary carries -- so the join keeps the binding honest
// instead of silently leaving a nil slice and waiting for nothing.
func HandleAwaitSignals(h cleat.HostCalls, key string, names string, timeoutMs int) (string, error) {
	wanted := strings.Split(names, ",")
	if len(wanted) == 0 || names == "" {
		return "", fmt.Errorf("no signal names given")
	}

	// Published before the first wait so a test can tell "the workflow has
	// begun waiting" from "the workflow has not been claimed yet". Without it,
	// a signal sent too early would be indistinguishable from a signal lost.
	h.SetQueryState("phase", "waiting")

	seen := map[string]bool{}
	var order []string

	// A TOTAL budget, not a per-call one, and the difference is not academic.
	//
	// The first version passed the same timeoutMs to every AwaitSignals in the
	// loop, so each call suspended with a fresh deadline. Every delivery that
	// did not advance `seen` -- a duplicate, or a name already recorded --
	// restarted the clock. Three duplicates of one signal bought three extra
	// timeout periods, and the run took 20s against an "8000ms" timeout.
	//
	// That is correct per-call behaviour from the engine: AwaitSignals promises
	// a timeout for THAT call and delivers one. The test wanted to say "this
	// workflow gives up after 8 seconds", which is a different claim, and
	// writing it as a per-call value made the assertion unfalsifiable -- an
	// external party sending duplicates could defer it indefinitely.
	//
	// Deadline arithmetic in durable time: h.Now() is the virtual clock, so
	// this is deterministic on replay in a way that time.Now() would not be.
	budget := time.Duration(timeoutMs) * time.Millisecond
	giveUpAt := h.Now().Add(budget)

	for len(seen) < len(wanted) {
		remaining := giveUpAt.Sub(h.Now())
		if remaining <= 0 {
			return fmt.Sprintf(`{"key":%q,"timedOut":true,"seen":%q}`,
				key, strings.Join(order, ",")), nil
		}
		res := h.AwaitSignals(wanted, remaining)
		if res.Err != nil {
			return "", fmt.Errorf("await: %w", res.Err)
		}
		if res.TimedOut {
			// Reported rather than treated as failure: "which ones had arrived
			// when it gave up" is the diagnostic, and a bare timeout error
			// throws it away.
			return fmt.Sprintf(`{"key":%q,"timedOut":true,"seen":%q}`,
				key, strings.Join(order, ",")), nil
		}
		if !seen[res.Name] {
			seen[res.Name] = true
			order = append(order, res.Name)
			h.SetQueryState("seen", strings.Join(order, ","))
		}
		// A repeat of a name already seen is deliberately NOT an error and
		// does not extend the set. Upstream's condition is "each name has
		// arrived", so a duplicate is a no-op rather than progress -- and a
		// loop that counted deliveries instead would finish early on three
		// copies of one signal.
	}

	h.SetQueryState("phase", "complete")
	return fmt.Sprintf(`{"key":%q,"order":%q}`, key, strings.Join(order, ",")), nil
}
