// Package main is the workflow that reads three signals and reports the order.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSignalOrder announces itself, then awaits three signals and returns
// what arrived, in the order it read them.
//
// The first await names ONE signal ("topic") and the next two name a different
// one ("queued"). That shape is the whole assertion: the test sends a `queued`
// signal FIRST and the `topic` signal second, so an engine that hands each
// await whatever arrived earliest -- rather than what it asked for -- gives the
// first await the wrong payload.
//
// The announcement is a durable call keyed by `key`, so the test can wait for
// the receiver to be running before it sends anything. Signals sent before this
// point would be testing early-delivery holding, which is a different question.
//
// The three awaits are WRITTEN OUT rather than folded into a helper closure.
// cleat's determinism analyzer rejects function-value calls it cannot resolve
// statically (E009, "function-value calls cannot be statically resolved"), and
// a `read := func(name string)` helper trips it three times. The repetition is
// the price of a call graph the analyzer can walk.
func HandleSignalOrder(h cleat.HostCalls, key string, timeoutMs int) (string, error) {
	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-waiting")); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	n1, p1, timedOut, err := h.DurableAwaitSignals([]string{"topic"}, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("await topic: %v", err)), nil
	}
	if timedOut {
		return `{"outcome":"timedout","at":"topic"}`, nil
	}

	n2, p2, timedOut, err := h.DurableAwaitSignals([]string{"queued"}, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("await queued 1: %v", err)), nil
	}
	if timedOut {
		return `{"outcome":"timedout","at":"queued-1"}`, nil
	}

	n3, p3, timedOut, err := h.DurableAwaitSignals([]string{"queued"}, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("await queued 2: %v", err)), nil
	}
	if timedOut {
		return `{"outcome":"timedout","at":"queued-2"}`, nil
	}

	return fmt.Sprintf(
		`{"outcome":"read","names":[%q,%q,%q],"payloads":[%q,%q,%q]}`,
		n1, n2, n3, p1, p2, p3), nil
}
