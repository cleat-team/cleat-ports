## 10. A policy-terminated child recorded no `completed_at`

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#864, 2026-09-07)
**Upstream area:** `test_dbos.py` — child lifecycle

Every retention sweep gates on `completed_at IS NOT NULL`, so those rows were
uncollectable. Rows written before the fix stay exempt — cleat-team/cleat#867.
