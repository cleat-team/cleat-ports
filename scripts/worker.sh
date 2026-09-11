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

# A SECOND WORKER, so cross-worker cases are expressible at all.
#
# cleat-worker serves the HTTP API and runs workflows in one process, and this
# harness started exactly one -- so a whole class of assertions could not be
# written here, only described. A concurrency key contended across PROCESSES
# rather than serialised within one; a signal delivered to a workflow another
# worker owns; a stale-but-living run writing its outcome after a takeover.
# ports/dbos-transact-py/README.md's "what this suite structurally cannot
# catch" says so, and this is the half of that entry that was fixable.
#
# CLEAT_PORTS_WORKER_INSTANCE selects one. Unset or "1" is the primary and
# every path below is byte-identical to what it was -- deliberately, because
# every session and all of CI depend on this script and a second worker must
# not perturb the first.
#
# The second shares the DATABASE, the API KEY and the FIXTURE with the first,
# and that sharing is the point: two workers against one database is the
# configuration under test. It needs its own pid file, log and API port, and
# nothing else.
#
# The key is shared rather than minted twice on purpose. mint_key short-
# circuits on a non-empty file, so a second mint would either no-op (leaving
# the second worker using the first's key, which is correct) or, if the file
# were also suffixed, mint a second key against the same tenant and leave two
# valid keys where the suite expects one. Sharing states the intent.
WORKER_INSTANCE="${CLEAT_PORTS_WORKER_INSTANCE:-1}"
case "$WORKER_INSTANCE" in
  1) ;;
  ''|*[!0-9]*)
    echo "CLEAT_PORTS_WORKER_INSTANCE must be a positive integer, got '$WORKER_INSTANCE'" >&2
    exit 1
    ;;
  *)
    # Port derived, not configured: a second env var to set is a second thing
    # to get wrong, and the offset keeps instance N inside the block this
    # session already owns.
    API_PORT=$(( CLEAT_PORTS_API_PORT + WORKER_INSTANCE - 1 ))
    API_URL="http://127.0.0.1:$API_PORT"
    PIDFILE="$CLEAT_PORTS_RESULTS_DIR/worker.$WORKER_INSTANCE.pid"
    LOGFILE="$CLEAT_PORTS_RESULTS_DIR/worker.$WORKER_INSTANCE.log"
    ;;
esac

healthy() { curl -sf -m 2 "$API_URL/healthz" >/dev/null 2>&1; }

running() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Auth stays ON. --require-auth defaults true UNCONDITIONALLY -- not "whenever
# --api-addr is set", as this comment said until 2026-09-10. The help text reads
# "(default: true when --api-addr is set)", and that clause describes when auth is
# APPLIED; it is not a condition on the flag's value, which is true with no API
# served at all. The distinction is load-bearing further down this file, where
# the RLS split is set up: see "the worker REFUSES rather than warns" there.
#
# Leaving auth on is the point on its own: a port that starts workflows over an
# unauthenticated API is exercising a configuration nobody deploys. Cheaper to
# mint one key here than to have every port assert against a path production
# does not use.
# Is the cached key known-good, known-bad, or unknowable?
#
#   0  it authenticates
#   1  it does not, or there is no file
#   2  cannot tell -- nothing is serving, so the question has no answer yet
#
# The three-way answer is the point. `[ -s "$KEYFILE" ]` asks whether the file
# is non-empty, which is a different question from whether the key works, and
# the two diverge exactly when a suite has truncated the tenant rows: the file
# keeps a key the database no longer knows. The failure then lands later as
# `401 invalid or revoked API key`, naming authentication -- which is the only
# part of the system behaving correctly.
#
# This is the same shape as the DSN note in cleat's CLAUDE.md: "A DSN that is
# set but does not connect looks exactly like one that works. Setting the
# variable is what stops a test skipping. Connecting is a separate question."
key_state() {
  [ -s "$KEYFILE" ] || return 1
  healthy || return 2
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 \
      -H "Authorization: Bearer $(cat "$KEYFILE")" \
      "$API_URL/api/workflows" 2>/dev/null)" || return 2
  case "$code" in
    200) return 0 ;;
    401|403) return 1 ;;
    # Any other code is about the endpoint, not the credential. Re-minting on a
    # 500 would burn a key row per call and blame the wrong thing.
    *) return 2 ;;
  esac
}

