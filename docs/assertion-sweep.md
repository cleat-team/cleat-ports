# What the assertion sweep measured, and what it did not

**Date: 2026-09-10. Against `develop` at `9f2aa794`, cleat at `79ed88df`.**

The question: **of the tests in this repo, how many actually assert anything?**

It was asked because three defects in one day all had the same shape — a check
that reported success without checking:

| | |
|---|---|
| [#172](https://github.com/cleat-team/cleat-ports/issues/172) | an assertion that **ran** and could not distinguish the two behaviours it named — both produced the same fixture call count |
| [#173](https://github.com/cleat-team/cleat-ports/pull/173) | `worker.sh crash` **exited 0 after killing nothing**, turning five recovery tests into no-crash controls that passed |
| [#175](https://github.com/cleat-team/cleat-ports/issues/175) | `start_fixture` **adopted any healthy fixture**, so 29% of the Python suite could read another session's counters |

If those were the pattern rather than the exception, adding coverage would be
building on sand. **They are the exception.** Both halves came back clean.

## Result

| port | cases | method | vacuous found |
|---|---:|---|---:|
| `dbos-transact-py` | 145 | coverage over the test files, plus run outcomes | **0** |
| `samples-go` | 46 | guard instrumentation, executed | **0** |
| `durabletask-go` | 10 | guard instrumentation, executed | **0** |

## Python: 145 cases

Run under `coverage run` with `--source=tests`, so the measurement is which
**assertion lines were reached**, not which product lines were. A test can pass
because an assertion was never executed — a guard not entered, an early return —
and nothing in the pass/fail column reveals it.

**139 passed, 6 skipped. Of the passing tests: 127 with every unconditional
check executed, 1 on a conditional path, 0 suspicious.**

This one is **automated and runs nightly** — `scripts/check-assertions-executed.py`,
enabled by `make test CLEAT_PORTS_COVERAGE=1`. It is falsified in both
directions by `scripts/selftest-check-assertions.py`; see
[#179](https://github.com/cleat-team/cleat-ports/pull/179) for why both
directions were needed.

**Two things it does not count as findings**, both learned by getting them
wrong first:

- `pytest.fail(...)` on a **failure path** — the `else` of a `while/else` that
  broke on success, or a guard on a bad status. Six of the seven tests the first
  version flagged were healthy for exactly this reason.
- A test that **errored** before asserting. Coverage alone cannot tell that from
  a test that passed without asserting, which is why the run's outcomes are
  required and not optional.

## Go: 56 test functions

**Go excludes `_test.go` from coverage by design**, so there is no equivalent of
the above and this was done differently — and it should not be read as the same
strength of evidence.

The question is also different. In Go the idiom is `if wrong { t.Fatal(...) }`,
so the failure call **not** executing is the success case; counting it the way
the Python check does would call every healthy Go test vacuous. What matters is
whether the **guard condition was evaluated**.

Method: a `go/ast` pass emitting every `if` inside a `Test*` function whose body
calls `t.Fatal`/`t.Error`, a marker inserted before each, run in a throwaway
worktree.

**123 guards, 119 reached, 47 tests with every guard reached.** The four
unreached:

- **3** in `Test_SingleSubOrchestrator_Failed`, which skips on cleat#1115.
- **1** in `TestASleepAdvancesTheClockByExactlyTheSleep`, which is **not** a
  finding, and the reason is the method's blind spot below.

### The blind spot, stated rather than buried

The timer test is shaped `if right { return }` followed by failure branches. Its
real assertion is the **success** check — whose body is just `return`, so the
instrumenter never marked it, because it only marks `if`s whose body fails. The
unreached guard is a failure branch that correctly did not run.

**Measured cost of the blind spot: 7 sites.** Six are in `harness_test.go`
helpers, which are not `Test*` functions and were never in scope. The seventh is
that timer test, which was read by hand and is sound.

### Why the Go sweep is NOT in CI

The instrumenter is a one-off. It has the blind spot above, and **a check that
quietly misses a pattern is worse than a measurement someone ran once and wrote
down** — the first reads as a guarantee. This file is that write-down. Anyone
adding an execution-level Go check should handle the success-guard shape first,
and falsify it in both directions the way `selftest-check-assertions.py` is.

## What none of this establishes

- **Not** that the assertions are well chosen. It establishes that they run and
  that they can fail. #172 ran and could not fail, and no coverage tool would
  have caught it — only measuring the engine did.
- **Not** anything about the five capability gaps (no pre-emptive cancellation,
  no queue concurrency limit, no detached handle, no executor identity, no
  per-run timeout). Those are absent semantics, not weak tests.
- **Not** a statement about MySQL or SQL Server. This ran on PostgreSQL.
