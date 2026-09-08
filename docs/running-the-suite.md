# Running the suite

Notes on the harness, written after runs that produced confident wrong answers.

Everything here has the same shape: **the run completes, reports a result, and
the result is about something other than the code under test.** A crash is easy;
these are not crashes. They are runs that look like evidence.

## A bare `down -v` does not stop profile-gated services

`make deps-down` is `docker compose down -v`. MySQL and SQL Server sit behind
compose profiles, and **a `down` without `--profile` silently leaves them
running.** To actually stop everything:

```sh
docker compose --profile mysql --profile mssql down -v
```

Why it matters more than an ordinary bug: a container you believe is cold and
that is in fact seventeen hours old is **unfalsifiable from inside the run**.
Every result is consistent with it. There is no assertion that fails, no error
in a log, and no way to tell the difference by reading output — the run is
simply answering a question about a different database than the one you think
you built. The failure surfaces later as an unreproducible result, or worse, as
a green run you trust.

If a migration landed since the container started, the symptom is a wall of
identical failures — `column "..." does not exist` on every workflow. One such
run produced 375 failures, none of them real.

## Stop the worker before tearing down its database

The worker binds port 8099 and `scripts/worker.sh` reuses a live one:

```
worker already serving http://127.0.0.1:8099 (pid 27599)
```

That is a feature across ports in one run, and a trap across runs. Tear the
databases down without stopping the worker and the next run inherits a worker
holding connections to a database that no longer exists. Every deploy fails with
`connection refused` — pointing at the network, which is fine, rather than at
the process, which is not.

`make worker-down` first, always. Order is: worker down, databases down,
databases up, then run.

## Do not truncate the output

`make all-ports | tail -25` is the most dangerous line in this document.

`all-ports` runs each port and continues past failures, so the summary for the
first port scrolls off while the second port's output survives. What remains
looks complete. One such read showed `samples-go` failing and had already
discarded the fact that **every deploy in the run failed with `connection
refused`** — the cause was in the part that was thrown away, and the part that
survived pointed squarely at innocent code.

A truncated result is worse than a broken one. A broken run looks wrong; a
truncated run looks like a finding. Write the full log to a file and grep it:

```sh
make all-ports DIALECT=$d > "$OUT/$d.log" 2>&1
grep -E '^--- (dbos-transact-py|samples-go):|passed,|--- FAIL' "$OUT/$d.log"
```

## Decide a run finished from the task, never from its output file

Every other entry here is about a run that produced the wrong answer. This one
is about reading a run that has not produced an answer yet, and it caught two
sessions in one night.

`go test` buffers and writes at the end, so a `grep -c` over its output while it
is still going returns **0** — and:

    0 matching events  +  0 failures  =  exactly what a clean completed run looks like

The empty file does not look empty. It looks like success. One session reported
"zero events across the whole suite, zero failures" from a file that was 0 bytes
with two `go test` processes still running.

**This is the same defect as *Do not truncate the output* above**, and the two
belong together: in both, nothing in the pipeline carried the run's completion
state, so a partial read and a final read were indistinguishable at the point of
reading. Truncation throws away part of a finished run; this throws away the
distinction between finished and not. Either way the result is well-formed and
looks like a finding.

The discipline already exists for CI and is worth pointing at your own jobs.
Nobody trusts `gh pr checks` to have listed every check; you gate on a total, or
on `mergeStateStatus`, because a check list lies by omission and "no pending"
also matches "never started". The same scepticism belongs on a background run
you started yourself:

  - wait for the task to **report completion**, then read the file
  - or have the command write a sentinel as its last action, and gate on that
  - never infer "it finished" from "the output contains no failures"

The trap is that this discipline tends to be pointed outward. Careful about
someone else's tooling, credulous about your own.

## Print what is actually running

After bringing databases up, print `docker ps` rather than trusting that `make
deps` returning zero means what you think:

```sh
docker ps --format '  {{.Names}} {{.Status}}'
```

`Up 5 seconds (healthy)` and `Up 17 hours (healthy)` are the same exit code and
completely different runs.

## Never edit any file a run is reading — including the runner itself

`pytest` collects at start, so editing a **test file** mid-run does not affect
the phase already going — it affects **the next dialect**, which collects
afresh. Untested new tests then appear in the middle of a run whose purpose was
to evaluate something else, and their failures are attributed to whatever the
run was testing.

