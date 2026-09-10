## 25. A workflow's timeout is a worker-wide flag, not a per-run value

**Class:** Missing API
**Upstream test:** `tests/test_queue.py` — `test_unsetting_timeout`,
`test_timeout_queue_recovery`, `test_set_workflow_delay`
**Status:** Open

**Filed upstream as cleat#1117** (2026-09-09, session `cleat-5c2b`). The finding
had never reached the engine repo; it exists there now as a question, since
each of these is a plausible design position as well as a plausible gap.

**What upstream asserts**

A timeout is a property of a *run*, set at the call site and inherited by
children:

```python
with SetWorkflowTimeout(2.0):
    DBOS.enqueue_workflow('test_queue', parent, child_one, child_two)
```

`parent` enqueues two children. One is wrapped in `SetWorkflowTimeout(None)`,
which **unsets** the inherited deadline; the other inherits the parent's. The
assertion is that the inheriting child is cancelled when the parent's 2s
deadline passes and the unset one survives to return its own workflow id.

So upstream is asserting three separable things: a timeout can be set per run,
it propagates to children, and propagation can be declined.

**What cleat does**

cleat has exactly one workflow timeout and it is a worker flag:

```
--max-workflow-duration  Maximum wall-clock duration per workflow execution
                         (0 = no limit). Workflows exceeding this are
                         cancelled and fail with a timeout error.
```

reaching the engine as `engine.WithDefaultWorkflowTimeout` at
`cmd/cleat-worker/setup.go:1710`. It applies to every workflow the worker runs.

The start API accepts no timeout. `handleStartWorkflow`'s request body is, in
full:

```go
Input          json.RawMessage `json:"input"`
EntryPoint     string          `json:"entry_point"`
ConcurrencyKey string          `json:"concurrency_key"`
TenantID       string          `json:"tenant_id"`
Namespace      string          `json:"namespace"` // deprecated
Priority       int             `json:"priority"`
```

There is a `timeout_ms` column, which is easy to mistake for the missing
feature and is not it: it is on `event_history`, recording the timeout of an
individual signal-await event, not a deadline for the run.

So none of upstream's three properties has a counterpart. There is no per-run
value to set, nothing to inherit, and nothing to decline — and because the
worker-wide flag applies uniformly, a parent and child always share a deadline
whether or not that is wanted.

**Why this is recorded as one gap rather than three**

`SetWorkflowTimeout(None)` is only meaningful once timeouts propagate, and
propagation is only meaningful once they can be set per run. A port of the
unsetting case cannot be written to fail for its own reason until the first
capability exists, so splitting it would create two entries that can only ever
be closed together.

**Tests**

`tests/test_timeouts.py` holds the assertion, skipped, rather than omitting it:
an absent test is indistinguishable from an untried one, and this is the first
thing a reader comparing the two systems will look for. The suite has no way to
drive `--max-workflow-duration` per test either — `CLEAT_PORTS_WORKER_EXTRA_FLAGS`
(ports#70) could start a worker with one, but a worker-wide deadline would then
apply to every other case sharing that worker.
