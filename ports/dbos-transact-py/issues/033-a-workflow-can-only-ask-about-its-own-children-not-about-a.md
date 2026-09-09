## 33. A workflow can only ask about its own children, not about an arbitrary workflow

**Class:** Missing capability

Upstream's `test_retrieve_workflow_in_workflow` calls `retrieve_workflow(id)`
from **inside** a running workflow, for ids the caller did not spawn, and reads
the status back.

cleat has two guest-side calls that cross a workflow boundary — `cleat_poll_child`
and `cleat_await_child` — and **both are children-only**. Re-derive from the
export list:

```sh
grep -oE '\.Export\("[^"]+"\)' engine/imports.go | sed 's/.*Export("//;s/")//' \
  | grep -iE 'status|retrieve|get_workflow|poll_child|await'
# cleat_await_child cleat_await_all_children cleat_await_any_child
# cleat_poll_child cleat_await_signals cleat_await_promise
```

Nothing takes an arbitrary workflow id and returns its status. The HTTP API can
answer it (`GET /api/workflows/:id`) — the gap is specifically **from inside a
workflow**, where a guest has no client.

**Why this is filed rather than ported around.** The obvious workaround — have
the parent pass the id and use `cleat_poll_child` — silently changes the
assertion. The upstream case is about observing a workflow you are not the
parent of. A port using the child path would pass while testing something else,
which is the failure mode this ledger exists to prevent.

**Worth noting how it was missed.** This case was published as *portable* in
WORKLIST.md, because `cleat_poll_child` appears in a scan for cross-workflow
reads and looks like it covers the case. It is the same near-miss as
`cleat_await_any_child` against `wait_first`, which the same survey caught one
case earlier.
