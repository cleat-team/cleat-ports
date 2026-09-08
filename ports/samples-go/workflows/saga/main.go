// Package main is the cleat port of temporalio/samples-go `saga/`: a money
// transfer whose completed steps are compensated in reverse when a later step
// fails.
//
// The core repo already carries a hand-port of this sample at
// examples/saga-temporal-port. That port COMPILES the pattern -- its ISSUES.md
// catalogues six API differences read off the SDK source, none of which was
// ever executed against a running engine. This workflow exists so they can be.
//
// # The shape of this file is a finding, not a style choice
//
// Every step is written out longhand, with the same six-line body repeated,
// because the obvious factoring does not compile. This first version:
//
//	forward := func(op string) func(cleat.HostCalls) (string, error) {
//	    return func(h cleat.HostCalls) (string, error) {
//	        return h.DurableCall("banking", op, req(op, op == failAt))
//	    }
//	}
//	s.AddStep("withdraw", forward("Withdraw"), compensate("WithdrawCompensation"))
//
// is rejected by the workflow analyzer, seven times:
//
//	E009: function-value calls cannot be statically resolved; the analyzer
//	      cannot trace the call chain
//	      -> Replace with a direct function call or inline the logic.
//
// That is a real constraint and it lands awkwardly HERE in particular, because
// cleat's saga API is itself closure-based: AddStep takes two function values
// and Run calls them. So the steps may be written as literals at the AddStep
// call site, and may not be produced by anything. A saga with N steps costs N
// copies of its call shape, and the upstream sample -- which factors its
// activity invocations into a helper -- cannot be ported as written.
//
// Recorded in ../../ISSUES.md rather than worked around silently.
//
// # Where this otherwise differs from upstream
//
//   - Upstream fails its third step unconditionally, via an activity named
//     StepWithError. That proves compensation runs but cannot show the
//     boundary: a saga where nothing fails should compensate nothing, and
//     upstream has no way to say so. Here the failing operation is a
//     parameter, so one workflow serves both.
//
//   - The failure is PERMANENT (the fixture answers 400). A 503 would be
//     TRANSIENT and retried under the step's policy, so compensation would
//     begin only after the retry budget drained, and the test would be
//     measuring the retry policy rather than the saga.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// bankReq builds the fixture request for one operation.
//
// A package-level function, not a local one: a local `req := func(...)` is a
// function VALUE, and calling it is the E009 above. A direct call to a
// declared function is statically resolvable and passes.
func bankReq(key, op, failOp string) string {
	return fmt.Sprintf(`{"key":%q,"fail_permanently":%t}`, key, op == failOp)
}

// HandleSagaTransfer runs a three-step transfer saga against the port fixture.
//
// key                 groups the fixture's call log for one test; must be unique.
// failAt              the forward operation that should fail, "" for none.
// failCompensationAt  the compensating operation that should fail, "" for none.
//
// Parameters bind by their exact Go names, so the caller sends
// {"key": ..., "failAt": ..., "failCompensationAt": ...}.
func HandleSagaTransfer(h cleat.HostCalls, key string, failAt string, failCompensationAt string) (string, error) {
	s := cleat.NewSaga()

	s.AddStep("withdraw",
		func(h cleat.HostCalls) (string, error) {
			return h.DurableCall("banking", "Withdraw", bankReq(key, "Withdraw", failAt))
		},
		func(h cleat.HostCalls) error {
			_, err := h.DurableCall("banking", "WithdrawCompensation",
				bankReq(key, "WithdrawCompensation", failCompensationAt))
			return err
		},
	)

	s.AddStep("deposit",
		func(h cleat.HostCalls) (string, error) {
			return h.DurableCall("banking", "Deposit", bankReq(key, "Deposit", failAt))
		},
		func(h cleat.HostCalls) error {
			_, err := h.DurableCall("banking", "DepositCompensation",
				bankReq(key, "DepositCompensation", failCompensationAt))
			return err
		},
	)

	// Upstream's third step has no compensation, and neither does this one: a
	// saga whose LAST step fails must compensate the two before it and call
	// nothing for itself. A third compensation would make that untestable.
	s.AddStep("notify",
		func(h cleat.HostCalls) (string, error) {
			return h.DurableCall("banking", "Notify", bankReq(key, "Notify", failAt))
		},
		nil,
	)

	if err := s.Run(h); err != nil {
		return "", err
	}
	return fmt.Sprintf(`{"key":%q,"transferred":true}`, key), nil
}
