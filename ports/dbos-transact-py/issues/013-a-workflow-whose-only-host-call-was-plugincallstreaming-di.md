## 13. A workflow whose only host call was `PluginCallStreaming` did not compile

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#875, 2026-09-07)
**Upstream area:** none — found writing the first streaming-plugin coverage

The generated adapter used `unsafe` without importing it. Any second host call
pulled the import in, so the defect needed a workflow using that call and
nothing else. Nothing in the tree was shaped that way.
