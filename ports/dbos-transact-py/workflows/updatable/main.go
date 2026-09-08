// Package main is the workflow under test for updates.
package main

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleUpdatable registers an update handler, announces itself, then waits.
//
// An update is the only external interaction that both CHANGES workflow state
// and RETURNS A VALUE to the caller -- a signal is fire-and-forget and a query
// is read-only. Both halves are exercised here: the handler mutates state the
// workflow's own result later reports, and it returns a value the HTTP caller
// reads from the response.
//
// The counter needs no lock, and the toolchain enforces that rather than
// leaving it to judgement: a sync.Mutex here is E013, "workflow code is
// single-threaded by design". The first version of this workflow had one
// defensively and would not compile. A guard giving a better answer than the
// reasoning it refused is the good case.
//
// The wait is a signal await rather than a sleep: the test needs the workflow
// ALIVE and reachable for an unbounded time while it sends updates, and a sleep
// would race the test on duration. The signal is how the test says "stop now".
//
// cleat#849 was filed against this feature when it was accepted with a 202 and
// never delivered -- no worker configured a handler and no guest exported one,
// so it was unimplemented rather than misrouted. Implemented across five SDKs;
// this is the first coverage that goes through a real worker.
// sliceMs is how long each wait lasts before looping. Short enough that an
// update lands promptly, long enough not to spin: every slice is a suspension
// and a resume.
// windowMs is how long the workflow sleeps before its first dispatch point,
// giving the test a deterministic window to create the update in.
const windowMs = 4000

func HandleUpdatable(h cleat.HostCalls, key string, timeoutMs int) (string, error) {
	applied := 0

	h.RegisterUpdateHandler("bump",
		func(payloadJSON string) (string, error) {
			var req struct {
				By int `json:"by"`
			}
			if err := json.Unmarshal([]byte(payloadJSON), &req); err != nil {
				return "", fmt.Errorf("bump: bad payload %q: %w", payloadJSON, err)
			}
			applied += req.By
			// Returned to the HTTP caller, not to the workflow.
			return fmt.Sprintf(`{"total":%d}`, applied), nil
		},
		func(payloadJSON string) error {
			var req struct {
				By int `json:"by"`
			}
			if err := json.Unmarshal([]byte(payloadJSON), &req); err != nil {
				return fmt.Errorf("bump: bad payload %q: %w", payloadJSON, err)
			}
			// The validator's job: refuse before any state changes.
			if req.By <= 0 {
				return fmt.Errorf("bump: by must be positive, got %d", req.By)
			}
			return nil
		})

	// Announce, so the test knows the handler is registered before it sends.
	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-ready")); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	// A durable sleep BEFORE the dispatch point, so the test has a window in
	// which the workflow is alive and has not yet polled.
	//
	// This ordering is the whole design of the test, and getting it wrong cost
	// a wrongly-filed issue. An earlier version waited in 1-second slices and
	// reported "20 slices, 0 applied", which read as twenty dispatch points
	// finding nothing. It was not: generation was 2, so the run suspended ONCE,
	// the remaining iterations ran inside one segment without suspending, and
	// the run finished 0.31s BEFORE the update was even created. There was
	// never a dispatch point after the update existed.
	//
	// So the window is explicit rather than hoped for. The test waits for the
	// announcement, POSTs the update during this sleep, and the AwaitSignals
	// below is then guaranteed to be a dispatch point with the request already
	// pending.
	h.DurableSleep(time.Duration(windowMs) * time.Millisecond)

	// AwaitSignals, NOT DurableAwaitSignals: the wrapper calls DispatchUpdates
	// before suspending (cleat/runtime_signals.go:150) and the primitive does
	// not, so a workflow waiting on the primitive accepts updates and handles
	// none. The SDK says "prefer AwaitSignals" without saying that is what is
	// lost.
	res := h.AwaitSignals([]string{"stop"}, time.Duration(timeoutMs)*time.Millisecond)
	if res.Err != nil {
		return "", fmt.Errorf("await stop: %w", res.Err)
	}

	return fmt.Sprintf(`{"applied":%d}`, applied), nil
}