mint_key() {
  # `key_state` on a bare line would be fatal: this script runs under `set -e`,
  # so a function returning 1 -- which is key_state's ordinary way of saying
  # "revoked" -- terminates the shell before the re-mint it was asked for. The
  # symptom was `ensure` exiting silently with the stale key still in place,
  # i.e. exactly the defect this function is meant to fix, caused by the fix.
  # `|| state=$?` puts the call in a condition context, where set -e does not
  # fire.
  local state=0
  key_state || state=$?
  case $state in
    0) return 0 ;;
    2) [ -s "$KEYFILE" ] && return 0 ;;
  esac
  ( cd "$SRC" && "$ROOT/bin/cleat-worker" \
      -db "$CLEAT_PORTS_DSN" \
      -driver "$CLEAT_PORTS_DIALECT" \
      -generate-api-key "$CLEAT_PORTS_TENANT" 2>/dev/null ) \
    | sed -n 's/^Key: *//p' | tr -d '[:space:]' > "$KEYFILE"
  [ -s "$KEYFILE" ] || { echo "failed to mint an API key" >&2; rm -f "$KEYFILE"; exit 1; }

  # Minting wrote a file; that is not the same as minting a key that works, and
  # this function's whole defect was treating the two as one.
  # `if ! key_state && [ $? -eq 1 ]` was the first attempt and is wrong: after
  # `! cmd`, $? is the NEGATED status, so the guard reads 0 where key_state said
  # 1. Capture the status, then branch on it.
  local after=0
  key_state || after=$?
  if [ "$after" -eq 1 ]; then
    echo "minted an API key that does not authenticate against $API_URL" >&2
    rm -f "$KEYFILE"
    exit 1
  fi
}

fixture_healthy() { curl -sf -m 2 "$CLEAT_PORTS_FIXTURE_URL/healthz" >/dev/null 2>&1; }

# The fixture equivalent of owned(), and it exists for a sharper reason than the
# worker one. A shared WORKER corrupts a run and says so loudly -- wrong
# database, 401, a table of nulls. A shared FIXTURE corrupts the EVIDENCE, in
# silence: this service holds the per-key call counters, and 40 of the 134 test
# functions in dbos-transact-py -- 29% of the suite -- read them as their
# assertion. `_counts` from another session's traffic is indistinguishable from
# this session's. ports#172 turned entirely on a count being 3 rather than 4.
#
# Found live while writing this: the fixture serving this session's port was
# started from a DIFFERENT checkout (a sibling worktree). Its code happened to
# be byte-identical, so nothing was wrong -- which is the point. Nothing would
# have said so if it had not been.
#
# -ww for the same reason owned() needs it: GNU ps truncates to 80 columns when
# stdout is not a tty, and the fixture is invoked as
#   <python> <ROOT>/scripts/fixture-service.py <PORT>
# with the port LAST. Measured at 255 columns here, so the one token that
# identifies the service sits ~170 columns past where the unwidened form stops.
fixture_owned() {
  local pid
  pid="$(cat "$FIXPID" 2>/dev/null)" || return 1
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local cmd
  cmd="$(ps -ww -p "$pid" -o command= 2>/dev/null)" || return 1
  case "$cmd" in
    *"fixture-service.py $CLEAT_PORTS_FIXTURE_PORT"*) return 0 ;;
    *) return 1 ;;
  esac
}

