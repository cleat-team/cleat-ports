// Package main is the workflow under test for recovery after a worker crash.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleRecovery makes a durable call, sleeps long enough for its worker to be
// killed mid-flight, and makes a second one.
//
// The two calls go to the fixture service under distinct keys, and the fixture
// counts calls per key (see scripts/fixture-service.py). That count is the only
// direct evidence the test needs: a workflow that resumes on another worker
// re-executes its body from step 0, so the question is whether the FIRST call
// is served from history or actually made again.
//
// A count of 1 for the before-key is the durable-execution guarantee itself. A
// count of 2 would mean the payment was taken twice.
//
// Both calls have to be real host calls rather than SideEffects: a SideEffect
// is recomputed and compared on replay, so it would prove nothing about work
// the engine is supposed to NOT repeat.
func HandleRecovery(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	before, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-before"))
	if err != nil {
		return "", err
	}

	// The window the crash happens in. It must outlast the reaper, which
	// needs the heartbeat to go stale before it will reclaim anything.
	h.DurableSleepMs(int64(sleepMs))

	after, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-after"))
	if err != nil {
		return "", err
	}

	return fmt.Sprintf(`{"before":%s,"after":%s}`, before, after), nil
}
