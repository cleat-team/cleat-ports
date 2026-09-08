// Package main SHOULD not build and currently does. It is cleat#949's sharp
// case.
//
// The entry point makes a host call, so it is in the cleat closure and IS
// checked -- and it suspends and replays. The helper it calls makes no host
// call, so it is outside the closure and is not checked, while being
// re-executed on every replay: replay re-runs the workflow function and
// constrains only the results of host calls, not local computation.
//
// The helper carries six violations across three codes -- goroutines (E001),
// channel send, receive and close (E002), sync.Mutex and sync.WaitGroup (E013)
// -- and the build reports none of them.
package main

import (
	"sync"

	"github.com/cleat-team/cleat/cleat"
)

// nonDeterministicHelper makes no host call, so it is not in the cleat closure
// -- but it is called from workflow code that IS replayed, and its result is
// returned as the workflow's result.
func nonDeterministicHelper(key string) string {
	var mu sync.Mutex
	results := make(chan string, 2)
	var wg sync.WaitGroup
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			mu.Lock()
			defer mu.Unlock()
			results <- key
		}(i)
	}
	wg.Wait()
	close(results)
	out := ""
	for r := range results {
		out += r
	}
	return out
}

func HandleHelperEscape(h cleat.HostCalls, key string, unused int) (string, error) {
	h.SetQueryState("phase", "running")
	return nonDeterministicHelper(key), nil
}
