// Package main is the workflow under test for the concurrency-key port.
//
// Written here rather than borrowed from cleat's testdata/: those fixtures
// exist to serve core's own tests and are free to change shape without regard
// to this repo. A port that depended on one would fail for reasons that have
// nothing to do with the behaviour it is asserting.
package main

import "github.com/cleat-team/cleat/cleat"

// HandleHoldsKey stays alive long enough for a second start to be attempted against
// the same concurrency key.
//
// DurableSleepMs suspends the run rather than blocking a worker slot, which is
// the point: the key must be held by the *run*, not by whichever worker
// happens to be executing it, or the assertion below would only be testing
// that one worker is busy.
// The parameter is `int`, not `int64`, deliberately: the generated WASM
// exports pass entry-point integer arguments as `int`, so an int64 parameter
// fails to compile in generated code the author never sees --
//
//	gen_wasm_exports.go: cannot use Ms (variable of type int) as int64 value
//
// which names a file that does not exist in this package.
//
// The name must begin with Handle. cleat resolves a run's entry point from a
// `handle_*` export unless the input carries an explicit __entry_point, so an
// exported function named anything else deploys and starts happily and then
// fails at execution with
//
//	cannot determine entry point: no __entry_point in input and no handle_*
//	export in WASM binary
//
// -- a permanent failure on the run, not an error at build or deploy time.
func HandleHoldsKey(h cleat.HostCalls, ms int) (string, error) {
	h.DurableLog("holds-key: sleeping")
	h.DurableSleepMs(int64(ms))
	h.DurableLog("holds-key: done")
	return `{"status":"done"}`, nil
}
