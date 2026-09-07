// Package main is the workflow under test for durable deferred cleanup.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleDeferCleanup registers a cleanup body, suspends, and completes.
//
// The two keys are what makes the test able to distinguish "the defer ran" from
// "the body ran": the body calls the fixture under bodyKey immediately, the
// defer calls it under deferKey. A test observing the workflow mid-sleep should
// see the first and not the second -- a defer that fires at registration time
// rather than at the end is a defer in name only, and a count-only check after
// completion cannot tell the two apart.
//
// The sleep is load-bearing for the second property. A durable sleep suspends
// the workflow and the resumed execution replays the body from step 0, so
// DurableDeferFunc is CALLED twice across the run. If each call appended a
// fresh entry to the defer table, the surviving execution would drain two of
// them.
//
// That the cleanup arrives at all is the claim worth making. IMPROVEMENT-PLAN
// 3.70 records that "every defer in every Go WASM workflow came to do nothing
// while the host recorded success" -- the host invoked defers by entry-point
// name and no guest exported one, and the miss was indistinguishable from a
// hit. A test that asserted only "the workflow completed" passed throughout
// that period.
func HandleDeferCleanup(h cleat.HostCalls, bodyKey string, deferKey string, sleepMs int) (string, error) {
	if err := h.DurableSend("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, bodyKey)); err != nil {
		return "", err
	}

	if _, err := h.DurableDeferFunc(func() {
		// A defer body's own host calls are ordinary durable calls. The engine
		// permits them deliberately: a cleanup that cannot reach the host
		// cannot release the lock it took (engine/durablecalls.go).
		h.DurableSend("flaky", "op", fmt.Sprintf(`{"key":%q,"fail_times":0}`, deferKey))
	}); err != nil {
		return "", err
	}

	h.DurableSleepMs(int64(sleepMs))

	return `{"finished":true}`, nil
}
