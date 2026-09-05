# cleat-ports

Ports of other durable-execution frameworks' test suites onto [cleat](https://github.com/cleat-team/cleat),
run as an external check on whether cleat actually behaves the way it claims to.

This repo exists because cleat's own tests were written by the people who wrote
cleat, against the semantics cleat happens to implement. A test suite written
for a *different* engine, by people with no knowledge of cleat's internals, asks
a harder question: does cleat do what a durable execution engine is supposed to
do, or only what cleat was built to do?

## What lives here, and what does not

This repo holds ports of **permissively licensed** upstream suites — MIT,
Apache-2.0, BSD. Each port is cleat code written against an upstream test's
*assertions*, with the upstream credited in `NOTICE` and in the port's
`UPSTREAM` file.

| Kind of upstream | Where it goes | Why |
|---|---|---|
| MIT / Apache-2.0 / BSD suites | **here**, under `ports/` | Compatible with this repo's Apache-2.0 license |
| Copyleft (AGPL, GPL) real apps | a **GitHub fork** in `cleat-team/`, keeping the upstream license | Fork preserves history and license; no copyleft code may enter this repo |
| Upstream with **no LICENSE file** | nowhere — reimplement from its prose spec into `cleat-team/cleat`'s `tests/conformance/` | No license means all rights reserved. See [docs/licensing.md](docs/licensing.md) |

`docs/licensing.md` is the binding version of that table. Read it before adding
a port.

## What a port is for

A port's job is **discovery**, not protection. When a port surfaces a real cleat
defect, that defect's permanent home is a hermetic regression test in
`cleat-team/cleat` under `tests/conformance/` — where it gates every merge.
Once promoted, the port has done its job and may go stale without costing
anything.

That handoff is the whole point of this repo, and it is written down as a
checklist: [docs/promotion-checklist.md](docs/promotion-checklist.md).

## Ports

See [ports/README.md](ports/README.md) for the index and current status.

## Running a port locally

```bash
make deps            # start PostgreSQL (pinned to the same image as cleat's dev compose)
make install-cleat   # install the pinned cleat toolchain from cleat-version.env
make port PORT=dbos-transact-py
```

`make install-cleat CLEAT_REF=develop` installs cleat's development branch
instead of the pinned release — which is what nightly CI does.

## How this repo is wired to core

- **Pull requests here** run every port against the **pinned** cleat version in
  `cleat-version.env`. A failure means the port changed.
- **Nightly** runs every port against `cleat-team/cleat@develop`. A failure means
  **cleat** changed, and the run opens or updates a single tracking issue on the
  core repo.
- **`workflow_dispatch`** lets a core PR trigger this suite before merging.

The pin is what makes the signal readable: without it, every failure is
ambiguous between "cleat regressed" and "the port bit-rotted".

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
