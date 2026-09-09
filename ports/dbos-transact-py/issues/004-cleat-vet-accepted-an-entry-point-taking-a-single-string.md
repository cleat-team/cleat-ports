## 4. `cleat vet` accepted an entry point taking a single string

**Class:** Missing API · **Status:** Promoted (cleat-team/cleat#839, 2026-09-06)
**Upstream area:** none — found while porting, in the port's own workflows

A workflow with exactly one string parameter receives the raw input JSON rather
than a named field. That is a rule, not a defect, but nothing warned about it
and it silently produced a key that was a JSON object. Now W003.
