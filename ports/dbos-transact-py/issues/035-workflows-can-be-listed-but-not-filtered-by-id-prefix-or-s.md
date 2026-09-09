## 35. Workflows can be listed but not filtered by id prefix or start time

**Class:** Missing capability

**Status:** Open

**Being filed upstream by session `cleat-5c2b`, 2026-09-09.** Claimed here rather
than over a side channel: an offer that lives only in a message is invisible to
the next reader, who finds a case that looks unclaimed. If no `cleat#` reference
appears on this entry, the filing did not happen and it is free to take.

Upstream's `test_send_recv_temp_wf` spends most of its assertions on
`DBOS.list_workflows(...)` with `workflow_id_prefix` and `start_time` filters,
including that a `start_time` in the future returns nothing.

cleat lists workflows (`GET /api/workflows`, covered by
`test_api_surface.py::test_the_workflow_list_contains_a_run_that_was_started`),
and `engine.WorkflowFilter` is:

```go
type WorkflowFilter struct {
    Status        string
    InputContains string
    ErrorContains string
    Search        string
    Offset        int
    Limit         int
}
```

No id prefix, no time window. `Search` is not a substitute: it is a different
predicate over different columns, and asserting against it would be asserting
something upstream does not claim.

**The send/recv half of that upstream case is already covered here** by
`test_send.py::test_a_fire_and_forget_send_reaches_the_service`. Only the
listing half is blocked, which is why this entry is about listing and not about
send.
