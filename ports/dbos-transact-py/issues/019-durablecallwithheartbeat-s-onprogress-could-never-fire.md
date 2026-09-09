## 19. `DurableCallWithHeartbeat`'s `onProgress` could never fire

**Class:** Design difference, resolved as removal · **Status:** Promoted (cleat-team/cleat#854, PR #881, 2026-09-07)
**Upstream area:** `test_failures.py` — long-running step heartbeats

The WIT interface's `durable-call-heartbeat` takes four parameters and never had
a progress channel, so the SDKs exposed a callback the ABI cannot deliver. Inert
in compiled workflows, `localdev` and `cleattest` alike. Removed rather than
wired: the guest is suspended inside the import for the whole call, so there is
no moment at which the host could run guest code.
