module cleatports/parallelunit

go 1.25.11

require github.com/cleat-team/cleat/cleat v0.0.0

// The SDK under test is the clone scripts/install-cleat.sh made, not whatever
// the module proxy serves. Same reasoning as the Python SDK being installed
// with `pip install -e ../../.cleat-src/python-sdk`.
//
// Note the path: the Go SDK is its OWN module, github.com/cleat-team/cleat/cleat,
// not a package inside github.com/cleat-team/cleat. A replace aimed at the
// parent path is silently ignored -- `go mod tidy` then downloads a release
// from the proxy and the port tests that instead, which is the one thing this
// directive exists to prevent, failing without a word.
replace github.com/cleat-team/cleat/cleat => ../../../../.cleat-src/cleat

// The parent module too. Not because this package imports it -- it does not --
// but because the SDK's own tests import github.com/cleat-team/cleat/engine,
// and `go mod tidy` resolves the test dependencies of everything it walks.
// Without this it tries the proxy for a v0.0.0 that does not exist.
replace github.com/cleat-team/cleat => ../../../../.cleat-src