refuse_foreign_fixture() {
  cat >&2 <<MSG
something is already serving the fixture service on $CLEAT_PORTS_FIXTURE_URL
and this invocation cannot show it is ours.

  pidfile: $FIXPID (absent, empty, or naming a process that is not the fixture)
  serving: $(lsof -nP -iTCP:"$CLEAT_PORTS_FIXTURE_PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -1 | xargs -I{} ps -ww -p {} -o command= 2>/dev/null || echo "unknown")

Adopting it would run this session's assertions against another session's call
counters, and the counters ARE the assertion in 29% of the Python suite. That
does not fail -- it produces a number, and the number is wrong.

Stop the process above, or set CLEAT_PORTS_FIXTURE_PORT to a free port.
MSG
  exit 3
}

start_fixture() {
  # `fixture_healthy && return 0` adopted ANY healthy service on the port. This
  # is the ownership check that was added to `ensure` for workers on
  # 2026-09-08 and never applied here.
  if fixture_healthy; then
    fixture_owned || refuse_foreign_fixture
    return 0
  fi
  # Healthy is false, so any pidfile is stale; drop it before writing a new one
  # or `stop` would later signal an unrelated process.
  rm -f "$FIXPID"
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
  # Three ways the old form succeeded at nothing: no $FIXPID skipped the whole
  # body; a failed `kill` was swallowed by `|| true`; and nothing ever
  # re-checked fixture_healthy, so a service that ignored the signal was
  # reported stopped. The postcondition is `! fixture_healthy`, not "we sent a
  # signal".
  if fixture_owned; then
    pid="$(cat "$FIXPID")"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$FIXPID"

  if fixture_healthy; then
    cat >&2 <<MSG
the fixture service on $CLEAT_PORTS_FIXTURE_URL is still serving after stop.

  serving: $(lsof -nP -iTCP:"$CLEAT_PORTS_FIXTURE_PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -1 | xargs -I{} ps -ww -p {} -o command= 2>/dev/null || echo "unknown")

Either it is not ours -- in which case this correctly did not kill it, and the
caller's belief that the fixture is gone is false -- or it ignored the signal.
Reporting a clean stop either way is what makes the next run's counters
somebody else's.
MSG
    return 1
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
  # -ww, and it is load-bearing: GNU ps TRUNCATES TO 80 COLUMNS when stdout is
  # not a tty, which every CI step and every captured subprocess is. The worker
  # is started as
  #
  #   .../bin/cleat-worker -db postgres://...?sslmode=disable -driver postgres -api-addr 127.0.0.1:8099
  #
  # and -api-addr begins at column 152, so the unwidened form cannot see the one
  # flag this function exists to read. It then reports every worker as foreign.
  # Caught by CI on the commit that introduced it, because the guard fails
  # CLOSED -- had it failed open it would have passed here and protected
  # nothing.
  local cmd
  cmd="$(ps -ww -p "$pid" -o command= 2>/dev/null)" || return 1
  case "$cmd" in *"-api-addr 127.0.0.1:$API_PORT"*) ;; *) return 1 ;; esac
  # ...AND serving the database this invocation asked for.
  #
  # The api-addr alone is not enough. A worker started for one dialect is this
  # project's worker on this project's port, so an api-addr check calls it
  # owned -- and `ensure` then REUSES it for a run against another dialect.
  # The run authenticates with the new dialect's key against a worker holding
  # the old dialect's database, and every result is about the wrong store.
  #
  # Measured 2026-09-08: a postgres worker was reused for a mysql run, which
  # produced a whole table of null statuses that looked like a broken build.
  # Nothing failed, because nothing was wrong -- the question was being put to
  # the wrong database.
  case "$cmd" in *"$CLEAT_PORTS_DSN"*) return 0 ;; *) return 1 ;; esac
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
  process: $(ps -ww -p "$pid" -o command= 2>/dev/null || echo "(gone)")

Another session may own it. Check with:  pgrep -fl cleat-worker
If the pidfile is simply stale, remove it: rm -f "$PIDFILE"
MSG
  exit 3
}

