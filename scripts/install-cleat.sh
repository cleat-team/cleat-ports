#!/usr/bin/env bash
# Install the cleat toolchain at a given ref into ./bin.
#
# A ref, not a published version: ports need to run against cleat's development
# branch nightly, and `go install pkg@develop` does not resolve branch names.
# So this clones at the ref and builds from source, which also means the version
# under test is a commit SHA we can put in a bug report.
set -euo pipefail

REF="${1:?usage: install-cleat.sh <ref>}"
REPO="${CLEAT_REPO:-github.com/cleat-team/cleat}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/bin"
SRC="$ROOT/.cleat-src"

mkdir -p "$BIN"
rm -rf "$SRC"
git clone --quiet --depth 1 --branch "$REF" "https://$REPO.git" "$SRC" 2>/dev/null \
  || { # not a branch or tag — try a bare clone and checkout, for a commit SHA
       git clone --quiet "https://$REPO.git" "$SRC"
       git -C "$SRC" checkout --quiet "$REF"; }

SHA="$(git -C "$SRC" rev-parse HEAD)"
echo "cleat ref=$REF sha=$SHA"

( cd "$SRC" && CGO_ENABLED=0 go build -o "$BIN/cleat" ./cmd/cleat )

# cleat-worker as well as cleat. The CLI has no `worker` subcommand -- the
# engine is a separate binary -- so a port that actually executes a workflow,
# rather than just checking the toolchain is present, needs this one too.
#
# CGO_ENABLED=1 here, unlike the CLI above, and it is not optional: wasmtime is
# the only WASM backend cleat has and it is behind `//go:build cgo`. Built with
# CGO_ENABLED=0 the worker starts, migrates, serves nothing, and dies with
#   wasmtime backend failed to initialize; ... requires CGO
# Core's own CI carries the same warning against CGO_ENABLED=0 for vet -- the
# build tag takes backend_wasmtime.go out of ./engine/ entirely, so what you
# analysed, or here linked, is not what ships.
( cd "$SRC" && CGO_ENABLED=1 go build -o "$BIN/cleat-worker" ./cmd/cleat-worker )

# Recorded so a failing run can name the exact commit under test rather than a
# branch name that has moved on by the time anyone reads the log.
printf 'ref=%s\nsha=%s\n' "$REF" "$SHA" > "$ROOT/bin/.cleat-build"
"$BIN/cleat" version || true
