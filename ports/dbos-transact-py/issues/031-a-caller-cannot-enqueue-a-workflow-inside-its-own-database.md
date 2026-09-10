## 31. A caller cannot enqueue a workflow inside its own database transaction

**Class:** Missing API
**Upstream test:** `tests/test_client.py` — 16 cases: `test_enqueue_in_transaction_{commit,rollback,pre_commit_invisible,deduplication,session,session_after_statement,run_sync}`,
`test_send_in_transaction_{commit,rollback,pre_commit_invisible,idempotent,session,session_after_statement,run_sync}`,
`test_send_bulk_in_transaction`, `test_enqueue_and_send_in_transaction`
**Status:** Open — declined on architecture, recorded because it is the single
largest block in the file and was not written down anywhere

**Deliberately NOT filed upstream, and this line exists so nobody re-files it.**
Checked 2026-09-09 while filing the other seven unfiled entries (cleat#1116-1122).
The absence of a `cleat#` reference on an entry usually means the finding never
reached the engine repo; here it means the opposite — see *Why this is recorded
rather than filed as work* below. Closing this needs a client that speaks the
database rather than HTTP, which is a product decision and not a request any
single issue can carry.

**What upstream asserts**

The caller owns a SQLAlchemy connection, opens a transaction, does its own
business writes, and enqueues a workflow *on that same connection*. The enqueue
is then atomic with the caller's work:

```python
with client._sys_db.engine.connect() as conn:
    with conn.begin():
        handle = client.enqueue_in_transaction(conn, options, "tx-commit")
        # ... the caller's own INSERTs ...
# commit -> the workflow exists and runs
```

`test_enqueue_in_transaction_rollback` asserts the mirror: roll back and the
workflow was never created. `test_enqueue_in_transaction_pre_commit_invisible`
asserts the property that makes it worth having — a **concurrent reader must not
see the workflow before the caller's transaction commits**, so nothing can pick
it up and run it against writes that may still be rolled back.

The remaining cases vary the handle rather than the property: a `Session` instead
of a `Connection`, a session that has already issued a statement, `run_sync` from
async code, and the same matrix for `send` plus deduplication and idempotency.

**What cleat has**

Nothing this could attach to, and the reason is the client boundary rather than a
missing feature. `POST /api/workflows/{name}/start` is HTTP; the caller holds no
connection to cleat's database and cleat exposes no transaction to join. The
write happens in `StartNewRun` inside the worker's own transaction
(`engine/store_lifecycle.go:789`, `BeginTx`), which has already committed by the
time the caller reads the 201.

So the outcome upstream forbids is cleat's normal one: the run is visible and
claimable the moment `start` returns, whatever the caller does next. A caller that
needs the two to be atomic has to invert the order — commit its own work first,
then start the workflow, and accept that a crash between them loses the start.

**This is NOT the `@DBOS.transaction` gap already recorded**, and the two are easy
to merge because both bottom out on "cleat has no SQL transaction to share" and
both happen to be 16 cases.

| | `@DBOS.transaction` | this |
|---|---|---|
| who runs the SQL | the **workflow**, inside a step | the **caller**, outside cleat entirely |
| what is missing | guest code cannot reach a database from WASM | the client cannot enlist in a caller's transaction |
| recorded at | `docs/migration/from-dbos.md:386` (§2) | here |

`grep -inE "enqueue_in_transaction|send_in_transaction"` over
`docs/migration/from-dbos.md` returns nothing; §2 there is explicitly about
workflow code — *"Cleat workflows run in WASM and cannot access databases
directly"* — and says nothing about the client.

**Why this is recorded rather than filed as work**

Closing it means a client that speaks the database rather than HTTP, which is a
different product decision from any single API. It is written down because
**16 of this file's 57 cases decline on it**, and until now a reader asking "why
is `test_client.py` only 8 covered" had nothing to find:
`grep -n "test_client.py" ISSUES.md` returned nothing before this entry.

The one case worth revisiting if the boundary ever moves is
`test_enqueue_in_transaction_pre_commit_invisible`. The others assert plumbing;
that one asserts a visibility rule, and cleat would need an answer to it the day
a transactional start existed.
