## 12. On MySQL, API keys are written to one database and read from another

**Class:** Bug · **Status:** Open (cleat-team/cleat#866, PR #884)
**Upstream area:** none — found running the suite on MySQL

MySQL isolates tenants by database, and the key lookup ran on a tenant-scoped
store while every writer used the base database. `--require-auth` defaults on,
so the HTTP API answered 401 to every request with no key that could work. The
suite failed 40 of 44 on MySQL for this alone.
