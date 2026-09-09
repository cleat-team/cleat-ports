// Package main returns the run id the engine gave THIS execution.
//
// Upstream `test_concurrency.py::test_concurrent_workflows` starts ten
// workflows from a thread pool, each under a caller-supplied id, and asserts
// each one returns its own. The assertion looks trivial and is not: it is the
// only thing in that file that would catch a host leaking identity between
// executions that overlap in time.
//
// cleat is the engine where that leak is most expressible. One worker runs
// many workflows concurrently and each is a WASM instance the host drives, so
// "which run am I" is answered by host state the guest reads back through
// `cleat_workflow_id` rather than by anything the guest holds itself. A host
// that resolved that against the wrong entry -- a pooled instance, a reused
// context, an index into a slice of in-flight runs -- would produce a workflow
// that completes perfectly and reports somebody else's identity.
//
// The sleep is load-bearing for the same reason upstream's is: without it each
// run can finish before the next is claimed, and ten sequential executions
// cannot demonstrate anything about concurrent ones. It has to be long enough
// that the runs genuinely overlap on the worker.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleOwnIdentity sleeps, then reports the run id it was given.
//
// The sleep comes FIRST. Reading the id after the pause is what makes this a
// test of identity held ACROSS a suspension and a resumption, not merely of
// identity at entry -- the resumption is where a host that reconstructs
// context from a pool has to get it right a second time, and it is the point
// at which the other nine runs are certain to have started.
func HandleOwnIdentity(h cleat.HostCalls, holdMs int) (string, error) {
	h.DurableSleepMs(int64(holdMs))

	runID := h.RunID()
	if runID == "" {
		return "", fmt.Errorf("the engine reported an empty run id")
	}
	return fmt.Sprintf(`{"runID":%q}`, runID), nil
}
