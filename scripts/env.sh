#!/usr/bin/env bash
# Shared defaults for the port harness. Sourced, not executed.
#
# One definition of each default, because there are two of them and they have
# to agree: the database port here and in docker-compose.yml, and the API port
# here and in whatever starts the worker. The 5432 collision this repo already
# fixed was a default that was right in one file and wrong in another, so these
# live in exactly one place and every script reads them from here.

# Which dialect this run targets. postgres unless asked otherwise; the other
# two need their compose profile started (see docker-compose.yml).
: "${CLEAT_PORTS_DIALECT:=postgres}"

# Host ports for the compose databases. None of them are the dialect's default:
# cleat's own dev compose binds 5432/3306/1433 and other work in progress may
# hold the obvious alternatives, so a collision would fail before a single test
# ran. Container-side ports are untouched.
: "${CLEAT_PORTS_PG_PORT:=5442}"
: "${CLEAT_PORTS_MYSQL_PORT:=3309}"
: "${CLEAT_PORTS_MSSQL_PORT:=1436}"

# One DSN per dialect, selected below. They are spelled out rather than built
# from parts because the three drivers disagree about syntax in ways a shared
# template hides: MySQL wants user:pass@tcp(host:port)/db, SQL Server wants a
# URL with the database as a query parameter, and only PostgreSQL takes the
# form everyone reaches for first. cmd/cleat-worker's -db flag documents all
# three.
: "${CLEAT_PORTS_DSN_POSTGRES:=postgres://postgres:postgres@localhost:${CLEAT_PORTS_PG_PORT}/cleat_ports?sslmode=disable}"

# The RUNTIME PostgreSQL DSN, which is a different role from the one above.
#
# CLEAT_PORTS_DSN stays the owner: it applies migrations and generates API
# keys, both of which need privileges the application role does not have. The
# worker's own --db is this one, an unprivileged role that RLS actually
# applies to. That split is what docker-compose.cluster.yml ships (--db as
# cleat_app, --migrate-db as the owner), and cleat-ports#198 is what it costs
# not to have it: PostgreSQL never applies a policy to a superuser, so the one
# dialect where the policies ARE the tenant isolation was the one running
# without them.
# DERIVED FROM CLEAT_PORTS_DSN, not rebuilt from parts.
#
# The first version of this composed the runtime DSN out of
# CLEAT_PORTS_PG_PORT, and that is a second derivation of the same fact.
# CLEAT_PORTS_DSN can be overridden wholesale -- every agent sandbox does
# exactly that -- and then the two disagree: the owner connection went to one
# port and the worker to another, which surfaced as 113 connection-refused
# failures with nothing pointing at the cause.
#
# Substituting the credentials into the DSN that is already in force cannot
# drift, because there is only one source for host, port and database.
: "${CLEAT_PORTS_DSN_MYSQL:=root:cleat@tcp(127.0.0.1:${CLEAT_PORTS_MYSQL_PORT})/cleat_ports?parseTime=true&multiStatements=true}"
: "${CLEAT_PORTS_DSN_MSSQL:=sqlserver://sa:Cleat%21Passw0rd@localhost:${CLEAT_PORTS_MSSQL_PORT}?database=cleat_ports}"

# CLEAT_PORTS_RUNTIME_DSN is what the worker connects as; CLEAT_PORTS_DSN
# remains the privileged connection everything else uses. They differ only on
# PostgreSQL -- MySQL and SQL Server have no RLS to be subject to, and their
# tenant scoping is in the queries themselves.
case "$CLEAT_PORTS_DIALECT" in
  postgres)
    : "${CLEAT_PORTS_DSN:=$CLEAT_PORTS_DSN_POSTGRES}"
    : "${CLEAT_PORTS_APP_PASSWORD:=cleat-app-ports-local}"
    : "${CLEAT_PORTS_RUNTIME_DSN:=postgres://cleat_app:${CLEAT_PORTS_APP_PASSWORD}@${CLEAT_PORTS_DSN#*@}}"
    ;;
  mysql)
    : "${CLEAT_PORTS_DSN:=$CLEAT_PORTS_DSN_MYSQL}"
    : "${CLEAT_PORTS_RUNTIME_DSN:=$CLEAT_PORTS_DSN_MYSQL}"
    ;;
  mssql)
    : "${CLEAT_PORTS_DSN:=$CLEAT_PORTS_DSN_MSSQL}"
    : "${CLEAT_PORTS_RUNTIME_DSN:=$CLEAT_PORTS_DSN_MSSQL}"
    ;;
  *) echo "CLEAT_PORTS_DIALECT must be postgres, mysql or mssql (got: $CLEAT_PORTS_DIALECT)" >&2; exit 2 ;;