crash_worker() {
  # A "crash" that killed nothing MUST NOT exit 0. This is the only operation
  # in this script whose entire value is that it happened: a recovery test asks
  # for a worker to die so it can watch the engine recover, and if nothing dies
  # the test still runs, still passes, and is measuring the uncrashed control.
  #
  # That is not hypothetical. On 2026-09-10 this function printed "no worker
  # running to kill" and returned 0 against a live, serving, untracked worker.
  # The mid-backoff retry test then reported the control's call count and
  # PASSED, agreeing with an engine that does the right thing and with one that
  # does not. Five tests across two modules call crash(); all five were
  # degraded and none of them could have said so.
  if running; then
    owned || refuse_foreign
    pid="$(cat "$PIDFILE")"
    kill -9 "$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    if kill -0 "$pid" 2>/dev/null; then
      echo "worker $pid survived SIGKILL after 10s; refusing to report a crash" >&2
      exit 1
    fi
    echo "worker killed (pid $pid)"
    rm -f "$PIDFILE"
  elif healthy; then
    cat >&2 <<MSG
refusing to "crash": $API_URL is serving but no pidfile identifies the worker.

  pidfile: $PIDFILE (absent, empty, or naming a dead process)
  serving: $(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -1 | xargs -I{} ps -ww -p {} -o command= 2>/dev/null || echo "unknown")

The usual cause is that the worker was started under a different
CLEAT_PORTS_RESULTS_DIR than this invocation resolves, so this script looks for
the pidfile in the wrong directory and concludes there is nothing to kill.
"ensure" tolerates that -- it sees a healthy URL and reports "(pid unknown)" --
and for every operation except this one, tolerating it is correct.

Kill the process above and let "worker.sh ensure" start a tracked one.
MSG
    rm -f "$PIDFILE"
    exit 1
  else
    echo "nothing is serving $API_URL, so there is no worker to crash" >&2
    rm -f "$PIDFILE"
    exit 1
  fi
}

stop_worker() {
  # Unlike `crash`, a stop with nothing running is legitimately idempotent --
  # the Makefile's EXIT trap calls it whether or not a worker was ever started.
  # So the postcondition is "nothing is serving afterwards", not "we killed
  # something", and the case that must fail is the middle one: something IS
  # serving and we cannot identify it.
  #
  # The old form skipped its whole body when `running` was false and exited 0
  # with NO OUTPUT ON ANY STREAM -- worse than `crash`, which at least wrote to
  # stderr. `Worker.stop()` exists so a test can build a backlog with the
  # worker gone and no claims held; a silent no-op leaves it claiming, the
  # queue's contents are then not the test's doing, and the premise fails as a
  # confusing assertion about queue contents rather than as a harness fault.
  if running; then
    owned || refuse_foreign
    pid="$(cat "$PIDFILE")"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    if kill -0 "$pid" 2>/dev/null; then
      echo "worker $pid survived SIGTERM then SIGKILL; not reporting a stop" >&2
      rm -f "$PIDFILE"
      exit 1
    fi
    echo "worker stopped (pid $pid)"
  elif healthy; then
    cat >&2 <<MSG
refusing to "stop": $API_URL is serving but no pidfile identifies the worker.

  pidfile: $PIDFILE (absent, empty, or naming a dead process)
  serving: $(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -1 | xargs -I{} ps -ww -p {} -o command= 2>/dev/null || echo "unknown")

Reporting a clean stop here would leave that process holding claims while the
caller believes the worker is gone.
MSG
    rm -f "$PIDFILE"
    exit 1
  else
    echo "nothing is serving $API_URL; stop is a no-op" >&2
  fi
  rm -f "$PIDFILE"
}

