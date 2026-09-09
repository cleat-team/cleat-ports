## 6. A completing child rewrote its parent's event and left the checksum stale

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#846, 2026-09-06)
**Upstream area:** `test_dbos.py` — child workflows

The child wrote its result into the parent's recorded `await_child` event
without recomputing the chained checksum, so the parent failed its next segment
with a checksum mismatch. Covered by
`test_children.py::test_awaiting_one_child_survives_the_parent_suspending`.
