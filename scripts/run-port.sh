#!/usr/bin/env bash
# Run a single port: setup, then test, against the cleat toolchain in ./bin.
set -euo pipefail

PORT="${1:?usage: run-port.sh <port-name>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/ports/$PORT"

[ -d "$DIR" ] || { echo "no such port: $PORT" >&2; exit 2; }
[ -x "$ROOT/bin/cleat" ] || { echo "cleat not installed — run: make install-cleat" >&2; exit 2; }

export PATH="$ROOT/bin:$PATH"
export CLEAT_PORTS_DSN="${CLEAT_PORTS_DSN:-postgres://postgres:postgres@localhost:5432/cleat_ports?sslmode=disable}"

mkdir -p "$ROOT/.port-results"
LOG="$ROOT/.port-results/$PORT.log"

echo "--- $PORT: $(cat "$ROOT/bin/.cleat-build" 2>/dev/null | tr '\n' ' ')"
set +e
( make -C "$DIR" setup && make -C "$DIR" test ) 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
set -e

if [ "$rc" -ne 0 ]; then
  echo "--- $PORT: FAIL (rc=$rc), log at .port-results/$PORT.log" >&2
else
  echo "--- $PORT: pass"
fi
exit "$rc"
