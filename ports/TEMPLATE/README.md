# <port name>

Port of <upstream>'s test suite onto cleat. See [`UPSTREAM`](UPSTREAM) for the
exact upstream commit.

## What this port covers

| Upstream test file | Cases ported | Notes |
|---|---|---|
| `<upstream/path_test.py>` | 0 / N | |

## What this port deliberately skips, and why

State the skips explicitly. A port that quietly covers a third of the upstream
suite while reading as complete is worse than no port at all — it converts an
unknown into a false negative.

- `<upstream file>` — <reason: tests upstream framework internals / application
  logic / a concept cleat does not have>

## Running

```bash
make -C ../.. deps
make -C ../.. install-cleat
make -C ../.. port PORT=<port name>
```

## Findings

See [`ISSUES.md`](ISSUES.md).
