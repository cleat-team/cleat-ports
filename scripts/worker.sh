#!/usr/bin/env bash
# Start / stop / crash the one cleat worker that every port in a run shares.
#
# One worker per `make` invocation, not one per port and not a long-lived
# daemon. Per-port workers would make a concurrency test meaningless -- cleat's
# concurrency key is enforced in the database, but "did the second run start"
# is a much weaker question when the answer depends on which of several workers
# happened to poll first. A persistent daemon would instead leave a process
# holding a database from a previous run, which is the kind of stale state that
# makes a red test unreproducible.
#
# `ensure` is idempotent: it starts a worker only if the pidfile's process is
# gone or unhealthy, so N ports in one run share the first one started.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/env.sh
. "$ROOT/scripts/env.sh"
SRC="$ROOT/.cleat-src"
PIDFILE="$ROOT/.port-results/worker.pid"
FIXPID="$ROOT/.port-results/fixture.pid"
FIXLOG="$ROOT/.port-results/fixture.log"
KEYFILE="$ROOT/.port-results/api-key"
LOGFILE="$ROOT/.port-results/worker.log"
API_PORT="$CLEAT_PORTS_API_PORT"
API_URL="$CLEAT_PORTS_API"

healthy() { curl -sf -m 2 "$API_URL/healthz" >/dev/null 2>&1; }

running() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Auth stays ON. --require-auth defaults true whenever --api-addr is set, and
# leaving it on is the point: a port that starts workflows over an unauthenticated
# API is exercising a configuration nobody deploys. Cheaper to mint one key here
# than to have every port assert against a path production does not use.
mint_key() {
  [ -s "$KEYFILE" ] && return 0
  ( cd "$SRC" && "$ROOT/bin/cleat-worker" \
      -db "$CLEAT_PORTS_DSN" \
      -driver "$CLEAT_PORTS_DIALECT" \
      -generate-api-key "$CLEAT_PORTS_TENANT" 2>/dev/null ) \
    | sed -n 's/^Key: *//p' | tr -d '[:space:]' > "$KEYFILE"
  [ -s "$KEYFILE" ] || { echo "failed to mint an API key" >&2; rm -f "$KEYFILE"; exit 1; }
}

fixture_healthy() { curl -sf -m 2 "$CLEAT_PORTS_FIXTURE_URL/healthz" >/dev/null 2>&1; }

start_fixture() {
  fixture_healthy && return 0
  mkdir -p "$ROOT/.port-results"
  python3 "$ROOT/scripts/fixture-service.py" "$CLEAT_PORTS_FIXTURE_PORT" \
    >"$FIXLOG" 2>&1 &
  echo $! > "$FIXPID"
  for _ in $(seq 1 40); do
    fixture_healthy && return 0
    sleep 0.25
  done
  echo "fixture service did not become healthy; log follows:" >&2
  tail -20 "$FIXLOG" >&2
  return 1
}

stop_fixture() {
  if [ -f "$FIXPID" ]; then
    pid="$(cat "$FIXPID" 2>/dev/null || true)"
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    rm -f "$FIXPID"
  fi
}

# Kill the worker the way a crash does: SIGKILL, no graceful shutdown, no
# chance to release its claims or finalize anything in flight. A workflow it
# was running stays `running` in the database with a heartbeat that stops
# advancing, which is exactly the state a machine losing power produces -- and
# the state the reaper exists to resolve.
#
# stop_worker below is deliberately NOT this: it signals first and only
# escalates, so a worker asked to stop gets to clean up. A recovery test that
# used it would be testing shutdown, not crash.
#
# The fixture service is left running on purpose. It holds the per-key call
# counts the recovery assertion reads, and those must survive the crash to be
# evidence of anything.
crash_worker() {
  if running; then
    pid="$(cat "$PIDFILE")"
    kill -9 "$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    echo "worker killed (pid $pid)"
  else
    echo "no worker running to kill" >&2
  fi
  rm -f "$PIDFILE"
}

stop_worker() {
  if running; then
    pid="$(cat "$PIDFILE")"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    echo "worker stopped (pid $pid)"
  fi
  rm -f "$PIDFILE"
}

