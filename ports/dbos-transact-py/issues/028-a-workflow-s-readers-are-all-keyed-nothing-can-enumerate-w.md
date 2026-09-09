## 28. A workflow's readers are all keyed — nothing can enumerate what it published

**Class:** Missing API
**Upstream test:** `tests/test_workflow_management.py` — `test_get_all_events`,
`test_get_all_notifications`, `test_get_all_notifications_null_topic`,
`test_get_all_stream_entries`
**Status:** Open — and see the caveat below, which is a reason to decline these
four cases *independently* of whether cleat grows the capability

**What upstream asserts**

A workflow publishes several values under different keys, and the caller reads
them **all at once**:

```python
DBOS.set_event("key1", "value1")
DBOS.set_event("key2", 42)
DBOS.set_event("key1", "updated")
...
events = dbos._sys_db.get_all_events(wfid)
assert events == {"key1": "updated", "key2": 42}
assert dbos._sys_db.get_all_events("nonexistent") == {}
```

Two properties: last-write-wins per key, and an unknown workflow yields empty
rather than an error. The same shape repeats for notifications and stream
entries, all keyed by `wfid`.

**What cleat has**

Every per-workflow reader takes the key as a required argument:

| | signature | needs |
|---|---|---|
| query state | `GetQueryState(ctx, workflowID, key)` | a key |
| HTTP | `GET /api/workflows/:id/query?key=X` → `{"key":…, "value":…}` | a key |
| signals | `PollSignal(ctx, workflowID, signalName)` | a name |

So a caller who knows a key can read it, and a caller who wants to know *which
keys exist* has no way to ask. `GET /api/instances/:id/state` sounds like the
missing verb and is not — `handleGetInstanceState` returns the
`WorkflowInstance` row, not the published values.

Verified for query state and signals. Streams were not separately checked; they
are asserted here only as the same shape, not as a measured third instance.

**Why this is filed but the four cases are still declined**

All four drive **`dbos._sys_db.*`** — an underscore-prefixed *internal* API, not
DBOS's public surface. A port asserting against it would pin an implementation
detail and then break for reasons that say nothing about either engine. That
holds even if cleat grew enumeration tomorrow, which is why it is the reason to
lead with rather than the capability gap.

The gap is recorded anyway because four cases bottom out on one missing verb,
and the next person reading this file would otherwise re-derive it. See
cleat-ports#95 for the full 44-case reconciliation of that file — 37 of them are
already accounted for by entries 21, 23, 25 and the `fork_workflow` row above.

**What would close it**

An all-keys read per workflow. The store method is the smaller half; the
question worth deciding first is whether cleat wants published state to be
*enumerable* at all, since a keyed-only reader is a deliberate shape in some
designs — a caller must know what it is asking for.
