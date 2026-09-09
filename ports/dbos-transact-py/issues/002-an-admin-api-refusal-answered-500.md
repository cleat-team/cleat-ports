## 2. An admin API refusal answered 500

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#832, 2026-09-06)
**Upstream area:** `test_workflow_management.py`

The HTTP status was derived from the error *message* by substring, so a refusal
that should have been 400/404/409 came back 500. Now classified with
`errors.Is` against explicit sentinel classes.
