// Package main is the workflow under test for a send issued after a suspension.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSendAfterSleep sends once before a durable sleep and once after it.
//
// The two sends are the same call in the same workflow, differing only in
// which side of the suspension they fall on, which is what makes the pair a
// measurement rather than two assertions. The early one is the control: if it
// stops arriving, the fixture or the harness is broken and the late one proves
// nothing.
//
// The late send is the case that did not work. A resumed segment replays the
// recorded steps with the session still in replay, and DurableSend's replay
// branch returned success for a step past the end of history without recording
// an event or dispatching anything -- so every send after a workflow's first
// suspension was silently dropped. cleat#835.
func HandleSendAfterSleep(h cleat.HostCalls, earlyKey string, lateKey string, sleepMs int) (string, error) {
	if err := h.DurableSend("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, earlyKey)); err != nil {
		return "", err
	}

	h.DurableSleepMs(int64(sleepMs))

	if err := h.DurableSend("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, lateKey)); err != nil {
		return "", err
	}

	return `{"sent":2}`, nil
}
