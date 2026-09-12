# Ports

One directory per upstream project. Coverage figures are honest counts of
upstream test *cases* re-expressed, not files touched — see
[../docs/adding-a-port.md](../docs/adding-a-port.md).

| Port | Upstream | Upstream license | Covers | Status |
|---|---|---|---|---|
| [`dbos-transact-py`](dbos-transact-py/) | [dbos-inc/dbos-transact-py](https://github.com/dbos-inc/dbos-transact-py) | MIT | queues, recovery, failures, concurrency, workflow management | **79 cases, 76 passing, 3 skipped** (2026-09-08) — 23 findings, 18 fixed |
| [`samples-go`](samples-go/) | [temporalio/samples-go](https://github.com/temporalio/samples-go) | **Apache-2.0** | a different engine's assumptions: signals, queries, timers, child workflows, saga compensation | **41 cases, 39 passing, 2 skipped** (2026-09-08) — 12 findings |
| [`durabletask-go`](durabletask-go/) | [microsoft/durabletask-go](https://github.com/microsoft/durabletask-go) | **Apache-2.0** (verified by reading LICENSE, not by the API) | the backend contract and orchestration lifecycle — the layer no other port here touches | **4 cases, 3 passing, 1 skipped** (2026-09-09) — 2 findings, 1 filed as cleat#1115 |
| [`temporalio-sdk-go`](temporalio-sdk-go/) | [temporalio/sdk-go](https://github.com/temporalio/sdk-go) | MIT | schedule administration, and what a duplicate start says about the run that won | **11 cases, 11 passing, 0 skipped** (2026-09-12) — 4 findings, 3 filed as cleat#1297 (fixed in cleat#1302), cleat#1324 and cleat#1325 |

## Planned

`durabletask-go` moved to the table above on 2026-09-09; its surveys are
`docs/durabletask-go-orchestrations-survey.md` and
`docs/durabletask-go-backend-survey.md`.

## Deliberately not here

| Upstream | Reason | Where it goes instead |
|---|---|---|
| [temporalio/features](https://github.com/temporalio/features) | **No LICENSE file** — all rights reserved | Reimplement from its per-feature spec READMEs into `cleat-team/cleat`, as a test in the package it guards |
| [PeerDB-io/peerdb](https://github.com/PeerDB-io/peerdb) | AGPL-3.0 | GitHub fork under `cleat-team/`, keeping AGPL |
| [flexprice/flexprice](https://github.com/flexprice/flexprice) | AGPL-3.0 | GitHub fork under `cleat-team/`, keeping AGPL |

See [../docs/licensing.md](../docs/licensing.md) for why.
