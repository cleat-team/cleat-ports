# Ports

One directory per upstream project. Coverage figures are honest counts of
upstream test *cases* re-expressed, not files touched — see
[../docs/adding-a-port.md](../docs/adding-a-port.md).

| Port | Upstream | Upstream license | Covers | Status |
|---|---|---|---|---|
| [`dbos-transact-py`](dbos-transact-py/) | [dbos-inc/dbos-transact-py](https://github.com/dbos-inc/dbos-transact-py) | MIT | queues, recovery, failures, concurrency, workflow management | **scaffolded — no tests ported yet** |

## Planned

| Candidate | Upstream license | Why it is worth porting |
|---|---|---|
| `samples-go` | MIT | ~90 sample workflows, 67 test files. Core already ports one of these by hand (`examples/saga-temporal-port`), and it yielded six findings. |

## Deliberately not here

| Upstream | Reason | Where it goes instead |
|---|---|---|
| [temporalio/features](https://github.com/temporalio/features) | **No LICENSE file** — all rights reserved | Reimplement from its per-feature spec READMEs into `cleat-team/cleat`'s `tests/conformance/` |
| [PeerDB-io/peerdb](https://github.com/PeerDB-io/peerdb) | AGPL-3.0 | GitHub fork under `cleat-team/`, keeping AGPL |
| [flexprice/flexprice](https://github.com/flexprice/flexprice) | AGPL-3.0 | GitHub fork under `cleat-team/`, keeping AGPL |

See [../docs/licensing.md](../docs/licensing.md) for why.
