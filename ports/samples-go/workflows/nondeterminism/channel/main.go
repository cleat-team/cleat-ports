// Package main must NOT build. Channels without a goroutine: the coordination
// half of the same pattern, isolated so a failure cannot be attributed to the
// `go` statement.
package main

import "github.com/cleat-team/cleat/cleat"

func HandleChannel(h cleat.HostCalls, key string) (string, error) {
	ch := make(chan string, 1)
	ch <- key
	return <-ch, nil
}
