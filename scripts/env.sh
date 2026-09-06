#!/usr/bin/env bash
# Shared defaults for the port harness. Sourced, not executed.
#
# One definition of each default, because there are two of them and they have
# to agree: the database port here and in docker-compose.yml, and the API port
# here and in whatever starts the worker. The 5432 collision this repo already
# fixed was a default that was right in one file and wrong in another, so these
# live in exactly one place and every script reads them from here.

# Host port for the compose Postgres. NOT 5432 -- cleat's own dev compose binds
# that, so the default here must not. See docker-compose.yml.
: "${CLEAT_PORTS_PG_PORT:=5442}"
: "${CLEAT_PORTS_DSN:=postgres://postgres:postgres@localhost:${CLEAT_PORTS_PG_PORT}/cleat_ports?sslmode=disable}"

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

export CLEAT_PORTS_FIXTURE_PORT CLEAT_PORTS_FIXTURE_URL
export CLEAT_PORTS_TENANT CLEAT_PORTS_PG_PORT CLEAT_PORTS_DSN CLEAT_PORTS_API_PORT CLEAT_PORTS_API
