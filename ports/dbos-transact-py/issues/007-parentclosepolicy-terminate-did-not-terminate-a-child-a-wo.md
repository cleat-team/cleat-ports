## 7. `ParentClosePolicy TERMINATE` did not terminate a child a worker held

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#848, 2026-09-07)
**Upstream area:** `test_dbos.py` — child lifecycle

The TERMINATE arm marked the row failed but left `assigned_to` set and the
generation unchanged, so the worker holding the child kept running it.
