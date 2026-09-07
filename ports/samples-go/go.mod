// The samples-go port's TEST module. Stdlib only, deliberately.
//
// The tests drive a running cleat worker over HTTP; they do not import cleat.
// Keeping the dependency set empty means a failure here is a failure of the
// engine or of the port, never of a test-side library version.
//
// The WORKFLOWS under workflows/ are not part of this module. They are staged
// into the cleat checkout and compiled to WASM by scripts/build-workflow.sh,
// which synthesises a go.mod for them so the SDK resolves to the commit under
// test rather than to a published release.
module cleatports/samplesgo

go 1.25
