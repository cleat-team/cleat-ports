#!/usr/bin/env bash
# Run a single port: setup, then test, against the cleat toolchain in ./bin.
set -euo pipefail

PORT="${1:?usage: run-port.sh <port-name>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/ports/$PORT"

[ -d "$DIR" ] || { echo "no such port: $PORT" >&2; exit 2; }
[ -x "$ROOT/bin/cleat" ] || { echo "cleat not installed — run: make install-cleat" >&2; exit 2; }

export PATH="$ROOT/bin:$PATH"
# Defaults live in scripts/env.sh so the DSN and the compose port cannot drift
# apart again. CI overrides CLEAT_PORTS_PG_PORT because its service binds 5432.
# shellcheck source=scripts/env.sh
. "$ROOT/scripts/env.sh"

mkdir -p "$ROOT/.port-results"
LOG="$ROOT/.port-results/$PORT.log"

# One worker, shared by every port in this run. `ensure` is idempotent, so the
# first port starts it and the rest reuse it. Teardown is the Makefile's job
# (it traps), not this script's -- stopping here would give each port its own
# worker, which is what we are deliberately not doing.
"$ROOT/scripts/worker.sh" ensure
CLEAT_PORTS_API="$("$ROOT/scripts/worker.sh" url)"
CLEAT_PORTS_API_KEY="$(cat "$ROOT/.port-results/api-key")"
export CLEAT_PORTS_API CLEAT_PORTS_API_KEY

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
