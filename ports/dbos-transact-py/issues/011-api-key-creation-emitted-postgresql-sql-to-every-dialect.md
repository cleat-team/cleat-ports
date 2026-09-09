## 11. API key creation emitted PostgreSQL SQL to every dialect

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#865, 2026-09-07)
**Upstream area:** none — found running the suite on MySQL and SQL Server

`INSERT INTO admin.tenant_api_keys ... VALUES ($1, ...)` unconditionally. MySQL
has no `admin` schema and read it as a database: `Unknown database 'admin'`.
