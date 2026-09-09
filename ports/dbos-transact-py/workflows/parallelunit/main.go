// Package main is the workflow under test for the parallel-execution port.
//
// It exists to answer a question nothing else in this port asks: does cleat run
// workflows CONCURRENTLY? The closest existing assertion,
// test_concurrency.py::test_distinct_keys_do_not_block_each_other, asserts that
// two starts under different keys are both admitted and both complete -- which
// a worker executing them one after another satisfies completely. That test was
// written to stop its neighbour passing vacuously and does that job; it was
// never about throughput.
//
// WHY THIS DOES NOT SLEEP, which is the whole design.
//
// The obvious port of upstream's test_max_parallel_workflows is 50 workflows
// that each sleep, asserting the batch finishes faster than serial could. Both
// halves of that are wrong here:
//
//   - DurableSleepMs SUSPENDS the run rather than blocking a worker slot (see
//     workflows/concurrency/main.go, which relies on exactly that). Fifty runs
//     each sleeping 5s complete in about 5s whether the engine runs them one at
//     a time or all at once, because nothing is occupied. A faithful-looking
//     transliteration would be green on a strictly serial engine.
//   - A wall-clock threshold is a comparison between two timings, and
//     cleat-ports#115 is the worked example of one going wrong: 3000ms against
//     4500ms, with a cold run's ~1s overhead landing between the hypotheses.
//
// So the unit of work is a durable call that HOLDS the worker slot for
// delayMs, and the fixture service counts how many such calls are inside its
// handler at once. The assertion is then a direct measurement -- "more than one
// workflow was mid-execution simultaneously" -- with no clock in it. A serial
// engine reports a peak of exactly 1.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleParallelUnit makes one durable call that the fixture holds open for
// delayMs, so that overlapping runs are observable as overlapping calls.
//
// `key` groups the batch: the fixture tracks in-flight count and peak per key,
// so concurrent test runs -- and the two halves of this test -- cannot read
// each other's peak. Every test here mints a uuid for it.
//
// Both parameters are `int`/`string` rather than int64: the generated WASM
// exports pass entry-point integer arguments as `int`, so an int64 parameter
// fails to compile in generated code the author never sees. Same reason
// workflows/concurrency/main.go gives.
//
// The name must begin with Handle -- cleat resolves a run's entry point from a
// `handle_*` export unless the input carries an explicit __entry_point, and
// getting it wrong is a permanent failure at execution, not an error at build
// or deploy time.
func HandleParallelUnit(h cleat.HostCalls, key string, delayMs int) (string, error) {
	req := fmt.Sprintf(`{"key":%q,"delay_ms":%d}`, key, delayMs)

	// A plain DurableCall, with no retry policy: a policy long enough to matter
	// would SUSPEND the run instead of holding the worker (cleat has a test
	// named for exactly that), which would undo the one property this fixture
	// exists to provide.
	resp, err := h.DurableCall("par", "unit", req)
	if err != nil {
		return fmt.Sprintf(`{"outcome":"failed","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	return fmt.Sprintf(`{"outcome":"succeeded","response":%s}`, resp), nil
}
