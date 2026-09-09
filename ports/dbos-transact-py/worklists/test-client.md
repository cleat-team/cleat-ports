## `tests/test_client.py` — 57 cases, read at `833794f7`

**3 portable · 13 already covered · 6 already a recorded gap · 35 need something
cleat does not have.**

Count reconciled before classifying, by a route independent of the README: 54
`def`s expand to 57 collected cases, because `test_client_enqueue_rejects_empty_workflow_id`
is `@parametrize`d ×3 and `test_set_workflow_id_rejects_empty` ×2. That matches
the inventory table's 57. Checked first because the same discrepancy on
`test_workflow_management.py` was entirely one parametrized case.

### The name census is worthless here, and that is the finding about method

    for nm in <54 upstream names>: grep -rl "$nm" tests/ ISSUES.md README.md

**0 of 54.** Not one upstream name appears anywhere in this port, while the
inventory credits the file with 8 cases. `grep -n "test_client.py" ISSUES.md`
also returns nothing, so the one command that removed two thirds of the
`test_workflow_management.py` job removes none of this one.

That is the inverse of agent1's result (1 name found, 12 actually covered) in a
sharper form, and it settles the rule rather than illustrating it: **a name
census is a lower bound on coverage and never an upper one.** Here the lower
bound is zero and the true figure is 13. Every case below was read.

### Where the 57 go

| bucket | cases | recorded as |
|---|---:|---|
| transactional enqueue / send | 16 | **not previously recorded** — ISSUES 31 |
| DBOS client-library internals | 14 | not an engine assertion; see below |
| already covered here | 13 | table below |
| already a recorded gap | 6 | ISSUES 20, 25; `test_dbos.py` §; #107 |
| mechanism gap, not previously recorded | 5 | otel attributes 3 · send idempotency 1 · caller identity 1 |
| **portable** | **3** | one case, parametrized ×3 |

### The largest bucket is a second transaction gap, and it is not the recorded one

Sixteen cases — `test_{enqueue,send}_in_transaction_*`, `test_send_bulk_in_transaction`,
`test_enqueue_and_send_in_transaction` — enqueue a workflow or post a message
**inside the caller's own SQLAlchemy transaction on the system database**, so the
enqueue commits or rolls back atomically with the caller's business writes.
`test_enqueue_in_transaction_pre_commit_invisible` is the property in one line: a
concurrent reader must not see the workflow before the caller's transaction
commits.

**This is not the `@DBOS.transaction` gap the `test_dbos.py` section records**, and
the two must not be merged — they happen to be 16 cases each, which is exactly the
kind of coincidence that invites it.

| | `@DBOS.transaction` (recorded) | `enqueue_in_transaction` (this) |
|---|---|---|
| who runs SQL | **workflow** code, inside a step | the **caller**, outside cleat |
| what cleat lacks | guest code cannot reach a database from WASM | the client cannot join a caller's transaction |
| recorded at | `docs/migration/from-dbos.md:386` | nowhere — filed as ISSUES 31 |

`grep -inE "enqueue_in_transaction|send_in_transaction" ` over
`docs/migration/from-dbos.md` returns nothing; §2 there is about workflow code
only. cleat's client is HTTP, so there is no connection to enlist and no shape
this could take without a different client.

**Separately, and worth someone checking:** the `test_dbos.py` section says the
`@DBOS.transaction` gap was *"Filed as its own ISSUES entry"*, and
`grep -inE "transaction|sql_session" ISSUES.md` still returns nothing — the same
command that section quotes as its reason for filing. Not acted on here because
it is another section's claim, but the ledger and the work-list disagree.

### DBOS client-library internals — 14

These assert on the Python client object, not on durable execution. cleat's
client is HTTP and has none of these properties, so there is nothing to answer
differently *or* to lack.

**Construction and connection — 6.** `test_client_no_migrate` (the client
migrates the system database), `test_client_bad_url`, `test_client_lazy_defers_connecting`,
`test_client_lazy_connects_on_first_use`, `test_client_lazy_rejects_listen_notify`,
`test_client_no_retry_raises_on_unreachable_database`.

**Delivery mechanism and its performance — 5.** `test_client_no_listener_by_default`
asserts a private attribute is `None`; `test_client_listen_notify_get_event` needs
PostgreSQL `LISTEN`/`NOTIFY`; `test_client_get_event_prompt_delivery` and its async
twin assert `elapsed < 30` to prove the client re-polls;
`test_client_get_event_async_does_not_pin_a_thread_per_wait` asserts 64 concurrent
waits are not capped by `min(32, cpu + 4)` executor threads.