esac

# Listen port for the fixture service the ports call to make failures happen on
# purpose. The worker forwards unrecognised service calls here; see
# scripts/fixture-service.py.
: "${CLEAT_PORTS_FIXTURE_PORT:=8098}"
: "${CLEAT_PORTS_FIXTURE_URL:=http://127.0.0.1:${CLEAT_PORTS_FIXTURE_PORT}}"

# Listen port for the shared worker's HTTP API.
: "${CLEAT_PORTS_API_PORT:=8099}"
: "${CLEAT_PORTS_API:=http://127.0.0.1:${CLEAT_PORTS_API_PORT}}"

# The default tenant every port runs as, and the name of the SECOND one.
#
# "Single-tenant by design" is what this said, and it was the accurate
# description of a harness that could not observe a cross-tenant leak. Two
# changes removed that, in the two directions a policy can fail:
# cleat-ports#198 put the worker on cleat_app with the RLS check on, which
# makes a fail-CLOSED defect visible; #210 adds a second tenant, without which
# a fail-OPEN one has no foreign row to return and so cannot be seen at all.
#
# The second tenant is PostgreSQL-only and provisioned by worker.sh, not here:
# its id is whatever --create-tenant minted, so it cannot be a constant the way
# the default tenant's all-zeros UUID is.
: "${CLEAT_PORTS_TENANT:=00000000-0000-0000-0000-000000000000}"
: "${CLEAT_PORTS_TENANT_B_NAME:=cleat-ports-tenant-b}"

# Where this run keeps its pidfiles, logs, minted keys and built WASM.
#
# Keyed by COMPOSE_PROJECT_NAME because that is already how a session declares
# its identity here: it isolates the databases, and until 2026-09-08 it isolated
# nothing else. Several sessions run out of one checkout, and a flat
# .port-results/ gave them ONE worker.pid, ONE api-key.<dialect> and ONE
# worker.log between them.
#
# The cost of that was not a collision anyone could see. All three symptoms
# present as `401 invalid or revoked API key` -- naming authentication, which is
# the one thing that is not wrong -- so a session reads it as the stale-key
# hazard the Makefile documents and moves on. Three separate sessions did,
# tonight. Worse, `worker.sh ensure` decides "up but not serving" by comparing
# THIS session's health URL against the SHARED pidfile, so it stopped a live
# worker belonging to somebody else and reported it as restarting its own.
: "${CLEAT_PORTS_RESULTS_ROOT:=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.port-results}"
: "${CLEAT_PORTS_RESULTS_DIR:=$CLEAT_PORTS_RESULTS_ROOT/${COMPOSE_PROJECT_NAME:-default}}"

export CLEAT_PORTS_RESULTS_ROOT CLEAT_PORTS_RESULTS_DIR
export CLEAT_PORTS_DIALECT CLEAT_PORTS_MYSQL_PORT CLEAT_PORTS_MSSQL_PORT
export CLEAT_PORTS_FIXTURE_PORT CLEAT_PORTS_FIXTURE_URL
export CLEAT_PORTS_TENANT CLEAT_PORTS_TENANT_B_NAME CLEAT_PORTS_PG_PORT CLEAT_PORTS_DSN CLEAT_PORTS_API_PORT CLEAT_PORTS_API
