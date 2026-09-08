// Package main must NOT build. A sync primitive with no concurrency at all --
// the case where the code is in fact deterministic and is refused anyway,
// because the analyzer rejects the primitive rather than proving the absence of
// a race. Included deliberately: it is the boundary of the rule, not a
// violation of it, and a port should record which one the toolchain enforces.
package main

import (
	"sync"

	"github.com/cleat-team/cleat/cleat"
)

func HandleSyncMutex(h cleat.HostCalls, key string) (string, error) {
	var mu sync.Mutex
	mu.Lock()
	defer mu.Unlock()
	return key, nil
}
