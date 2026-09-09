#!/usr/bin/env bash
#
# Prove the run that just finished used the dialect it claims.
#
# A dialect matrix that silently runs PostgreSQL three times under three names
# passes every test and proves nothing -- the matrix key is a string this repo
# wrote, so asserting on it establishes only that someone can type. This asks
# the database instead.
#
# THE DISCRIMINATOR IS NOT "the claimed dialect has rows".
#
# `make deps DIALECT=mysql` starts postgres AND mysql (see the Makefile: the
# fixture service and the harness both expect postgres up regardless), so a leg
# that had silently fallen back to PostgreSQL would still find rows -- in
# PostgreSQL. Checking only the claimed dialect would pass in exactly the case
# this script exists to catch.
#
# So for a non-postgres leg it asserts both halves:
#
#   the claimed dialect HAS workflow rows   -- the run reached it
#   postgres has NONE                       -- the run did not go there instead
#
# Usage: scripts/assert-dialect.sh <postgres|mysql|mssql>
set -euo pipefail

dialect="${1:?usage: assert-dialect.sh <postgres|mysql|mssql>}"
: "${MSSQL_SA_PASSWORD:=Cleat!Passw0rd}"

count_in() {
  case "$1" in
    postgres)
      docker compose exec -T postgres \
        psql -U postgres -d cleat_ports -tAc \
        "SELECT count(*) FROM workflow_instances" 2>/dev/null | tr -d '[:space:]'
      ;;
    mysql)
      docker compose exec -T mysql \
        mysql -uroot -pcleat -N -B cleat_ports \
        -e "SELECT count(*) FROM workflow_instances" 2>/dev/null | tr -d '[:space:]'
      ;;
    mssql)
      docker compose exec -T mssql \
        /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" \
        -C -d cleat_ports -h -1 -W -Q \
        "SET NOCOUNT ON; SELECT count(*) FROM workflow_instances" 2>/dev/null | tr -d '[:space:]'
      ;;
    *) echo "unknown dialect: $1" >&2; return 2 ;;
  esac
}

# Second, independent fact: what the server says it is. A row count proves
# something wrote to that container; this proves the container is the engine it
# claims to be. Neither is sufficient alone -- a leg could talk to the right
# server and run its tests against another, or exec into a container whose
# image is not what the compose service name suggests -- so both are required.
version_of() {
  case "$1" in
    postgres)
      docker compose exec -T postgres psql -U postgres -d cleat_ports -tAc \
        "SELECT version()" 2>/dev/null | head -1
      ;;
    mysql)
      docker compose exec -T mysql mysql -uroot -pcleat -N -B \
        -e "SELECT @@version" 2>/dev/null | head -1
      ;;
    mssql)
      docker compose exec -T mssql \
        /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" \
        -C -h -1 -W -Q "SET NOCOUNT ON; SELECT @@VERSION" 2>/dev/null | head -1
      ;;
  esac
}

# A `case`, not an associative array: `declare -A` needs bash 4, and macOS ships
# 3.2 as /bin/bash, where `[postgres]=` is parsed as an arithmetic index and the
# script dies with "postgres: unbound variable". GitHub runners have bash 5, so
# this would have worked in CI and failed for every developer running it locally
# -- the wrong way round for a check people are meant to reproduce.
case "$dialect" in
  postgres) want="PostgreSQL" ;;
  mysql)    want="8." ;;
  mssql)    want="Microsoft SQL Server" ;;
esac

ver="$(version_of "$dialect")"
case "$ver" in
  *"$want"*)
    echo "ok: ${dialect} identifies itself as: ${ver:0:60}"
    ;;
  *)
    echo "FAIL: the ${dialect} container does not identify as ${dialect}." >&2
    echo "      expected a version string containing '${want}', got: '${ver}'" >&2
    exit 1
    ;;
esac

claimed="$(count_in "$dialect")"
claimed="${claimed:-}"

# A non-numeric or empty answer is a broken probe, not a passing one. Without
# this, a container that is not running returns "" and every comparison below
# would be against the empty string.
case "$claimed" in
  ''|*[!0-9]*)
    echo "FAIL: could not count workflow_instances in ${dialect} (got: '${claimed}')." >&2
    echo "      The probe is broken; this is not evidence the run used ${dialect}." >&2
    exit 1
    ;;
esac

if [ "$claimed" -eq 0 ]; then
  echo "FAIL: ${dialect} has no workflow_instances rows after the port ran." >&2
  echo "      The run did not reach the database it claims to have used." >&2
  exit 1
fi

echo "ok: ${dialect} holds ${claimed} workflow_instances row(s)"

# The discriminator. postgres is up for every dialect, so a silent fallback
# lands there and is invisible to the check above.
if [ "$dialect" != "postgres" ]; then
  pg="$(count_in postgres)"
  pg="${pg:-}"
  case "$pg" in
    ''|*[!0-9]*)
      echo "FAIL: could not count workflow_instances in postgres (got: '${pg}')." >&2
      echo "      Cannot rule out a silent fallback, so this leg is not evidence." >&2
      exit 1
      ;;
  esac
  if [ "$pg" -ne 0 ]; then
    echo "FAIL: this leg claims ${dialect}, but postgres also holds ${pg} workflow_instances row(s)." >&2
    echo "      postgres is started for every dialect, so rows there mean the run went to" >&2
    echo "      postgres -- exactly the false green a dialect matrix is prone to." >&2
    exit 1
  fi
  echo "ok: postgres holds 0 rows, so this leg did not silently fall back"
fi
