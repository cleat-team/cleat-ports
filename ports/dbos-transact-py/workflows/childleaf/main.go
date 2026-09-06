// Package main is the child workflow used by the fan-out tests.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleLeaf sleeps briefly and reports the tag it was given, so a parent can
// tell which child produced which result.
func HandleLeaf(h cleat.HostCalls, ms int, tag string) (string, error) {
	h.DurableLog("leaf " + tag + ": start")
	h.DurableSleepMs(int64(ms))
	return fmt.Sprintf(`{"tag":%q}`, tag), nil
}
