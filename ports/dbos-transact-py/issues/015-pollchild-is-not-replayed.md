## 15. `PollChild` is not replayed

**Class:** Bug · **Status:** Open (cleat-team/cleat#847, PR #871)
**Upstream area:** `test_dbos.py` — child status polling

It re-queries the child live on every execution, so a poll that answered
"running" before a suspension can answer "completed" after it. Resolution:
derive the answer from the parent's durable clock and the child's
`completed_at` rather than recording an event — the rule is that the answer
must be a function of recorded state, not that everything records an event.
