## 24. A workflow result the store cannot hold is replaced with `{}` and the run reports success

**Class:** Design difference
**Upstream test:** `tests/test_failures.py::test_nonserializable_return`
**Status:** Open

**What upstream asserts**

A workflow returning a value its serializer cannot encode FAILS. The point is
not the encoder: a value that cannot be recorded must not be reported as a
recorded success.

**What cleat does**

An entry point returns a string that the engine stores in
`workflow_instances.result` -- JSONB on Postgres, JSON on MySQL, a
`CHECK (ISJSON(...))` column on SQL Server. A result no dialect can hold is
replaced with `{}` by `coerceResultJSON` (`engine/store_lifecycle.go`) and the
workflow completes.

Measured 2026-09-08 on Postgres, reading the column directly rather than the
API, with controls:

| returned by the workflow | stored | status | error_code | error_msg |
|---|---|---|---|---|
| `{"ok":true}` (control) | `{"ok": true}` | `done` | — | — |
| `{"x":123456789012345678901234567890}` (control) | unchanged | `done` | — | — |
| `not json` | **`{}`** | `done` | — | — |
| `{"x":NaN}` | **`{}`** | `done` | — | — |
| `{"x":Infinity}` | **`{}`** | `done` | — | — |

The two controls are what make the rest evidence. `big-int` is past 2**53, so it
also shows the value is not passed through a float on the way to the column.

**What is and is not silent**

The engine logs an ERROR naming the workflow and the discarded value:

    workflow result is not valid JSON and was replaced with {} -- whatever it
    carried, including any error the workflow returned, is not stored anywhere

So this is not silent to an operator reading worker logs. It is invisible to a
CALLER: `done`, no `error_code`, no `error_msg`, `result` of `{}`. A caller who
asked for a value receives an empty object and a success.

Stated because the obvious write-up -- "cleat silently discards the result" --
is wrong, and I had written it before tracing the function.

**Assessment**

A deliberate difference in part. `coerceResultJSON`'s own comments show the
trade-off was considered for the valid-but-wrong-shaped case: replacing a
storable result would destroy data, so that case is reported and stored as-is.
The invalid case has no such option -- the column would reject it -- so the
choice is between substituting and failing the workflow, and cleat substitutes.

What is not obviously deliberate is that the caller learns nothing. Upstream's
property is about the CALLER's view, and by that measure the behaviours differ:
upstream fails, cleat returns success with a substituted value. Whether to
surface it (an `error_code`, or failing the run) is a product decision, which is
why this is recorded here rather than filed as a defect.

**A second finding, from the control rather than the subject**

The large-integer case was included as a CONTROL -- to show the engine does not
mangle values merely for being awkward. It found a different defect, filed as
cleat#1022: the same result is stored exactly on PostgreSQL and narrowed to a
double on MySQL.

| dialect | `{"x":123456789012345678901234567890}` stored as |
|---|---|
| PostgreSQL | `{"x": 123456789012345678901234567890}` |
| MySQL | **`{"x": 1.2345678901234566e29}`** |

Read from the column on both, same WASM binary. The conversion is inherent to
MySQL's `JSON` type -- exact only to `BIGINT` -- so the defect is the silence
and the divergence, not the narrowing. Nothing logs it, and the degraded value
is valid JSON of the right shape.

Worth recording how it surfaced: an assertion that the result "is a number" or
"is an object" passes on both dialects. It took comparing against the exact
returned string, on more than one dialect, and it was not what the case was for.

**Tests**

`tests/test_results.py` pins the current behaviour, with the `valid` control.
The substitution test fails with instructions to invert it if cleat moves to
upstream's behaviour, and the large-integer test asserts per-dialect values --
skipping, with its reason, on any dialect nobody has measured. SQL Server is
unmeasured: `result` there is a `CHECK (ISJSON(...))` column, a third
implementation, and guessing would assert nothing.
