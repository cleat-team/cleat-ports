## 23. Nothing can ask cleat to remove a workflow record

**Class:** Defect — filed as cleat#1002
**Upstream test:** `tests/test_workflow_management.py` — 18 of 46 cases, headed by
`test_garbage_collection`, `test_payload_garbage_collection`,
`test_delete_workflow`
**Status:** Open — unportable until cleat#1002 lands, then portable

**18 of 46 cases in this file bottom out on one missing capability**, arriving by
two different routes. Both are recorded here rather than separately because a fix
for either is most of a fix for the other.

**Route one: garbage collection (15 cases).**

DBOS exposes GC as a **callable API** taking a cutoff timestamp and a row
threshold, so a test creates rows, calls GC with a cutoff a millisecond in the
past, and asserts what survived:

    test_garbage_collection                                    the base case
    test_garbage_collection_batched                            parametrized x3
    test_garbage_collection_batched_rows_threshold
    test_garbage_collection_batched_resumable
    test_garbage_collection_batch_size_validation
    test_garbage_collection_collects_rows_that_terminalize_mid_sweep
    test_garbage_collection_spans_every_application
    test_payload_garbage_collection
    test_payload_gc_spares_a_straggler_then_reclaims_it
    test_payload_gc_never_orphans_a_status_row
    test_payloads_survive_while_their_status_row_does
    test_legacy_payload_rows_still_read
    test_retention_lock_key_is_the_cross_sdk_contract

The interesting ones are not "does it delete". They are the **ordering and
partial-failure** cases: a row reaching a terminal state *during* a sweep, a
sweep interrupted and resumed, and payload rows that must never outlive — or
predecease — the status row they belong to.

cleat has the feature and no way to invoke it. `--retention-days` defaults to
**30 and is on by default** (`cmd/cleat-worker/config.go:107`); a second sweep,
`--completed-workflow-retention-days`, defaults to 0 and is opt-in. Both run from
`retentionLoop` (`cmd/cleat-worker/setup.go:2482`) on a **hardcoded 24-hour
ticker with no sweep at startup**, so a worker restarting inside a day never
executes either. The cutoff is computed at day granularity, so no sub-day window
can be requested even in principle.

**This is a defect, and it took checking to be sure of that.** Every background
loop in the worker is tick-first; none pre-runs its sweep. The distinguishing
fact is the interval, not the pattern — the next-longest loop is
`memoryCleanupLoop` at 10 minutes, and retention is 144x that. Tick-first costs
the other seven one period of latency. It costs retention the entire feature on
any worker with a lifetime under a day. Full loop table in cleat#1002.

**Route two: there is no delete endpoint (3 cases).**

    test_delete_workflow
    test_bulk_delete
    test_client_delete_workflow

`DELETE` appears in exactly three places in the worker's API, and none of them
removes a workflow:

| route | what it deletes |
|---|---|
| `DELETE /api/workflows/{def}/routing/{k}` | a routing rule (`server.go:366`) |
| `DELETE /api/workflows/{def}/tags/{k}` | a tag (`server.go:375`) |
| `DELETE /api/schedules/{name}` | a schedule (`server.go:1665`) |

The instance surface is read-only apart from lifecycle: `/api/instances/{id}`,
`/api/instances/{id}/events`, `/api/instances/{id}/state`, all `GET`
(`api_instances.go:28-32`). The admin surface is `force-complete`, `force-fail`,
`re-replay` and `steps/{n}/resolve`, all `POST` (`api_admin.go:41-47`). So the
only mechanism in cleat that removes a workflow record at all is the retention
sweep — which is route one.

**Read the dispatch, not the route table.** `route_table_test.go` lists 18 routes
and omits `POST /api/workflows/{def}/start`, which the port suite calls in almost
every test. It is a **sample used by one test**, not the route surface; the real
surface is parsed from path segments in `server.go:297` and `api_instances.go:13`.
Concluding "no delete" from the route table would have been right by luck.

**Assessment**

Distinct from #20 and #22, and the distinction is why it is filed separately:

| | why unportable | can it be retired |
|---|---|---|
| #20 queues | cleat has no work queues | no — different architecture |
| #22 concurrency | analyzer refuses the constructs | **never** — no design could pass |
| **#23 removal** | **the machinery exists; nothing can call it** | **yes — cleat#1002** |

These eighteen are **blocked, not out of scope**. Two changes to `retentionLoop`
— one sweep at startup, and the interval as a flag — make the fifteen GC cases
portable without adding a feature, because the sweep already does what upstream
asserts. The three delete cases need a genuinely new endpoint, but one whose
implementation already exists as `DeleteCompletedWorkflows`. Written down so that
when cleat#1002 closes, the next session finds a work-list rather than
re-deriving one.

**What the port can observe today, and why it is not worth a test yet.**
`cleat_retention_last_run_timestamp` (`monitoring/prometheus/metrics.go:536`) is
exported on `/metrics` and set only at the end of a sweep, so a port could assert
it stays unset. That asserts the bug rather than the behaviour, and would have to
be deleted the day cleat#1002 lands — the opposite of the self-retiring skip this
suite prefers, where a test written to skip on a known defect starts passing when
the defect is fixed with nobody editing it.

**Method:** upstream figures are by collection, not by grep. A name grep of the
GC family gives 13: `test_garbage_collection_batched` is parametrized x3, and two
more cases join the family on reading rather than on their names. cleat#1002 was
filed with the grep estimate of ~14 and is corrected there. The cleat column is
read from `setup.go`, `config.go`, `server.go`, `api_instances.go` and
`api_admin.go` with line numbers.

**Not established:** whether the two sweeps are correct when they *do* run.
Nothing here tests the deletion logic — only that it is unreachable. The ordering
cases upstream cares most about, a row terminalizing mid-sweep and an interrupted
sweep resuming, are unexamined in cleat and may well be where the real defects
are.
