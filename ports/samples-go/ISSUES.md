# <port name>: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

Empty is the correct starting state. Add entries as you port, not at the end.

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
