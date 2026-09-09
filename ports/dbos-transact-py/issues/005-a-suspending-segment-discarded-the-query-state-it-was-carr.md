## 5. A suspending segment discarded the query state it was carrying

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#844, 2026-09-06)
**Upstream area:** `test_dbos.py` — workflow status while running

Query state set before a suspension was lost, so a reader polling a suspended
workflow saw nothing. Covered by `test_query_state.py`.
