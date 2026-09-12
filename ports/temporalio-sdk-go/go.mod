// The temporalio/sdk-go port's TEST module. Stdlib only, deliberately, for the
// reason ports/durabletask-go/go.mod gives: the tests drive a running cleat
// worker over HTTP and do not import cleat, so a case is portable here only if
// it has an HTTP-reachable analogue.
//
// The workflows/ directory arrived with the duplicate-start cases and is built
// by scripts/build-workflow.sh, the way the other Go ports do it. It is NOT
// part of this module: the workflow package resolves the cleat SDK from the
// checkout under test, and pulling that dependency in here would let a test
// reach engine internals instead of the HTTP surface.
//
// The schedule cases still start nothing -- both are about the schedule ROW --
// so the split is between cases, not a stage this port has outgrown.
module cleatports/temporaliosdkgo

go 1.25
