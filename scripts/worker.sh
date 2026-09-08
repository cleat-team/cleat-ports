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
PIDFILE="$CLEAT_PORTS_RESULTS_DIR/worker.pid"
FIXPID="$CLEAT_PORTS_RESULTS_DIR/fixture.pid"
FIXLOG="$CLEAT_PORTS_RESULTS_DIR/fixture.log"
# Per dialect, and that is the whole point of the suffix.
#
# The key lives in the database it was minted against -- api_keys is a table
# like any other -- so a key minted on PostgreSQL means nothing on MySQL. A
# single shared path made `make port DIALECT=mysql` after a postgres run fail
# every test with
#
#     start answered 401: {"error":"invalid or revoked API key"}
#
# because mint_key returns early whenever the file is non-empty, and it was:
# it held the postgres key. The 401 names authentication, which is the one
# thing that was not wrong, and sends you looking at --require-auth.
#
# `worker.sh stop` does not remove it either, so stopping the worker and
# starting it on another dialect reproduced the same failure -- which is what
# makes this worth a suffix rather than a cleanup in stop.
KEYFILE="$CLEAT_PORTS_RESULTS_DIR/api-key.$CLEAT_PORTS_DIALECT"
LOGFILE="$CLEAT_PORTS_RESULTS_DIR/worker.log"
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
  mkdir -p "$CLEAT_PORTS_RESULTS_DIR"
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
# owned reports whether the pid in PIDFILE is a cleat-worker this project
# started, by checking the process's OWN command line for our API port rather
# than trusting the file that named it.
#
# Per-run pidfiles make a cross-session mixup unlikely; they do not make it
# impossible, and the consequence is severe enough to check twice. On
# 2026-09-08 a flat pidfile let `ensure` stop a live worker belonging to another
# session and report it as restarting its own -- because health was tested
# against THIS session's URL while the pid came from a file everyone shared.
# A pid is a claim about a process; the process's argv is the process itself.
owned() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null)" || return 1
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q -- "-api-addr 127.0.0.1:$API_PORT"
}

# refuse_foreign exits rather than signalling a process this project does not
# own. Loud, because the alternative is what happened: the kill succeeds, the
# run continues, and the session that lost its worker sees `401 invalid or
# revoked API key` -- which names authentication, the one thing not wrong.
refuse_foreign() {
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || echo unknown)"
  cat >&2 <<MSG
refusing to signal pid $pid: it is not a cleat-worker serving 127.0.0.1:$API_PORT.

  pidfile: $PIDFILE
  process: $(ps -p "$pid" -o command= 2>/dev/null | cut -c1-120 || echo "(gone)")

Another session may own it. Check with:  pgrep -fl cleat-worker
If the pidfile is simply stale, remove it: rm -f "$PIDFILE"
MSG
  exit 3
}

crash_worker() {
  if running; then
    owned || refuse_foreign
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
    owned || refuse_foreign
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
  mkdir -p "$CLEAT_PORTS_RESULTS_DIR"

  mkdir -p "$CLEAT_PORTS_RESULTS_DIR"

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
  # -enable-admin-api is off by default and the operator endpoints answer 404
  # without it -- the same 404 as an unknown run, from a different line
  # (cmd/cleat-worker/api_admin.go:20 rather than :133). A port test that does
  # not set it measures the flag, not the endpoint.
  #
  # Plugin config. `llm`'s ollama provider is the one plugin path drivable with
  # no credential -- it takes a base URL and no API key -- so pointing it at the
  # fixture service is what makes a plugin call testable without a model, an API
  # key or a network. The fixture answers /api/chat, which is the path the
  # provider POSTs to.
  #
  # The config is a single JSON blob handed to every plugin, each of which
  # unmarshals its own shape, so this stays valid as more plugins are linked
  # (cleat#891 takes the count from 1 to 20).
  #
  # Written every start rather than once: the fixture port comes from env.sh
  # and a stale file would point a later run at the wrong port, which surfaces
  # as a connection refused inside the plugin rather than as a config problem.
  PLUGIN_CONFIG="$CLEAT_PORTS_RESULTS_DIR/plugin-config.json"
  mkdir -p "$CLEAT_PORTS_RESULTS_DIR"
  cat > "$PLUGIN_CONFIG" <<JSON
{"providers":{"ollama":{"base_url":"$CLEAT_PORTS_FIXTURE_URL","enabled":true,"default_model":"llama3.2"}}}
JSON

  ( cd "$SRC" && exec "$ROOT/bin/cleat-worker" \
      -db "$CLEAT_PORTS_DSN" \
      -driver "$CLEAT_PORTS_DIALECT" \
      -api-addr "127.0.0.1:$API_PORT" \
      -rls-check off \
      -bench-svc-url "$CLEAT_PORTS_FIXTURE_URL" \
      -plugin-config "$PLUGIN_CONFIG" \
      -enable-admin-api \
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
      # Serving is necessary and not sufficient: it must be OUR worker.
      #
      # Ports are chosen by hand here, so two sessions can pick the same one,
      # and then this branch reuses a worker belonging to somebody else --
      # against their database, with a key minted against ours. The symptom is
      # `401 invalid or revoked API key`, which names authentication: the one
      # thing that is not wrong. Observed on the shared default 8099 before
      # per-session ports were used at all.
      if [ -f "$PIDFILE" ] && ! owned; then
        cat >&2 <<MSG
something is already serving $API_URL and it is not this project's worker.

  pidfile: $PIDFILE ($(cat "$PIDFILE" 2>/dev/null || echo "no pid"))
  serving: $(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -1 | xargs -I{} ps -p {} -o command= 2>/dev/null | cut -c1-110 || echo "unknown")

Reusing it would run this session against another session's database while
authenticating with this session's key -- which fails as "401 invalid or
revoked API key" and names the wrong thing.

Set CLEAT_PORTS_API_PORT (and CLEAT_PORTS_FIXTURE_PORT) to a free port.
MSG
        exit 3
      fi
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
