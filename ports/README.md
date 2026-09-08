# Ports

One directory per upstream project. Coverage figures are honest counts of
upstream test *cases* re-expressed, not files touched — see
[../docs/adding-a-port.md](../docs/adding-a-port.md).

| Port | Upstream | Upstream license | Covers | Status |
|---|---|---|---|---|
| [`dbos-transact-py`](dbos-transact-py/) | [dbos-inc/dbos-transact-py](https://github.com/dbos-inc/dbos-transact-py) | MIT | queues, recovery, failures, concurrency, workflow management | **73 cases, 70 passing, 3 skipped** (2026-09-07) — 23 findings, 18 fixed |
| [`samples-go`](samples-go/) | [temporalio/samples-go](https://github.com/temporalio/samples-go) | **Apache-2.0** | a different engine's assumptions: signals, queries, timers, child workflows, saga compensation | **32 cases, 28 passing, 4 skipped**; 24 of them on all three dialects (2026-09-08) — 10 findings |

## Planned

Nothing queued. `samples-go` moved to the table above on 2026-09-07.

## Deliberately not here

| Upstream | Reason | Where it goes instead |
|---|---|---|
| [temporalio/features](https://github.com/temporalio/features) | **No LICENSE file** — all rights reserved | Reimplement from its per-feature spec READMEs into `cleat-team/cleat`, as a test in the package it guards |
| [PeerDB-io/peerdb](https://github.com/PeerDB-io/peerdb) | AGPL-3.0 | GitHub fork under `cleat-team/`, keeping AGPL |
| [flexprice/flexprice](https://github.com/flexprice/flexprice) | AGPL-3.0 | GitHub fork under `cleat-team/`, keeping AGPL |

See [../docs/licensing.md](../docs/licensing.md) for why.
