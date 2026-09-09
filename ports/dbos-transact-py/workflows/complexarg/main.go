// Package main is the workflow under test for complex argument round-tripping.
package main

import (
	"encoding/json"
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// Inner is nested one level deep on purpose: a flat struct would round-trip
// through any encoder that handles a single object, and upstream's
// test_complex_type nests specifically to catch one that does not recurse.
type Inner struct {
	One string `json:"one"`
	Two int    `json:"two"`
}

// Outer holds Inner by value.
type Outer struct {
	Inner Inner `json:"inner"`
}

// HandleComplexArg echoes its arguments twice, either side of a durable sleep.
//
// One run measures both halves of upstream's test_complex_type. The first echo
// is the plain round trip. The second is the recovery half: a durable sleep
// suspends the workflow, and the resumed segment REPLAYS from the top, so the
// argument is decoded again from what the store kept. If the store round trip
// were lossy, `after` would differ from `before` in the same run -- which is a
// stronger statement than comparing either one to the input, because both
// echoes come from the same request and no test fixture sits between them.
//
// `n` is a DIRECT int parameter and `Inner.Two` is a struct FIELD. Both are
// given the same value by the test. They do not bind the same way: struct
// fields are json.Unmarshal'ed, direct ints go through a hand-rolled scanner
// that cannot express a sign (cleat#1036), so a negative pair diverges here
// and nowhere else.
func HandleComplexArg(h cleat.HostCalls, outer Outer, n int, sleepMs int) (string, error) {
	before, err := json.Marshal(outer)
	if err != nil {
		return "", err
	}

	h.DurableSleepMs(int64(sleepMs))

	after, err := json.Marshal(outer)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(`{"before":%s,"after":%s,"n":%d}`, before, after, n), nil
}
