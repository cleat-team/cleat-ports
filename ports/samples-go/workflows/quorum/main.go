// Package main awaits a quorum of DISTINCT named signals.
//
// The await-signals port works around the absence of this primitive: its
// HandleAwaitSignals loops over AwaitSignals once per name, because
// AwaitSignalsWithQuorum's minCount counted DELIVERIES rather than distinct
// names and three copies of one signal satisfied a quorum of three.
//
// cleat#1132 recorded that, cleat#1135 fixed it by narrowing the awaited set as
// each distinct name arrives, and this fixture exists so the fix is asserted
// from outside the engine on every dialect rather than only in cleat's own
// package tests.
package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleQuorum awaits `need` distinct signals from the comma-separated `names`.
//
// It reports the names it collected, in arrival order, so a test can tell
// "quorum reached" from "quorum reached by counting one name repeatedly" --
// which is the distinction the fix is about and which a count alone cannot make.
func HandleQuorum(h cleat.HostCalls, key string, names string, need int, timeoutMs int) (string, error) {
	want := strings.Split(names, ",")

	// Announced before the await so a test can wait for the workflow to be
	// parked rather than sleeping. Signals sent before this point would be
	// queued rather than raced, which tests a different thing.
	h.DurableCall("quorum", "waiting", fmt.Sprintf(`{"key":%q}`, key+"-waiting"))

	res, err := h.AwaitSignalsWithQuorum(want, need, -1, time.Duration(timeoutMs)*time.Millisecond)

	got := make([]string, 0, len(res))
	for _, r := range res {
		got = append(got, r.Name)
	}
	if err != nil {
		return fmt.Sprintf(`{"outcome":"timedOut","got":%d,"names":%q}`, len(got), strings.Join(got, ",")), nil
	}
	return fmt.Sprintf(`{"outcome":"quorum","got":%d,"names":%q}`, len(got), strings.Join(got, ",")), nil
}
