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
//   - Quorum is the closer-looking fit and the wrong one. minCount counts
//     SIGNALS, not distinct names, so three deliveries of "approve" satisfy a
//     quorum of 3 over three different names. Upstream's guarantee is that
//     each named signal arrived once, which quorum cannot express.
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

	deadline := time.Duration(timeoutMs) * time.Millisecond
	for len(seen) < len(wanted) {
		res := h.AwaitSignals(wanted, deadline)
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
