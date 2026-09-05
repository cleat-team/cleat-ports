# Adding a port

## Before you start

Read [licensing.md](licensing.md) and confirm the upstream is permissively
licensed. If it is copyleft, or has no LICENSE file, it does not belong here and
that document says where it does belong.

## Scaffold

```bash
make new-port PORT=<name>       # copies ports/TEMPLATE/ to ports/<name>/
```

Name the port after its upstream repo (`dbos-transact-py`, `samples-go`), not
after what it tests. One directory per upstream.

## Fill in the three required files

- **`UPSTREAM`** — project, URL, license, and the exact upstream commit the port
  was derived from. Pin the commit: "derived from main" is not reproducible, and
  when upstream changes an assertion you need to know which version you matched.
- **`README.md`** — which upstream tests this port covers, which it deliberately
  skips, and why. The skip list is the honest part; a port that quietly covers a
  third of the upstream suite while reading as complete is worse than no port.
- **`ISSUES.md`** — starts empty. Findings accumulate here, then get promoted per
  [promotion-checklist.md](promotion-checklist.md).

## Write the port

Port **assertions**, not code. Read what the upstream test pins down, then write
cleat code that pins down the same behaviour. Use the concept mappings already
in the core repo's `docs/migration/from-dbos.md`, `from-temporal.md`, and
`from-restate.md` — and when a mapping there turns out to be wrong, that is
itself a finding worth recording.

Prefer upstream tests that assert **engine** behaviour over ones that assert
application logic. For a DBOS port that means `test_queue.py`, `test_failures.py`,
`test_concurrency.py`, and `test_workflow_management.py` before
`test_fastapi.py`. Business-logic assertions port at the same cost and tell you
almost nothing about cleat.

## Make it runnable

Every port must expose these three targets to the top-level Makefile, via a
`Makefile` in the port directory:

```make
setup:   ## install port dependencies
test:    ## run the port against the installed cleat toolchain
clean:   ## remove build artifacts
```

`make port PORT=<name>` runs `setup` then `test`. CI runs exactly that, so if it
works locally it works in CI.

## Register it

Add a row to the table in `ports/README.md`, including an honest coverage
figure. Then open the PR.
