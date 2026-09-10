// Package main is a child that either finishes quickly or runs long.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleTerminateLeaf sleeps for sleepMs and reports the tag it was given.
//
// One workflow serves as both of upstream's L1 and L2. L1 is started with a
// short sleep and awaited, so it has COMPLETED before the parent closes; L2 is
// started with a long sleep and never awaited, so it is still running. The
// difference is the input, not the code -- two near-identical fixtures would
// let a divergence hide in whichever one was not read.
func HandleTerminateLeaf(h cleat.HostCalls, tag string, sleepMs int) (string, error) {
	h.DurableSleepMs(int64(sleepMs))
	return fmt.Sprintf(`{"tag":%q}`, tag), nil
}
