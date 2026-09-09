// The durabletask-go port's TEST module. Stdlib only, deliberately.
//
// The tests drive a running cleat worker over HTTP and through the harness
// scripts; they do NOT import cleat. That rule is inherited from
// ports/samples-go and it is load-bearing here rather than stylistic: several
// of upstream's backend-contract cases have a tempting cleat analogue at the
// STORE level (engine.NewPostgresStore is exported, so a port could drive
// ClaimWorkflow and ReleaseWorkflow directly), and reaching for it would make
// this port a unit test of the engine's internals wearing a port's name.
//
// The consequence is a real constraint on what is portable here, and it is
// stricter than "cleat has something in this area": a backend-contract case is
// portable only if it has an HTTP- or harness-reachable analogue. See
// README.md, which records the cases that fail that test and why.
//
// The WORKFLOWS under workflows/ are not part of this module. They are staged
// into the cleat checkout and compiled to WASM by scripts/build-workflow.sh.
module cleatports/durabletaskgo

go 1.25
