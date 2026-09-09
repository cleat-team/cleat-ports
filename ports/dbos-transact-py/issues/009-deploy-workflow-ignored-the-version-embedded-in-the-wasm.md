## 9. `deploy-workflow` ignored the version embedded in the WASM

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#861, 2026-09-07)
**Upstream area:** none — found standing up the multi-dialect harness

It auto-incremented unconditionally, so redeploying changed bytes wrote a
version the binary did not report, and the engine's run-time version check
rejected it.
