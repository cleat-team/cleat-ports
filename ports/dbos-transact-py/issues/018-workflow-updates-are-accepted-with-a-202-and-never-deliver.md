## 18. Workflow updates are accepted with a 202 and never delivered

**Class:** Missing API · **Status:** Open (cleat-team/cleat#849; implemented across five SDKs)
**Upstream area:** `test_dbos.py` — interacting with a running workflow

Filed as a scheduling bug. It was not: no worker configured an update handler
and no guest exported one, so the feature was unimplemented rather than
misrouted. The original "deliver at a segment boundary" recommendation would
have turned a silent hang into a silent rejection.
