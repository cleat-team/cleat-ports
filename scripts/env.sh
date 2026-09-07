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
: "${CLEAT_PORTS_DSN_MYSQL:=root:cleat@tcp(127.0.0.1:${CLEAT_PORTS_MYSQL_PORT})/cleat_ports?parseTime=true&multiStatements=true}"
: "${CLEAT_PORTS_DSN_MSSQL:=sqlserver://sa:Cleat%21Passw0rd@localhost:${CLEAT_PORTS_MSSQL_PORT}?database=cleat_ports}"

case "$CLEAT_PORTS_DIALECT" in
  postgres) : "${CLEAT_PORTS_DSN:=$CLEAT_PORTS_DSN_POSTGRES}" ;;
  mysql)    : "${CLEAT_PORTS_DSN:=$CLEAT_PORTS_DSN_MYSQL}" ;;
  mssql)    : "${CLEAT_PORTS_DSN:=$CLEAT_PORTS_DSN_MSSQL}" ;;
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

# The default tenant every port runs as. Single-tenant by design -- see the
# -rls-check note in worker.sh for what that costs.
: "${CLEAT_PORTS_TENANT:=00000000-0000-0000-0000-000000000000}"

export CLEAT_PORTS_DIALECT CLEAT_PORTS_MYSQL_PORT CLEAT_PORTS_MSSQL_PORT
export CLEAT_PORTS_FIXTURE_PORT CLEAT_PORTS_FIXTURE_URL
export CLEAT_PORTS_TENANT CLEAT_PORTS_PG_PORT CLEAT_PORTS_DSN CLEAT_PORTS_API_PORT CLEAT_PORTS_API
