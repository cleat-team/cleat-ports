# samples-go

Ports of [temporalio/samples-go](https://github.com/temporalio/samples-go)
assertions onto cleat. Apache-2.0; see `UPSTREAM` for the pinned commit and for
how this repo previously recorded the licence wrongly.

## Why this port and not more DBOS

The DBOS port asks whether cleat behaves like a durable execution engine, using
a suite written by people who did not know cleat. This one asks a different
question: **do a different engine's assumptions hold here?**

Temporal's model is not DBOS's. Signals are typed channels rather than a queue
read; queries are a first-class read-only interrogation of running state;
`workflow.Sleep` and timers are engine primitives rather than a durable call;
child workflows carry a parent-close policy; and saga compensation is a
documented pattern rather than a library feature. Where cleat maps cleanly, a
port is cheap. Where it does not, the mapping itself is the finding.

Precedent for the yield: the core repo already ports **one** of these samples by
hand — `examples/saga-temporal-port`, roughly 250 lines — and it produced six
concrete API findings. That is the ratio this port is betting on.

## Upstream shape

At the pinned commit: **83 top-level sample directories, 446 Go files, 67
`_test.go` files.** Upstream tests run against Temporal's own test framework
(`testsuite.WorkflowTestSuite`), which has no cleat equivalent — so what ports
is the **assertion each sample pins down**, not its test harness.

## Priority

Ordered by how much engine behaviour each exercises, not by how interesting the
sample is.

| Upstream area | Priority | Why |
|---|---:|---|
| `saga/` | **1** | compensation on failure — the one already hand-ported, and the six findings came from it |
| `child-workflow/`, `childworkflow-continueasnew/` | **1** | parent/child lifecycle, close policy, continue-as-new inside a child |
| `signal-counter/`, `await-signals/` | **1** | signal delivery and multi-signal await, where Temporal's model differs most |
| `query/`, `query-workflow/` | **1** | query semantics against a running workflow — cleat's `SetQueryState` is a different shape |
| `timer/`, `sleepfor/`, `cron/` | 2 | timers and schedules as engine primitives |
| `retryworkflow/`, `activity-retry/` | 2 | retry policy, already partly covered by the DBOS port |
| `mutex/`, `goroutine/` | 2 | concurrency primitives; cleat forbids goroutines in workflow code (E013) |
| `dsl/`, `expense/`, `pso/` | 3 | application logic; ports at the same cost and tells you less |

## Deliberately not here

- **Anything using Temporal's test framework directly.** `testsuite` mocks the
  service; a port that used it would test the mock. Assertions are re-expressed
  against a real cleat worker over HTTP, the same way the DBOS port does.
- **`encryption/`, `codec-server/`** — Temporal's payload codec is a client-side
  concern with no cleat equivalent surface.
- **`nexus/`** — a cross-namespace RPC feature cleat has no analogue for.
- **`worker-specific-task-queues/`, `sticky-execution/`** — Temporal worker
  topology, not engine semantics.

## Status

**21 cases, 17 passing, 4 skipped** (2026-09-07) — 7 findings, 3 filed, 1 fixed.

Measured green on **PostgreSQL and MySQL**, all 21 on each. One case is
deliberately dialect-aware (cleat#936) and reports a different result on each,
which is the finding; every other case asserts the same thing on both.

Derived, not asserted:

```
$ go test ./tests/ -list '.*' | grep -c '^Test'
21
```

The DBOS port's status line read "scaffolded — no tests ported yet" for two days
while 53 cases existed. Hence the command beside the number.

| upstream area | cases | file |
|---|---:|---|
| `saga/` | 6 | `tests/saga_test.go` |
| `child-workflow/` | 5 | `tests/child_workflow_test.go` |
| `await-signals/` | 6 | `tests/await_signals_test.go` |
| `query/`, `query-workflow/` | 4 | `tests/query_test.go` |

**The four skips are all one defect**, cleat-team/cleat#933 — a single signal
delivery satisfies more than one `AwaitSignals`. They are skipped rather than
inverted, because the assertions are what the sample actually guarantees and
rewriting them to match the defect would mean writing each test twice.
`TestOneDeliveryCurrentlySatisfiesTwoAwaits` pins the defect instead, so the
port notices when it is fixed.

Two of the seventeen are controls on the instrument rather than on cleat
`TestTheFixtureRecordsAFailedCallToo` — every other assertion reads the
fixture's ordered call log, and the entries that matter are calls that
*failed*, so "does the log record a failure at all" has to be checked
separately or the expected sequences would be wrong in a way that looked like
an engine defect. `TestTheChildIsReachableByIdFromOutsideTheParent` — the
child-workflow tests locate the child through the parent's query state, and a
stale or wrong id there would have them reading some other run's status, which
would mostly still pass.
