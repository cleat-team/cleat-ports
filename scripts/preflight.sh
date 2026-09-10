#!/usr/bin/env bash
#
# Everything that must pass before a push. Run it AS the gate:
#
#     scripts/preflight.sh && git push …
#
# not beside one. This script exists because "beside one" is what kept
# happening: on 2026-09-10 three pushes went out behind a check whose failure
# could not stop them --
#
#   python3 -m py_compile … | head -1      # the pipe eats the exit status
#   check.py --check; git add …; git commit …   # ';' is not '&&'
#   compile && count && push                # neither runs the SUITE
#
# The third is the interesting one. It passed on a file with one test defined
# twice and another module's test missing, because the case COUNT was 5 either
# way. A gate made of proxies is silent about whatever the proxies cannot see.
#
# Usage:
#   scripts/preflight.sh            # static checks only (fast, no database)
#   scripts/preflight.sh --suite    # also run the Python suite (needs a worker)
#   scripts/preflight.sh --suite tests/test_defer.py   # ... just these tests
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
PORT=ports/dbos-transact-py
fail=0

run() {  # run <label> <cmd...>
    local label="$1"; shift
    local out
    if out="$("$@" 2>&1)"; then
        printf '  ok    %s\n' "$label"
    else
        printf '  FAIL  %s\n' "$label"
        printf '%s\n' "$out" | sed 's/^/          /' | head -20
        fail=1
    fi
}

echo "preflight:"

# Syntax. Cheap, and never sufficient on its own -- see the header.
run "python syntax" python3 -m compileall -q "$PORT/tests" "$PORT/scripts" scripts
run "shell syntax"  bash -n scripts/worker.sh

# The inventory check, which also refuses a shadowed test -- a duplicate
# definition that pytest silently collects once while the file shows two.
run "case inventory" python3 "$PORT/scripts/count-queue-cases.py" --check
run "issue citations" bash scripts/check-issue-citations.sh
run "issue numbers"   bash scripts/check-issue-numbers.sh

# Self-tests for the checks themselves. A check nobody falsifies is a check
# that reports clean because it cannot report anything else.
[ -f scripts/selftest-check-assertions.py ] && \
    run "assertion-check selftest" python3 scripts/selftest-check-assertions.py
[ -f scripts/selftest-fixture-service.py ] && \
    run "fixture selftest" python3 scripts/selftest-fixture-service.py

if [ "${1:-}" = "--suite" ]; then
    shift
    # THE ONE THAT MATTERS. Everything above is a proxy for this.
    if [ -x "$PORT/.venv/bin/pytest" ]; then
        echo "  ...   running the suite (this is the gate the others stand in for)"
        if ( cd "$PORT" && .venv/bin/pytest -q "${@:-tests/}" ) ; then
            printf '  ok    pytest %s\n' "${*:-tests/}"
        else
            printf '  FAIL  pytest %s\n' "${*:-tests/}"
            fail=1
        fi
    else
        printf '  FAIL  pytest: no venv at %s/.venv -- run `make -C %s setup`\n' "$PORT" "$PORT"
        fail=1
    fi
else
    echo "  note  suite NOT run (pass --suite). Static checks alone have"
    echo "        passed on a broken tree before; they are proxies."
fi

if [ "$fail" -ne 0 ]; then
    echo "preflight FAILED -- do not push"
    exit 1
fi
echo "preflight ok"
