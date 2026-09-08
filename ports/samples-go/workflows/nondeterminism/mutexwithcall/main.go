// Package main must NOT build, and it is the control that gives the three
// exempt fixtures beside it their meaning.
//
// It is byte-identical to nondeterminism/syncmutex except for one line --
// h.SetQueryState -- which puts the function in the cleat closure. That single
// difference is what turns a silent build into two E013s, and it is the whole
// evidence for cleat#949.
//
// Without this fixture, "the mutex workflows build" would be equally explained
// by the analyzer not implementing E013 at all.
package main

import (
	"sync"

	"github.com/cleat-team/cleat/cleat"
)

// Identical to the refused-workflow fixture except for one host call, which is
// the only variable under test.
func HandleMutexWithCall(h cleat.HostCalls, key string, unused int) (string, error) {
	var mu sync.Mutex
	mu.Lock()
	defer mu.Unlock()
	h.SetQueryState("phase", "running")
	return key, nil
}
