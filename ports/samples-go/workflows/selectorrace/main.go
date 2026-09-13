// Package main drives cleat's Selector, which no port has touched.
//
// NOT A PORT OF temporalio/samples-go, and not of sdk-go's TestSelectorNoBlock
// either. The cross-port grep that found this gap -- `grep -rli selector
// ports/*/tests/` returning nothing across four ports and ~200 cases -- made
// upstream's selector case look portable, and reading the TEST body supported
// that: execute a workflow, assert a string, no history reads. Reading the
// WORKFLOW it drives did not. `Workflows.SelectorBlockSignal` is built on
// workflow.Go goroutines, two channels, selector.AddDefault, HasPending and an
// activity -- five constructs cleat does not have, three of them refused by vet
// (E001 goroutines, E002 channels). The case is not portable.
//
// What survives is the gap itself: cleat ships a Selector with signal, child
// and timer futures, and nothing anywhere asserts any of it. So this is a
// fixture written against cleat's own API, like workflows/childpriority -- the
// kind of case the four-upstream method cannot produce, because no upstream has
// this shape.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSelectorRace races an optional signal against up to two timers and
// reports which future won and which timer flags were set.
//
// THE SHORT TIMER IS ADDED FIRST AND THAT ORDERING IS THE TEST. cleat#1129 was
// AddTimer assigning rather than appending, so a second call silently discarded
// the first -- "no error, no log, nothing at build time, and a deadline that
// simply never fired", per the comment that now sits on the fixed function.
// Under that bug this fixture keeps only the LONG timer: the short deadline
// never fires, shortFired stays false, and the run takes longMs. Adding them in
// the other order would leave the correct timer in place by accident and assert
// nothing.
//
// Every parameter is always supplied; a zero disables that future rather than
// omitting it, because an omitted int binds to 0 silently and a fixture that
// can be accidentally disabled is not evidence.
func HandleSelectorRace(h cleat.HostCalls, key string, signalName string, shortMs int, longMs int) (string, error) {
	sel := cleat.NewSelector(h)

	var payload string
	if signalName != "" {
		sel.AddSignal(signalName, &payload)
	}

	var shortFired, longFired bool
	if shortMs > 0 {
		sel.AddTimer(time.Duration(shortMs)*time.Millisecond, &shortFired)
	}
	if longMs > 0 {
		sel.AddTimer(time.Duration(longMs)*time.Millisecond, &longFired)
	}

	// Published before Select so a test can distinguish "the workflow is
	// waiting" from "the workflow has not been claimed yet". Without it a
	// signal sent too early and a signal lost look identical -- the same
	// reasoning workflows/awaitsignals gives for its own phase key.
	h.SetQueryState("phase", "waiting")

	started := h.Now()
	winner := sel.Select()
	elapsedMs := h.Now().Sub(started).Milliseconds()

	// fmt.Sprintf("%v", err) rather than err.Error(), because E008 refuses a
	// call through an interface and `error` is one: the analyzer cannot resolve
	// the callee statically, so a workflow may hold an error but not ask it for
	// its message. workflows/abandonvariant reaches for the same formulation.
	errText := ""
	if err := sel.Err(); err != nil {
		errText = fmt.Sprintf("%v", err)
	}

	return fmt.Sprintf(
		`{"key":%q,"winner":%q,"payload":%q,"shortFired":%t,"longFired":%t,"elapsedMs":%d,"err":%q}`,
		key, winner, payload, shortFired, longFired, elapsedMs, errText), nil
}
