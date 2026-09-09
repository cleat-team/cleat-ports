## 1. Seven API routes were registered on a table the binary never used

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#830, 2026-09-06)
**Upstream area:** `test_workflow_management.py` — list, cancel, resume

Two route tables existed; the worker served one and seven instance and admin
routes were registered on the other. The endpoints answered the SPA's HTML
fallback rather than 404, so a client saw a 200 with a web page.