# ensure_app_role gives cleat_app a password and LOGIN, idempotently.
#
# migrations/postgres/005_app_role.sql creates the role NOLOGIN and without a
# password, deliberately -- its own comment says the operator supplies those.
# So the harness is the operator here.
#
# Created BEFORE migrations rather than after, and that ordering is forced: the
# worker opens its runtime pool before it runs migrations, so a role that
# cannot log in kills it before 005 would have created one. 005's guard is
# `IF NOT EXISTS (SELECT 1 FROM pg_roles ...)`, so it skips a role that is
# already there, and its later `ALTER ROLE cleat_app NOSUPERUSER NOCREATEDB
# NOCREATEROLE NOBYPASSRLS` does not touch LOGIN. The grants -- including
# ALTER DEFAULT PRIVILEGES, which is what covers tables added by later
# migrations -- all come from 005 and are left to it.
#
# Attributes match 005's exactly. A role created here with anything more is a
# role the ports run under and deployments do not, which is the whole defect
# being repaired.
# pg_psql runs one psql invocation against the ports database, over whichever
# channel this environment actually has.
#
# ONE helper for both callers below, deliberately. Two implementations of "talk
# to postgres" is how they drift apart, and the drift is silent because each
# works somewhere.
#
# `psql` on PATH first: that is CI, where PostgreSQL is a GitHub Actions SERVICE
# container and `docker compose` knows nothing about it -- the first version of
# this used compose unconditionally and every port job died with
# `service "postgres" is not running`, having worked locally. `docker compose
# exec` second: that is the local harness, where compose owns the database and
# psql is frequently not installed on the host at all (it is not on mine).
#
# Arguments after the flags are passed through, so the caller writes one psql
# command line rather than two.
pg_psql() {
  local user="$1" pass="$2" host="$3" port="$4"; shift 4
  if command -v psql >/dev/null 2>&1; then
    PGPASSWORD="$pass" psql -U "$user" -h "$host" -p "$port" -d cleat_ports "$@"
  else
    case "$host" in localhost|127.0.0.1) host="host.docker.internal" ;; esac
    docker compose exec -T -e PGPASSWORD="$pass" postgres \
      psql -U "$user" -h "$host" -p "$port" -d cleat_ports "$@"
  fi
}

