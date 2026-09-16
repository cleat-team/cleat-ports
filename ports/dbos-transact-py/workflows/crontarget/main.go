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
//
// `tag` IS OPTIONAL, AND ALWAYS WAS -- this declaration is catching up with the
// callers rather than relaxing anything. It exists to make the parameter count
// two; no caller ever needed it to carry meaning. HandleCronScheduler schedules
// this target with `{"key":...}` and has no tag concept to put there, so every
// firing from that path arrives without one.
//
// Until cleat#1065 an absent `string` bound `""` and the omission was invisible.
// Now an absent declared parameter is refused, so the schedule fired, the run
// was claimed, and the guest rejected the payload -- once a minute, for as long
// as the schedule existed. `*string` is cleat#1065's own spelling for "absence
// is expected here", and it keeps the two-parameter shape the comment above
// requires. Callers that do send a tag -- the misfire and round-trip cases --
// bind it exactly as before. cleat#1705.
func HandleCronTarget(h cleat.HostCalls, key string, tag *string) (string, error) {
	h.DurableCall("flaky", "op", fmt.Sprintf(`{"key":%q,"fail_times":0}`, key))

	// Absent reads as "" so the result shape is unchanged for every existing
	// assertion: before cleat#1065 an omitted tag bound "" and was reported
	// that way, and the tests that omit it do not read the field.
	reported := ""
	if tag != nil {
		reported = *tag
	}
	return fmt.Sprintf(`{"ran":true,"key":%q,"tag":%q}`, key, reported), nil
}
