// Package main is the workflow a cron schedule starts.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCronTarget calls the fixture so a run leaves evidence that outlives the
// workflow's own history, which is purged when it completes.
//
// TWO parameters, deliberately. An entry point whose only parameter is a string
// receives the whole input JSON rather than the field of that name (cleat#824,
// now W003), so a single-parameter version would call the fixture under the key
// `{"key":"..."}` and the test would read a cron that fires as a cron that
// delivers nothing. That happened during the probe this test came from.
func HandleCronTarget(h cleat.HostCalls, key string, tag string) (string, error) {
	h.DurableCall("flaky", "op", fmt.Sprintf(`{"key":%q,"fail_times":0}`, key))
	return fmt.Sprintf(`{"ran":true,"key":%q,"tag":%q}`, key, tag), nil
}