**Neither of the above — 3.** `test_db_retry_connection_error_opt_out` drives a
decorator against a *fake* database class and never touches DBOS at all;
`test_set_workflow_id_rejects_empty` (2 cases) tests a Python context manager's
constructor.

The distinction that matters for the ledger: **none of these is "cleat lacks the
mechanism"**, so none belongs in ISSUES. Filing them there would inflate the gap
with assertions no engine could make.

### Already covered here — 13

Coverage is by assertion, not by name; none of these names appears in the tree.

| upstream | covered by |
|---|---|
| `test_client_enqueue_and_get_result` | `test_api_surface.py` (the run appears in `/api/workflows`) |
| `test_client_enqueue_idempotent` | `test_queues.py::test_the_same_idempotency_key_starts_one_run` |
| `test_client_enqueue_appver_not_set` · `_appver_set` | `test_versions.py::test_the_version_reported_is_the_deployed_one` |
| `test_client_send_with_topic` | `test_api_surface.py::test_a_signal_delivered_over_http_reaches_the_workflow` |
| `test_client_send_no_topic` | `test_send.py::test_a_fire_and_forget_send_reaches_the_service` |
| `test_client_get_event` · `_finished` | `test_query_state.py::test_query_state_is_readable_while_the_workflow_is_suspended` |
| `test_client_get_event_update` · `_update_finished` | `test_query_state.py::test_a_reader_sees_the_current_value_not_the_final_one` |
| `test_client_retrieve_wf` · `_done` | `test_api_surface.py` + `cleat.get` / `await_terminal` |
| `test_enqueue_with_priority` | `test_queues.py::test_priority_is_accepted_and_recorded`, `test_priority_order.py` |

**13 here against the inventory's 8 was not a discrepancy**, and the two
numbers no longer sit side by side. The inventory's figure counted *our* cases
attributed to the file (ports#92); this counts *upstream* cases with a local
equivalent. `test_api_surface.py` has exactly 8 cases and the coverage above is
spread over six files.

Reading one as the other is what the `Cases here` column made easy, and
**ports#134 removed it** for that reason among others. The 13 above is the
figure this survey stands behind.

### Already a recorded gap — 6

`test_enqueue_with_timeout` — ISSUES 25, the timeout is a worker-wide flag.
`test_enqueue_with_deduplication` and `test_client_enqueue_wrong_appver` — ISSUES 20,
both need a queue to sit in (`list_queued_workflows`, status `ENQUEUED`).
`test_client_fork` and `test_client_fork_async` — the fork bucket agent1 opened
in ports#107. `test_client_send_bulk` — the `test_dbos.py` section already
records *no bulk send*, at 5 cases; this is its sixth.

### Mechanism gap, not previously recorded — 5

**otel carrier and caller attributes — 3.** `test_client_enqueue_with_otel_context`,
`_without_otel_context`, `_otel_context_without_active_span`. DBOS stores the
caller's `attributes` dict on the run and, if an otel context is supplied,
injects a `traceparent` carrier beside it. cleat extracts a **trace id only** —
`extractTraceIDFromTraceParent(r.Header.Get("traceparent"))` at
`cmd/cleat-worker/server.go:611` — and there is no per-run attributes bag to put
a caller's own keys in. The middle case is the one worth keeping: absent an otel
context, attributes must survive *unchanged*, which is an assertion about not
corrupting caller data.

**Idempotent send — 1.** `test_client_send_idempotent` posts the same message
twice under one key and asserts one notification row. cleat's `Idempotency-Key`
header is read only by the **start** handler; the signal endpoint takes no key.

**Caller identity on a run — 1.** `test_client_auth` records `authenticated_user`
and `authenticated_roles` on the run and reads them back from the listing. cleat
authenticates a **tenant**, not a user: `auth.TenantIDFromContext` is what the
start handler consults, and nothing records who started a run. `from-dbos.md:378`
states the position — *"Authentication is handled at the host level (API keys,
middleware), not in workflow code"* — so this is a deliberate difference, but the
*record* of it, which is what the test asserts, does not exist either. Related to
ISSUES 26 (nothing records which worker ran a workflow) without being the same
question.