ensure_app_role() {
  [ "$CLEAT_PORTS_DIALECT" = "postgres" ] || return 0

  # Every credential comes from the DSNs in force, not from defaults restated
  # here: a second source for the same fact is what put the owner on one port
  # and the worker on another.
  local ocreds ouser opass ohost oport
  ocreds=${CLEAT_PORTS_DSN#*://}
  ouser=${ocreds%%:*}
  opass=${ocreds#*:}; opass=${opass%%@*}
  ohost=${ocreds#*@}; ohost=${ohost%%[:/]*}
  oport=${ocreds#*@}; oport=${oport#*:}; oport=${oport%%/*}

  local pw="${CLEAT_PORTS_APP_PASSWORD:-cleat-app-ports-local}"
  if ! pg_psql "$ouser" "$opass" "$ohost" "${oport:-5432}" -v ON_ERROR_STOP=1 -q -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cleat_app') THEN
        CREATE ROLE cleat_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
\$\$;
ALTER ROLE cleat_app LOGIN PASSWORD '${pw}';
" >/dev/null; then
    echo "could not provision the cleat_app role on $CLEAT_PORTS_DSN" >&2
    return 1
  fi

  # TWO CONTROLS, and the second one exists because its absence cost a whole
  # suite run: 109 of 136 tests failed on `401 invalid or revoked API key`,
  # which is one worker that could not authenticate wearing the costume of a
  # hundred defects.
  #
  # Control 1 is on the PROPERTY, not the artifact. "The role exists" is not
  # what matters -- "the role cannot escape a policy" is, and a role that picked
  # up SUPERUSER or BYPASSRLS somewhere looks identical until a tenant
  # assertion silently passes.
  local attrs
  attrs=$(pg_psql "$ouser" "$opass" "$ohost" "${oport:-5432}" -tAc \
    "SELECT rolsuper::text || ' ' || rolbypassrls::text FROM pg_roles WHERE rolname = 'cleat_app'" \
    2>/dev/null | tr -d '\r')
  case "$attrs" in
    "false false") : ;;
    *)
      echo "cleat_app is not subject to RLS (rolsuper rolbypassrls = '${attrs}')." >&2
      echo "The worker would start and every tenant policy would be inert." >&2
      return 1
      ;;
  esac

  # Control 2: can the RUNTIME DSN actually connect? Provisioning reports
  # success for having run the ALTER, which is a different claim -- and the
  # worker does not turn a failure here into a refusal. Its RLS check has three
  # arms, and an unreachable database takes the one that WARNS and continues
  # (cmd/cleat-worker/main.go:647), so the worker comes up, serves 401 to
  # everything, and the suite reports a hundred unrelated-looking failures.
  #
  # Asked over the same route the worker will use -- host and port from the
  # runtime DSN, not the container's loopback -- because pg_hba can answer those
  # differently and a control that takes a different path is not a control.
  # Every credential comes FROM THE RUNTIME DSN, not from $pw. The first
  # version of this used $pw and passed a deliberately-wrong DSN, because it
  # was asking "can the password I just set authenticate" -- true, and a
  # different question from "does the string the worker is about to use work".
  # Those come apart exactly when they differ, which is the only case worth
  # checking.
  local creds host port ruser rpass
  creds=${CLEAT_PORTS_RUNTIME_DSN#*://}
  ruser=${creds%%:*}
  rpass=${creds#*:}; rpass=${rpass%%@*}
  host=${creds#*@}; host=${host%%[:/]*}
  port=${creds#*@}; port=${port#*:}; port=${port%%/*}
  if ! pg_psql "$ruser" "$rpass" "$host" "${port:-5432}" -tAc "SELECT 1" >/dev/null 2>&1; then
    echo "cleat_app cannot authenticate over the DSN the worker will use:" >&2
    echo "  $CLEAT_PORTS_RUNTIME_DSN" >&2
    echo "Starting anyway would give a worker that answers 401 to every request," >&2
    echo "which reads as a broken test suite rather than a broken connection." >&2
    return 1
  fi
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

  # The worker runs as cleat_app with the RLS check ON. cleat-ports#198.
  #
  # This used to pass -rls-check=off and connect as `postgres`, with the
  # trade-off written out honestly: PostgreSQL never applies a policy to a
  # superuser, and for GetWorkflowByID and ListWorkflows the policies are the
  # ONLY tenant isolation, so the refusal being silenced was the check doing
  # its job. The justification given was that these ports are single-tenant and
  # "cannot observe a cross-tenant leak either way".
  #
  # THAT REASONING COVERS ONE OF THE TWO FAILURE DIRECTIONS. It is sound for
  # fail-OPEN -- a leak a single-tenant suite cannot see. It says nothing about
  # fail-CLOSED, where the policy raises and the call errors, which a
  # single-tenant port observes perfectly well. cleat#1177 is exactly that:
  # successorOfRun issued its SELECT outside beginTxWithRLS, so every
  # continue-as-new chain walk raised `cleat.tenant_id is not set` -- on a
  # superuser connection, silently not.
  #
  # And the asymmetry makes this the wrong dialect to switch off. MySQL and SQL
  # Server carry `AND tenant_id = ?` and never depended on RLS, so a defect of
  # this shape is PostgreSQL-only. PostgreSQL is the dialect this harness runs.
  #
  # The split is the one docker-compose.cluster.yml ships: --db unprivileged,
  # --migrate-db on the owner. CLEAT_PORTS_DSN stays the owner because
  # migrations and -generate-api-key both need privileges cleat_app has not got.
  #
  # ensure_app_role is therefore NOT optional, and that is stronger than it looks:
  # with -rls-check=off gone, the worker REFUSES rather than warns. The refuse arm
  # is `-rls-check=require || (auto && --require-auth)`, and --require-auth
  # defaults true, so `auto` on a superuser connection exits 1. Measured
  # 2026-09-10 against PostgreSQL 16.15, one DSN, one flag varied:
  #
  #   -db only (defaults)    ERROR "refusing to start: ... not subject to
  #                          row-level security", exit 1
  #   --require-auth=false   WARN, same text, worker continues
  #   -rls-check=off         no RLS message at all, worker continues
  #
  # So a regression here does not quietly downgrade this harness to the old
  # superuser configuration -- it stops the worker starting, and every port fails
  # on connection refused. That is the failure mode to want. It is also not
  # hypothetical: while #204 was being written, CLEAT_PORTS_RUNTIME_DSN was
  # composed from CLEAT_PORTS_PG_PORT while CLEAT_PORTS_DSN was overridden
  # wholesale, so the worker was pointed at a different database than the owner
  # and 113 tests failed on connection refused. Loud, and diagnosed in minutes --
  # which is the argument for a configuration that cannot silently fall back.
  ensure_app_role || exit 1
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

  # CLEAT_PORTS_WORKER_EXTRA_FLAGS appends flags to the worker.
  #
  # The flags above are the ones every port needs. A test that needs the worker
  # configured differently -- a short --retention-days, a --retention-interval
  # -- had no way to ask for it, so a whole class of behaviour was unreachable
  # from the suite regardless of how the test was written.
  #
  # Word-split deliberately, so a caller can pass more than one flag:
  #
  #   CLEAT_PORTS_WORKER_EXTRA_FLAGS="-retention-days 1 -retention-interval 5s"
  #
  # which means a value containing whitespace cannot be passed this way. That
  # is the documented limit rather than an oversight: an array would carry it,
  # and an array cannot survive an environment variable, which is the interface
  # a pytest fixture actually has.
  #
  # It is also recorded in the log, because a worker started with different
  # flags is a different worker and a run that cannot say which one it had is
  # not reproducible.
  local extra=()
  if [ -n "${CLEAT_PORTS_WORKER_EXTRA_FLAGS:-}" ]; then
    # shellcheck disable=SC2206
    extra=( $CLEAT_PORTS_WORKER_EXTRA_FLAGS )
    echo "worker extra flags: ${extra[*]}"
  fi

  ( cd "$SRC" && exec "$ROOT/bin/cleat-worker" \
      -db "$CLEAT_PORTS_RUNTIME_DSN" \
      -migrate-db "$CLEAT_PORTS_DSN" \
      -driver "$CLEAT_PORTS_DIALECT" \
      -api-addr "127.0.0.1:$API_PORT" \
      -bench-svc-url "$CLEAT_PORTS_FIXTURE_URL" \
      -plugin-config "$PLUGIN_CONFIG" \
      -enable-admin-api \
      ${extra[@]+"${extra[@]}"} \
      >"$LOGFILE" 2>&1 ) &
  echo $! > "$PIDFILE"

  # Wait for readiness rather than sleeping. A fixed sleep is either slower
  # than it needs to be or, on a cold database that has migrations to run,
  # too short -- and too short shows up as a confusing connection-refused in
  # the first test rather than as a worker problem.
  #
  # The budget is 90s *without output*, not 30s in total. Progress is the log
  # growing: a worker that is still writing gets more time, one that has gone
  # quiet is abandoned.
  #
  # WHAT ACTUALLY GOES WRONG HERE, measured rather than assumed. A cold start
  # is not slow because of the migration set -- that is 4-6s of the old 30s
  # (postgres 0.6s, mssql 1.7s, mysql 5.9s locally; 0.9/1.9/4.4s on the CI
  # runner, same commit as the failing run). It is slow because MySQL applies
  # the set TWICE, once for the main database and once per tenant, and the
  # phase between the two passes -- TenantDB -> CreateTenantDatabase -- logs
  # nothing at all. Over four cold runs the two migration passes took 2s every
  # time and the silent gap between them took 1s, 1s, 9s, 1s. The variance is
  # entirely in the part that produces no output.
  #
  # So the failure this replaces was a SILENT stall of roughly 22-26s hitting
  # a 30s cap, not a migration set outgrowing its budget. That is why the
  # no-output budget is 90s and not 30s: the thing being waited through is
  # invisible by construction, so the margin has to cover it rather than track
  # it. cleat#1084 asks for a log line before CreateTenantDatabase; if that
  # lands, this loop sees the phase and the 90s stops doing any work.
  #
  # The cost is that a genuinely hung worker takes 90s rather than 30s to
  # report. That is the honest price of not being able to tell the two apart.
  # last_size starts BELOW any real size so the first pass always counts as
  # progress. Starting it at 0 made the stall counter run one tick ahead of
  # the elapsed counter, and the give-up message then reported a longer stall
  # than the wait that contained it -- "29s elapsed, last 30s of it with
  # nothing written".
  local waited=0 stalled=0 size=0 last_size=-1
  while [ "$waited" -lt 600 ]; do          # 300s absolute ceiling
    healthy && { mint_key; echo "worker ready at $API_URL (pid $(cat "$PIDFILE"))"; return 0; }
    running || { echo "worker exited during startup; log follows:" >&2
                 tail -20 "$LOGFILE" >&2; rm -f "$PIDFILE"; exit 1; }
    size=$(wc -c <"$LOGFILE" 2>/dev/null | tr -d ' ')
    if [ "${size:-0}" -gt "$last_size" ]; then
      last_size="$size"; stalled=0
    else
      stalled=$((stalled + 1))
      [ "$stalled" -ge 180 ] && break
    fi
    sleep 0.5
    waited=$((waited + 1))
  done

  echo "worker did not become healthy: $((waited / 2))s elapsed," \
       "last $((stalled / 2))s of it with nothing written to the log;" \
       "log follows:" >&2
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
      # `[ -f "$PIDFILE" ] && ! owned` was wrong, and wrong in the direction
      # that fails OPEN. With no pidfile at all the && short-circuits false,
      # the refusal is skipped, and ensure ADOPTS whatever is serving the port
      # -- printing "(pid unknown)" and exiting 0. A mismatched
      # CLEAT_PORTS_RESULTS_DIR produces exactly that state.
      #
      # `owned` already returns 1 for an absent pidfile, an empty one, one
      # naming a dead process, and one naming a foreign worker, so testing it
      # alone covers every case the old form meant to cover plus the one it
      # let through.
      #
      # This is the GENERATOR of ports#172/#173: an adopted worker is live but
      # untracked, so every later pid-based operation has nothing to act on.
      # `crash` then killed nothing and returned 0, and five recovery tests
      # silently measured the uncrashed control and passed. Fixing `crash`
      # without fixing this leaves the thing that manufactures the state.
      if ! owned; then
        cat >&2 <<MSG
something is already serving $API_URL and this invocation cannot claim it.

  pidfile: $PIDFILE ($(cat "$PIDFILE" 2>/dev/null || echo "no pid"))
  serving: $(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -1 | xargs -I{} ps -ww -p {} -o command= 2>/dev/null || echo "unknown")

Reusing it would run this session against another session's database while
authenticating with this session's key -- which fails as "401 invalid or
revoked API key" and names the wrong thing.

If the process above is YOUR worker on the right port but a different -db, this
is a dialect switch: stop it first with "worker.sh stop". ensure will not reuse
a worker that is not serving the database this invocation asked for.

Otherwise set CLEAT_PORTS_API_PORT (and CLEAT_PORTS_FIXTURE_PORT) to a free port.
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
  stop-worker)
    # Stops the WORKER and leaves the fixture service running.
    #
    # `stop` takes the fixture down too, which is right when a run is ending
    # and wrong for anything that stops one worker while the suite continues.
    # The fixture service is SHARED -- one per session, not one per instance --
    # so a second worker's teardown calling `stop` silently removes the service
    # every remaining test depends on. Observed: tearing down instance 2 after
    # tests/test_cross_worker.py left tests/test_priority_order.py failing on
    # URLError, which reads as a product defect and is a harness one.
    stop_worker
    ;;
  url) echo "$API_URL" ;;
  *) echo "usage: worker.sh <ensure|crash|stop|stop-worker|url>" >&2; exit 2 ;;
esac
