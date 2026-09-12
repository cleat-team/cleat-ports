// Package main is the workflow the update cases run against.
package main

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// applied records, in arrival order, the name of every update whose HANDLER
// ran. Order is what TestUpdateOrdering asserts and a count alone cannot show.
var applied []string

// HandleUpdates registers the handlers the update cases need and then waits in
// slices, so there are dispatch points to service them at.
//
// TWO APPLY HANDLERS RATHER THAN ONE CALLED TWICE, and that is forced rather
// than stylistic: cleat consumes an update NAME permanently on first use
// (cleat#1330 -- `workflow_update_requests` is keyed by `(workflow_id,
// update_name)` and completion is an UPDATE, not a delete), so the ordering
// case cannot send one name twice the way upstream's does. The divergence is
// asserted directly in updates_test.go rather than worked around silently.
//
// THE WAIT IS 500ms AND NOT A BARE INTEGER. `AwaitSignals` takes a
// time.Duration, and a bare `1000` is 1000 NANOSECONDS -- which cleat#1331
// makes a livelock rather than an error: the SDK guards `timeout <= 0` and then
// truncates with .Milliseconds(), so anything under 1ms reaches the host as the
// 0 the guard exists to reject and the workflow spins forever. cleat's own
// testdata/updatedispatch/main.go writes `1000`. This file says
// `500*time.Millisecond` so that reading it teaches the right thing.
func HandleUpdates(h cleat.HostCalls, marker string, slices int) (string, error) {
	h.RegisterUpdateHandler("apply_one",
		func(payload string) (string, error) {
			applied = append(applied, "apply_one")
			return fmt.Sprintf(`{"handled":"apply_one","position":%d}`, len(applied)), nil
		}, nil)

	h.RegisterUpdateHandler("apply_two",
		func(payload string) (string, error) {
			applied = append(applied, "apply_two")
			return fmt.Sprintf(`{"handled":"apply_two","position":%d}`, len(applied)), nil
		}, nil)

	// The echo handler exists so one case can assert that the caller's PAYLOAD
	// reached the handler. A handler that ignored its argument would satisfy
	// every other assertion here.
	h.RegisterUpdateHandler("echo",
		func(payload string) (string, error) {
			applied = append(applied, "echo")
			return fmt.Sprintf(`{"echoed":%q}`, payload), nil
		}, nil)

	// guarded's validator refuses a payload carrying "reject":true. The handler
	// appends, so a refusal that still ran the handler is visible in the
	// workflow's own result rather than only in the promise.
	h.RegisterUpdateHandler("guarded",
		func(payload string) (string, error) {
			applied = append(applied, "guarded")
			return `{"handled":"guarded"}`, nil
		},
		func(payload string) error {
			if strings.Contains(payload, `"reject":true`) {
				return errors.New("guarded: refused, reject was set")
			}
			return nil
		})

	// boom's handler always fails. Upstream's rejected-update cases assert the
	// caller learns and the RUN survives; a handler error is cleat's nearest
	// equivalent to an update the workflow refuses at handling time.
	h.RegisterUpdateHandler("boom",
		func(payload string) (string, error) {
			applied = append(applied, "boom")
			return "", errors.New("boom: the handler failed on purpose")
		}, nil)

	for i := 0; i < slices; i++ {
		h.AwaitSignals([]string{"never"}, 500*time.Millisecond)
	}

	return fmt.Sprintf(`{"marker":%q,"applied":%d,"order":%q}`,
		marker, len(applied), strings.Join(applied, ",")), nil
}
