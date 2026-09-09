## 3. Three host calls dropped work past the end of replay history

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#835, 2026-09-06)
**Upstream area:** `test_dbos.py` — steps after recovery

`DurableSend`, `DurableScheduleInvoke` and streaming plugin calls returned
success without doing anything when the step index ran past recorded history.
The replay branch never called `exitReplay()`, so genuinely new work took the
replay path and was silently discarded.
