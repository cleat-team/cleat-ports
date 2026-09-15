## 33. A workflow can only ask about its own children, not about an arbitrary workflow — WITHDRAWN, poll_child is not children-only

**Class:** Missing capability — **withdrawn, the capability exists**

**Status:** Withdrawn (2026-09-13, session `cleat-62e3`). Ported as
`tests/test_observe_arbitrary_run.py`. The correction is recorded on cleat#1120.

**The claim below is false.** `cleat_poll_child` is not children-only, so
nothing was missing and the upstream case was portable the whole time.

### What was measured

`PollChild` (`engine/children.go:382`) passes the guest's run id straight to
`childWfStore.GetChildResult`, whose query carries no parentage predicate in any
dialect:

```sql
-- engine/store_children.go:161 (postgres)
SELECT COALESCE(result, '{}'), status, error_msg FROM workflow_instances WHERE id = $1
-- engine/mysql_store.go:403      ... WHERE id = ? AND tenant_id = ?
-- engine/mssql_signals_promises.go:361  ... WHERE id = @p1
```

The ABI binding (`engine/imports.go:410-419`) reads the id out of guest memory
and calls straight through, filtering nothing. A store-level probe — two
unrelated parents, each with one finished child, one asking for the other's —
returned the unrelated workflow's **full result body** on postgres, mysql and
mssql alike, each dialect running its own known-positive first.

The boundary that does exist is the **tenant**, not parentage. That is
consistent with how cleat scopes everything else, and run ids are UUIDs, so this
is not a tenancy escape and the withdrawal is not reporting one.

### Why it was filed

The name was read as a specification. `poll_child` says `child`, both sides of
this ledger repeated it, and **nobody ran it**. Note what the original entry
says about its own history: the case had first been published as *portable*
"because `cleat_poll_child` appears in a scan for cross-workflow reads and looks
like it covers the case." That first verdict was right. The correction was the
error, and it was applied confidently enough to shelve the case and open an
upstream issue.

The near-miss this was filed as a twin of — `cleat_await_any_child` against
`wait_first` — was a call whose **name matched a capability it did not have**.
This is the same mistake with the polarity reversed: a call whose **name hid a
capability it did have**. Symmetric, and neither is visible without running it.

### What replaced it

`tests/test_observe_arbitrary_run.py` makes the upstream assertion directly: a
run started through the API, asserted to have no `parent_workflow_id`, then read
from inside a different workflow by id. It is now the only test that would
notice if a parentage restriction were ever added — a defensible change that
would silently break any workflow observing a run it did not spawn.

It also pins the negative half. An unknown run id comes back as **`running`**,
not as an error: `GetChildResult` returns a zero `ChildOutcome` with a nil error
for a row it cannot find, so "absent" and "in progress" are indistinguishable to
a guest. The test asserts only that an unknown id is never reported *completed*,
which is the answer an observer would act on.