### Portable — 3 · **ported 2026-09-09 · the reading below was WRONG**

One case, parametrized ×3: **`test_client_enqueue_rejects_empty_workflow_id`**,
upstream's #759 — an empty or whitespace id must be *rejected*, not inserted
verbatim, and `_workflow_exists` then confirms nothing was written.

Ported as `tests/test_idempotency_key_form.py` (ports#125), five tests: the three
blank forms, a control, and the mechanism.

#### The prediction, and why it is left here rather than deleted

cleat generates the run id server-side, so the direct analogue does not exist.
The nearest caller-supplied identifier is the `Idempotency-Key` header, and the
guard on it is a bare emptiness test with no trim, on every dialect:

    cmd/cleat-worker/server.go:599   idempotencyKey := r.Header.Get("Idempotency-Key")
    engine/store_lifecycle.go:753    if idempotencyKey != "" {      // postgres
    engine/mysql_lifecycle.go:571    if idempotencyKey != "" {      // mysql
    engine/mssql_lifecycle.go:1074   if idempotencyKey != "" {      // sqlserver

From that, this section predicted: `""` means "no key" and skips the block; `"   "`
is not `""`, so it is hashed and stored as a real key, and two unrelated requests
that both send a blank-but-present key deduplicate onto the same run.

**Every citation above is accurate and the conclusion is false.** Measured
2026-09-09 against a live worker: a whitespace-only key does **not** deduplicate.
Both starts answer `201` with different run ids and no `already_started`.

**The chain has a fourth hop the reading did not have.** Go's `net/textproto`
trims leading and trailing whitespace from header values while parsing the
request, so `"   "` reaches the handler as `""` and never meets the `!= ""` guard.
That is not a check cleat wrote — it is the HTTP library — and the evidence is
`test_whitespace_around_a_key_is_not_part_of_it`: a padded key and a bare key
deduplicate **together**, which can only happen if the padding was removed before
either was stored.

So the property holds and is held up by a layer nobody in cleat chose. It would
stop holding if the key ever moved somewhere that layer does not reach — a JSON
body field, where `!= ""` would be the whole guard. `StartNewRun`'s only two
callers passing a non-empty key are that handler and the scheduler, whose key is
engine-generated, so there is no such path today.

**Why this is written out rather than replaced with the right answer.** Three
correct file:line citations, a chain with no branch in it, and a wrong
conclusion, is the most expensive shape a work-list can carry: the next reader
checks the citations, finds them accurate, and files a defect that does not
exist. The original text said *"stated as read, not run"* and *"deliberately not
filed as a cleat defect until someone runs it"*, and that caveat is the only
reason no bogus issue was filed in the two days it stood. **The caveat did its
job; the citations did not.** Reading a chain end to end cannot find a hop you
did not know to look for.

### Validation

- Partition is total and disjoint over the 54 defs, checked in code:
  no duplicates, none unassigned, no phantom names. Sums to **54 defs / 57
  cases** by both routes.
- The 16-case transactional bucket was selected by name (`"_in_transaction" in n`)
  and then re-derived by **call graph** — every test that calls
  `enqueue_in_transaction` / `send_in_transaction` / `send_bulk_in_transaction`.
  The two sets are identical, in both directions. A name filter over Python
  source is the weakest tool in this repo's collection, so it does not get to
  stand alone.
- `python3 ports/dbos-transact-py/scripts/count-queue-cases.py --check` →
  `README.md inventory tables match the tree`, exit 0. No tests added, so the
  inventory is unchanged by construction.

**A partition that adds up is not a partition that is right** — agent1's summed
to 44/46 in both its wrong and its right version. The call-graph re-derivation is
here because of that, and it is the only independent check this classification
has: unlike `test_workflow_management.py`, there was no prior ISSUES claim to
reconcile against, because ISSUES.md does not mention this file at all.

### What this says about where to go next

Six of the eight upstream files are now surveyed and the shape has not varied:
the per-file numbers are **ceilings**. This one is the most extreme yet — **3
portable of 57**, and the 3 are one parametrized case about input validation.

35 of 57 need something cleat does not have, and 30 of those 35 are one
architectural fact: **DBOS's client is a library holding a database connection,
and cleat's is HTTP.** Transactional enqueue (16), client construction and
connection (6), delivery mechanism (5), and the caller-identity and otel records
(4) are all downstream of it. That is not a backlog; it is a boundary, and no
amount of porting moves it.

---
