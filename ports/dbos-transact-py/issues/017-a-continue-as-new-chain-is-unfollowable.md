## 17. A continue-as-new chain is unfollowable

**Class:** Bug · **Status:** Open (cleat-team/cleat#826; recording half in PR #886, retrieval in #887)
**Upstream test:** `test_dbos.py` — continue-as-new

The caller polls the id it started, sees `done` and `{}`, and the run carrying
the real result is unnamed. Upstream keeps the workflow id across the
transition; cleat inserted a fresh uuid with nothing linking the two.

A second defect had to be fixed before this was even reachable: the old run's
result was written raw into a JSON column, so every continuation died with
`22P02`.
