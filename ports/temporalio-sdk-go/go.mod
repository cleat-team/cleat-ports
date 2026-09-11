// The temporalio/sdk-go port's TEST module. Stdlib only, deliberately, for the
// reason ports/durabletask-go/go.mod gives: the tests drive a running cleat
// worker over HTTP and do not import cleat, so a case is portable here only if
// it has an HTTP-reachable analogue.
//
// This port has no workflows/ directory yet, and that is a property of the
// cases ported so far rather than a plan. Both assertions here are about the
// SCHEDULE ROW -- whether a second create is refused, and what an omitted
// policy field reads back as -- and neither requires a schedule ever to fire.
// The first case that needs a schedule to start something will need a workflow
// package and scripts/build-workflow.sh, the way the other Go ports do.
module cleatports/temporaliosdkgo

go 1.25