**The worse case is editing the runner script**, and it is worse for a reason
that is not obvious: **bash does not load a script into memory — it reads it
incrementally as it executes.** Inserting lines shifts every byte offset after
the insertion point, so the running interpreter resumes at the wrong place.

Observed on `run-branch.sh` while a three-dialect run was in flight: adding a
guard near the top caused the postgres block to execute a **second** time —
truncating the log the first pass had already written — and the script then died
with

    syntax error near unexpected token `done'

Note what that costs. The re-run overwrote a complete, correct result with a
broken one, so the *evidence* of the first pass was destroyed rather than merely
supplemented, and the second pass's wall of `0.00s` failures looked like a real
collapse. Diagnosing it required reading the whole task output, where the two
`=== postgres: bringing up databases` blocks are the only visible tell.

A test-file edit adds noise to a later phase. **A runner edit corrupts control
flow in the phase already running**, and can destroy the result you were waiting
for.

Save the change as a patch and apply it after. `bash -n <script>` after any edit
confirms it still parses, but it cannot tell you whether something was midway
through reading it.

## A guard whose premise is CI cannot be vouched for locally

`cleat`'s `scripts/check-skip-budget.sh` refuses a raised skip total unless the
ledger names each new skip and why. Run it on a laptop and it errors on lines
that are **correct in CI**: `TestRustAllHostCallsCompiles` expects a skip for
absent cargo, and cargo plus `wasm32-wasip1` are installed on these machines, so
it runs instead.

The ledger describes **CI's environment**. So:

  - a local run can confirm a **new** line does not error
  - it cannot vouch for the **file**

Seeing those two errors locally means your laptop differs from CI, not that the
ledger is wrong. Fixing what they appear to report breaks the file for everyone.

Same shape as the rest of this document, pointed at a guard rather than a test:
the command completes, reports a result, and the result is about a different
environment from the one the guard exists to describe.

**And attribute by NAME, not by delta.** That guard reports a delta, and the
delta can be wrong while remaining self-consistent: one PR added two skips and
CI reported one, because the unattributed count had drifted to 615 against a 616
allowance. Trusting the delta produces a count that agrees with itself and is
wrong about the tree.

## One shared daemon: isolation is now a convention, not a boundary

Until 2026-09-08 each session ran its own colima VM, so container names and host
ports could collide freely -- different network namespaces. Four VMs
pre-allocated **26 GiB** to hold a few hundred MB of database:

    postgres actual working set    69.71 MiB
    the colima VM it sat inside     6    GiB      ~85x

Stopping them returned **371 MB -> 7847 MB** of host memory. Below that line the
worker refuses API starts outright -- `503 worker is under memory pressure` --
so the suite fails wholesale for a reason that is true and has nothing to do
with the code.

On one shared daemon there is **no VM boundary at all**. Set both of these, per
session:

    export COMPOSE_PROJECT_NAME=cleat-ports-<something-unique>
    export CLEAT_PORTS_POSTGRES_PORT=...   # and MYSQL / MSSQL

Nothing enforces either. `engine/testutil`'s `CleanupPostgresTestData` is an
unqualified `DELETE FROM` across a list that includes `workflow_instances`, so a
shared database name is one connection string away from wiping another session's
fixtures mid-test.

**Prefer non-default ports even when the defaults look free.** A stopped colima
VM releases its host forward, so 5442/3309/1436 become available -- and a
restarted one silently takes them back. The compose file already records what
that costs: port 1435 looked free in `docker ps` while a colima SSH forward was
delivering connections to a **different** SQL Server, which failed
authentication against it. `docker ps` answers "is a container bound here"; the
question is "where does a connection to this port actually land".

## Rule out cross-process interference by measuring, not by arguing

The isolation advice that used to live here said to use a dedicated colima
context. That is stale -- see the section above; there is one shared daemon now
and a per-context VM no longer exists to isolate anything.

Cross-process interference is worth ruling out *by measurement* rather than by
argument when a result will not reproduce — read the other process's
environment and compare ports. It is the kind of explanation that fits every
observation, which is exactly why it needs checking rather than assuming, in
both directions: it has been the true cause here, and it has also been the
comfortable wrong answer.

## Several sessions share this checkout; `.port-results` is keyed per run

`COMPOSE_PROJECT_NAME` and per-session database ports isolate the **containers**.
Until 2026-09-08 they isolated nothing else: `.port-results/` was one flat
directory, so every concurrent session shared one `worker.pid`, one
`api-key.<dialect>` and one `worker.log`.

What that does, all measured in one twenty-minute window with three sessions
live:

  * **`worker.sh ensure` stopped a worker belonging to another session.** It
    tests health against *this* session's URL but read the pid from a file
    everyone shared, so it saw "up but not serving", stopped a stranger's
    process, and reported it as restarting its own.
  * **`api-key.<dialect>` went to 0 bytes** while another session was
    authenticating with it — a `mint` that ran with an unset DSN truncated the
    file by redirect before failing.
  * **A session read another's `worker.log` for several minutes.** The only
    tell was `-api-addr 127.0.0.1:8199` where its own worker was on 8109.

**Every one of those surfaces as `401 invalid or revoked API key`** — naming
authentication, which is the one thing that is not wrong. That is the same
shape as the stale-key hazard the Makefile documents, one level up: there the
file's NAME did not distinguish two databases, here its DIRECTORY did not
distinguish two sessions. Two sessions independently diagnosed it as staleness
and moved on.

State now lives in `$CLEAT_PORTS_RESULTS_DIR`, which defaults to
`.port-results/$COMPOSE_PROJECT_NAME` (or `.port-results/default`). Two further
guards, because per-run paths make a mixup unlikely rather than impossible:

  * `worker.sh` refuses to signal a pid whose process is not a `cleat-worker`
    serving this session's `-api-addr`. A pid is a claim about a process; the
    process's own argv is the process.
  * `ensure` refuses to *reuse* a healthy worker on its port when that worker
    is not this project's. Serving is necessary and not sufficient — reusing a
    stranger's worker runs against their database with your key, and fails as
    that same 401.

### Telling the four apart, because they share one symptom

A documented failure mode needs a stated way to distinguish it from its
neighbours, not only a description of itself. The Makefile's stale-key comment
explains its own case completely and correctly — and that is what made it
absorb three cases it does not explain. It supplies a ready, plausible,
locally-correct story, and a sufficient explanation terminates the search.

Every one of these prints `401 invalid or revoked API key`:

| cause | how to tell |
|---|---|
| stale key — database recreated since minting | key file has a value, but no matching row in `tenant_api_keys` for **your** DSN |
| another session rewrote the key file | key file's mtime is recent and **you did not mint it**; the flat layout made this possible at all |
| your worker was stopped by another session's `ensure` | nothing on your `-api-addr`, or a `cleat-worker` there with a `-db` that is not yours |
| you are talking to a stranger's worker on your port | it answers `/healthz`, but `pgrep -fl cleat-worker` shows its `-db` pointing at another database |

The discriminating question is the same in all four: **does the process serving
my API port have my DSN?** One command answers it, and it is worth running
before believing any 401:

```sh
pgrep -fl cleat-worker
```

Ports are still chosen by hand, so `pgrep` is also how to tell your worker from
someone else's before starting anything.

`make clean` removes only this run's subdirectory. A bare `rm -rf
.port-results` would delete every concurrent session's state at once, which is
a worse version of the bug this layout exists to prevent.

## Giving the worker different flags

`scripts/worker.sh` starts the worker with the flags every port needs. A test
that needs a differently-configured worker — a short
`-completed-workflow-retention-days`, a faster `-poll` — had no way to ask, so
that behaviour was unreachable from the suite no matter how the test was
written.

    CLEAT_PORTS_WORKER_EXTRA_FLAGS="-completed-workflow-retention-days 1 -poll 250ms"

The value is word-split, so several flags can be passed and **a value containing
whitespace cannot**. That is the documented limit rather than an oversight: an
array would carry it and an array cannot survive an environment variable, which
is the interface a pytest fixture actually has.

`worker.sh` echoes the extra flags when it starts. A worker started with
different flags is a different worker, and a run that cannot say which one it
had is not reproducible.

Restarting the worker to change flags means stopping it first — `ensure` reuses
a healthy worker and will not notice that you wanted a different one.
