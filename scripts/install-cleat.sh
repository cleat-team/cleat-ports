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

# Recorded so a failing run can name the exact commit under test rather than a
# branch name that has moved on by the time anyone reads the log.
printf 'ref=%s\nsha=%s\n' "$REF" "$SHA" > "$ROOT/bin/.cleat-build"
"$BIN/cleat" version || true
