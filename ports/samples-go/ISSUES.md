# samples-go: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

Empty is the correct starting state. Add entries as you port, not at the end.

---

## 1. Saga steps cannot be factored: the API is closure-based, the analyzer rejects closures

**Class:** Design difference (with a cost worth naming)
**Upstream sample:** `saga/`
**Status:** Open

**What upstream asserts**

Nothing about code shape — but the upstream sample factors its activity
invocations into a helper and calls it from each step, which is how anyone
would write a saga of more than three steps.

**What cleat does**

`cleat.Saga.AddStep` takes two function values, and `Run` calls them. So the
saga API is closure-based by construction. The workflow analyzer, however,
rejects any call through a function value:

```
E009: HandleSagaTransfer:51: function-value calls cannot be statically resolved;
      the analyzer cannot trace the call chain
      -> Replace with a direct function call or inline the logic.
```

Seven of these, from the natural factoring:

```go
forward := func(op string) func(cleat.HostCalls) (string, error) {
    return func(h cleat.HostCalls) (string, error) {
        return h.DurableCall("banking", op, bankReq(op, op == failAt))
    }
}
s.AddStep("withdraw", forward("Withdraw"), compensate("WithdrawCompensation"))
```

The two rules compose into a narrow lane: step bodies **may** be written as
literals at the `AddStep` call site, and **may not** be produced by anything.
A package-level `func` is fine to call *from inside* a literal; a local
`req := func(...)` is not, because calling it is a function-value call.

Note this is not a general ban on function values — `AddStep` receives them
and `Run` invokes them, inside the SDK, without complaint. The analyzer's
reach stops at the workflow package.

**Assessment**

The E009 rule is defensible on its own: an analyzer that cannot trace a call
chain cannot verify determinism, and guessing would be worse. What makes it a
finding is the *interaction*. cleat ships a saga helper whose entire interface
is function values, and then forbids the calling code from constructing them.
An N-step saga costs N copies of its call shape, and `workflows/saga/main.go`
in this port is deliberately left in that shape so the cost is visible rather
than hidden behind a comment.

The upstream sample cannot be ported as written. That is the finding.

---

## 2. `examples/saga-temporal-port/ISSUES.md` is stale on two of its six items

**Class:** Documentation defect in the core repo
**Upstream sample:** `saga/`
**Status:** Open

**What the core repo claims**

`examples/saga-temporal-port/ISSUES.md` #4:

> The `Saga.AddStep` compensate function signature is `func(HostCalls)` — it
> returns no error. This means compensation failures are silently dropped.

and #6, that `Run` wraps a failed step as `saga step %q failed: %w`.

**What cleat does**

Neither holds. `AddStep`'s third parameter is `func(HostCalls) error`, and
`Run` collects compensation failures with `errors.Join` and returns them
alongside the forward error (`cleat/runtime_workflow.go:426`). The wrapping is
`fmt.Errorf("saga: %w", ...)`.

Executed, not read: `TestAFailingCompensationIsReportedNotSwallowed` fails a
compensating call on purpose and asserts (a) the remaining compensations still
run, and (b) the run's error still names the forward failure. It passes.

**Assessment**

The findings were true when written and were never re-checked, which is what
happens to a finding recorded as prose next to code that keeps moving. Worth
noting *how* they went stale rather than just that they did: all six were
derived by reading the SDK source, so the document has no executable component
that could have failed when the signature changed.

The same drift is visible one layer down — the doc comment above `AddStep`
still shows its example compensator as:

```go
func(h HostCalls) {
    h.DurableCall("flights", "Cancel", cancelJSON)
}
```

which would not compile against the function it documents.

This is the argument for the ports repo over a design review: an assertion that
runs tells you when it stops being true.

---

## 3. An unrecognised `parent_close_policy` silently means ABANDON

**Class:** Bug (silent-acceptance)
**Upstream sample:** `child-workflow/`
**Status:** Open

**What upstream asserts**

Temporal's `ParentClosePolicy` is an enum. A value outside it cannot be sent —
the client rejects it — so "the policy I wrote was the policy that ran" is
guaranteed by construction rather than by care.

**What cleat does**

`enforceParentClosePolicy` matches exact string literals, and ABANDON has no
arm at all: it is the *absence* of an update. So any value that is not
`TERMINATE`, `REQUEST_CANCEL` or one of the recognised spellings falls through
to ABANDON, silently.

Measured — a parent started with `parent_close_policy: "terminate"`,
lower-case:

```
 id       | def_name         | status | policy         | parent
 78035b86 | sg_child_sleeper | done   | terminate      | dae873cd
```

Stored verbatim, no error at start, no warning in the log, and the child ran to
completion after its parent closed. `TestAnUnrecognisedPolicyIsTreatedAsAbandon`
pins this as current behaviour, in the same shape the DBOS port used for
cleat#900: if it ever fails because the value was rejected or normalised, that
is the fix landing and the test should be updated rather than deleted.

Three things make the typo easy to write and hard to see:

- `ParentClosePolicy` is a `string` type, so the typed constants are trivial to
  bypass and any string literal compiles.
- The column's DEFAULT is `'ABANDON'`, so a wrong value and a missing value are
  indistinguishable afterwards.
- ABANDON is the safe-looking outcome. The child keeps running, nothing errors,
  and nothing looks wrong until someone asks why the children of terminated
  parents are still alive.

**Assessment**

The failure is silent and it fails *open* — toward children that keep running
rather than children that stop. A validation at the start boundary, or a
warning when the column holds an unrecognised value, would close it. Nothing
about the enforcement itself needs to change.

Worth stating what is NOT wrong here, because the port initially claimed it
was: TERMINATE and REQUEST_CANCEL both work. The first version of these tests
reported "a TERMINATE child completed anyway", which was the harness's own thin
timing margin — 500ms between the child's sleep and the parent's — and not the
engine. Direct measurement of the row across the parent's completion showed the
correct transition:

```
ready | running -               gen=1
done  | failed  parent workflow terminated gen=2
```

The tests now measure the ordering rather than assume it, and a child that
finishes before its parent fails as a harness problem naming itself as one.

---

## Template for an entry

## N. <one-line summary>

**Class:** Bug | Missing API | Design difference
**Upstream test:** `<file>::<test name>`
**Status:** Open | Promoted (cleat-team/cleat#NNN, YYYY-MM-DD) | Won't fix

**What upstream asserts**

<The guarantee the upstream test pins down, in plain language. Describe the
behaviour — do not paste upstream code.>

**What cleat does**

<Observed behaviour, with the minimal reproduction.>

**Assessment**

<Why this is a bug / missing API / deliberate difference. If it is a deliberate
difference, say why the difference is deliberate — that is the comfortable
answer, so it needs the most support.>
