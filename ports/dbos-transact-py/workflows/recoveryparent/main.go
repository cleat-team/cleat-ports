// Package main is the parent workflow for the child-across-recovery test.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleRecoveryParent spawns one child, sleeps long enough for its worker to
// be killed mid-flight, and then awaits the child it already started.
//
// The child is `retrycall`, reused rather than written fresh, because it
// already calls the fixture service under a caller-chosen key and the fixture
// counts calls per key (scripts/fixture-service.py). That count is the whole
// instrument: it makes a SECOND child observable, which is the thing this test
// exists to detect.
//
// Why a child rather than another durable call. test_recovery.py already
// proves a completed durable CALL is served from history rather than repeated.
// A child workflow is a different mechanism -- the parent records a run id and
// later awaits it, rather than recording a result -- so nothing about the call
// case implies the child case. A replayed parent that re-runs ChildWorkflow
// from step 0 without consulting history would start a second, real, separate
// workflow, and the first one's work would already have happened.
//
// The sleep sits BETWEEN the spawn and the await deliberately. Crashing before
// the spawn leaves nothing to duplicate and the assertion holds vacuously;
// crashing after the await means the parent has already finished the part
// under test. The window has to contain the crash and nothing else.
//
// failStatus is passed explicitly even though 0 is its default. An omitted int
// parameter binds its zero value, so this would work either way -- but a
// payload that names every parameter cannot be quietly wrong about any of
// them, and cleat#1046 spent two hours demonstrating the cost of relying on
// the defaulting rule. See conftest._ENTRY_PARAMS.
func HandleRecoveryParent(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	runID, err := h.ChildWorkflow("retrycall", fmt.Sprintf(
		`{"service":"flaky","key":%q,"attempts":1,"intervalMs":50,"failTimes":0,"failStatus":0}`,
		key))
	if err != nil {
		return "", fmt.Errorf("spawn: %w", err)
	}

	h.DurableSleepMs(int64(sleepMs))

	result, err := h.AwaitChild(runID)
	if err != nil {
		return "", fmt.Errorf("await: %w", err)
	}

	return fmt.Sprintf(`{"runID":%q,"child":%s}`, runID, result), nil
}
