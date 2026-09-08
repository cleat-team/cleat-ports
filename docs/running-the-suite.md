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

## Print what is actually running

After bringing databases up, print `docker ps` rather than trusting that `make
deps` returning zero means what you think:

```sh
docker ps --format '  {{.Names}} {{.Status}}'
```

`Up 5 seconds (healthy)` and `Up 17 hours (healthy)` are the same exit code and
completely different runs.

## Never edit a test file while a run is executing

`pytest` collects at start, so an edit mid-run does not affect the phase already
going — it affects **the next dialect**, which collects afresh. Untested new
tests then appear in the middle of a run whose purpose was to evaluate something
else, and their failures are attributed to whatever the run was testing.

Save the change as a patch and apply it after.

## Isolate from the other sessions

Several sessions share this machine and run their own databases. Use a dedicated
docker context so a teardown here cannot touch a suite running there:

```sh
export DOCKER_CONTEXT=colima-cleat-ports
```

Cross-process interference is worth ruling out *by measurement* rather than by
argument when a result will not reproduce — read the other process's
environment and compare ports. It is the kind of explanation that fits every
observation, which is exactly why it needs checking rather than assuming, in
both directions: it has been the true cause here, and it has also been the
comfortable wrong answer.
