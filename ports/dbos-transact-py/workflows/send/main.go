// Package main is the workflow under test for fire-and-forget sends.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSend sends one fire-and-forget request, then suspends.
//
// The sleep is the point, not padding. A durable sleep suspends the workflow
// and the resumed execution replays the body from step 0, so a send that is
// re-executed rather than served from history shows up as a second call at the
// fixture. Without the sleep the body runs once and the test could not tell a
// correct engine from one that repeats sends.
//
// h.DurableSend was unreachable from Go until cleat#806: the method and the
// host export both existed with no wiring between them, so this workflow could
// not have been written. That fix was verified at the import section of the
// compiled binary, which proves the call can be MADE and not that it arrives.
// This is the other half.
func HandleSend(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	if err := h.DurableSend("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key)); err != nil {
		return "", err
	}

	h.DurableSleepMs(int64(sleepMs))

	return `{"sent":true}`, nil
}