start() {
  [ -x "$ROOT/bin/cleat-worker" ] || {
    echo "cleat-worker not built -- run: make install-cleat" >&2; exit 2; }
  mkdir -p "$ROOT/.port-results"

  mkdir -p "$ROOT/.port-results"

  # Run from the cloned source tree, not from here. cleat-worker resolves its
  # migrations with a hardcoded relative path -- cmd/cleat-worker/main.go does
  # `migration.NewRunner(migrateDB, dialect, "migrations")` -- with no flag to
  # override it and no embedded copy. Started anywhere else it dies with
  # `read migrations: open migrations/postgres: no such file or directory`
  # before serving anything, which reads as a database permissions problem
  # because that is what the surrounding log line suggests.
  [ -d "$SRC/migrations" ] || {
    echo "no migrations at $SRC/migrations -- run: make install-cleat" >&2; exit 2; }

  # -rls-check=off, deliberately, with the trade-off stated.
  #
  # cleat refuses to start when its connection is not subject to row-level
  # security, because for GetWorkflowByID and ListWorkflows the RLS policies
  # are the ONLY tenant isolation -- neither has an application-level tenant
  # filter. PostgreSQL never applies RLS to a superuser, and the compose
  # database connects as `postgres`. The refusal is correct and it is a good
  # check.
  #
  # The production fix is to run as the unprivileged cleat_app role
  # (migrations/postgres/005_app_role.sql) with --migrate-db kept on the owner.
  # This harness does not do that yet, and the cost of not doing it is real but
  # bounded: these ports are single-tenant, so they cannot observe a
  # cross-tenant leak either way, which also means they cannot catch a
  # regression in it. A port that ever asserts tenant isolation must switch to
  # cleat_app first, or it will pass on a connection where isolation is not in
  # force at all.
  start_fixture || exit 1

  # -driver as well as -db. The worker defaults to postgres and will hand a
  # MySQL or SQL Server DSN to lib/pq without it, which fails with a message
  # about SSL or about a missing "=" rather than about dialect.
  ( cd "$SRC" && exec "$ROOT/bin/cleat-worker" \
      -db "$CLEAT_PORTS_DSN" \
      -driver "$CLEAT_PORTS_DIALECT" \
      -api-addr "127.0.0.1:$API_PORT" \
      -rls-check off \
      -bench-svc-url "$CLEAT_PORTS_FIXTURE_URL" \
      >"$LOGFILE" 2>&1 ) &
  echo $! > "$PIDFILE"

  # Wait for readiness rather than sleeping. A fixed sleep is either slower
  # than it needs to be or, on a cold database that has migrations to run,
  # too short -- and too short shows up as a confusing connection-refused in
  # the first test rather than as a worker problem.
  for _ in $(seq 1 60); do
    healthy && { mint_key; echo "worker ready at $API_URL (pid $(cat "$PIDFILE"))"; return 0; }
    running || { echo "worker exited during startup; log follows:" >&2
                 tail -20 "$LOGFILE" >&2; rm -f "$PIDFILE"; exit 1; }
    sleep 0.5
  done

  echo "worker did not become healthy within 30s; log follows:" >&2
  tail -20 "$LOGFILE" >&2
  stop_worker
  exit 1
}

case "${1:?usage: worker.sh <ensure|crash|stop|url>}" in
  ensure)
    # Health of the endpoint, not ownership of the pidfile, is what decides.
    # A worker left by an earlier run serves fine and starting a second one
    # just loses the port bind -- which is how this was found: the second
    # process logged "address already in use", exited, and took the run with
    # it while the healthy first worker sat there unused.
    if healthy; then
      start_fixture || exit 1
      echo "worker already serving $API_URL${PIDFILE:+ (pid $(cat "$PIDFILE" 2>/dev/null || echo unknown))}"
      mint_key
    elif running; then
      echo "worker process is up but not serving; restarting"
      stop_worker
      start
    else
      # A pidfile whose process is gone, or a process that is up but not
      # serving, are both "start a fresh one" -- but the stale pid must go
      # first or `stop` later would signal an unrelated process.
      rm -f "$PIDFILE"
      start
    fi
    ;;
  crash)
    crash_worker
    ;;
  stop)
    stop_worker
    stop_fixture
    ;;
  url) echo "$API_URL" ;;
  *) echo "usage: worker.sh <ensure|crash|stop|url>" >&2; exit 2 ;;
esac
