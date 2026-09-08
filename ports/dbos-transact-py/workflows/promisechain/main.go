// Package main awaits several promises in sequence, so that later resolutions
// arrive while the workflow is AWAKE handling an earlier one.
//
// It exists to answer a scope question on cleat#953. That defect was measured
// on the signal path: a delivery arriving while the workflow is running matches
// zero rows on the wake update (`status IN ('ready','suspended')`, and a claimed
// workflow is 'running'), and finalize then overwrites any pulled-forward wake
// with the workflow's own timeout.
//
// The identical predicate guards three other wake paths -- promise resolved,
// promise rejected, update dispatched -- but those were identified by READING
// the predicate rather than by measuring. A source read is not a measurement,
// and four plausible hypotheses about this engine have died on contact with one
// in the last two days. So: reproduce it or do not claim it.
//
// The shape mirrors the signal reproduction exactly. Awaiting several in
// sequence means that while the workflow is processing resolution N, the
// resolutions for N+1.. land on a row that is 'running'.
package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePromiseChain creates `count` promises, publishes their ids, and awaits
// each in turn within a TOTAL budget.
//
// A total budget rather than a per-call timeout, for the reason the
// await-signals port learned the hard way: passing the same value to every
// await in a loop gives each call a fresh deadline, so anything that does not
// advance the loop restarts the clock and the assertion becomes unfalsifiable.
func HandlePromiseChain(h cleat.HostCalls, key string, count int, budgetMs int) (string, error) {
	ids := make([]string, 0, count)
	for i := 0; i < count; i++ {
		id, err := h.CreatePromise(fmt.Sprintf("%s-%d", key, i))
		if err != nil {
			return "", fmt.Errorf("create promise %d: %w", i, err)
		}
		ids = append(ids, id)
	}

	// Published before any await, so the test can resolve them all without
	// racing the workflow to discover their ids.
	h.SetQueryState("promises", strings.Join(ids, ","))
	h.SetQueryState("phase", "awaiting")

	giveUpAt := h.Now().Add(time.Duration(budgetMs) * time.Millisecond)

	resolved := 0
	for i, id := range ids {
		remaining := giveUpAt.Sub(h.Now())
		if remaining <= 0 {
			return fmt.Sprintf(`{"key":%q,"resolved":%d,"timedOut":true}`, key, resolved), nil
		}
		_, timedOut, err := h.AwaitPromiseMs(id, int64(remaining/time.Millisecond))
		if err != nil {
			return "", fmt.Errorf("await promise %d: %w", i, err)
		}
		if timedOut {
			return fmt.Sprintf(`{"key":%q,"resolved":%d,"timedOut":true}`, key, resolved), nil
		}
		resolved++
		h.SetQueryState("resolved", fmt.Sprintf("%d", resolved))
	}

	return fmt.Sprintf(`{"key":%q,"resolved":%d,"timedOut":false}`, key, resolved), nil
}
