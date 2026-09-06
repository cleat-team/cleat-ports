#!/usr/bin/env bash
# Compile a port's workflow package to WASM against the cleat checkout under
# test, and echo the path of the .wasm it produced.
#
#   build-workflow.sh <workflow-package-dir> <out-dir>
#
# Why it stages the sources instead of building them where they live:
#
# `cleat build` finds a local SDK by walking up from the workflow package
# looking for <ancestor>/cleat/go.mod (wasm/build.go, sdkReplaceDir), and it
# then writes the root-module replace as the PARENT of whatever it found. Both
# have to be right at once, so the package must sit under a directory whose
# `cleat/` subdirectory is the SDK and whose own go.mod is the root module --
# which describes the cleat checkout itself and nothing else.
#
# A workflow package living in this repo satisfies neither. The failure is not
# an error, which is the dangerous part: when the search fails, `cleat build`'s
# propagateReplaces deliberately skips the SDK and root replaces -- on the
# grounds that they "were already written above", true only when the search
# succeeded -- so the package's OWN replace is dropped and the build silently
# resolves the SDK from the module proxy. The port would then be testing a
# published release rather than the commit under test. Reported upstream.
set -euo pipefail

PKG="${1:?usage: build-workflow.sh <workflow-package-dir> <out-dir>}"
OUT="${2:?usage: build-workflow.sh <workflow-package-dir> <out-dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/.cleat-src"

[ -d "$PKG" ]           || { echo "no such workflow package: $PKG" >&2; exit 2; }
[ -d "$SRC/cleat" ]     || { echo "no cleat checkout -- run: make install-cleat" >&2; exit 2; }
[ -x "$ROOT/bin/cleat" ]|| { echo "cleat not built -- run: make install-cleat" >&2; exit 2; }

NAME="$(basename "$PKG")"
STAGE="$SRC/.ports-build/$NAME"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp "$PKG"/*.go "$STAGE/"

# Replaces are relative to the stage, which sits two levels under the cleat
# checkout, so they are stable wherever this repo is cloned. They are needed
# for the *analysis* pass, which loads the source package before any code is
# generated; the generated build directory gets its own absolute ones from
# sdkReplaceDir, which now finds the SDK because the stage is inside the
# checkout. The parent module is required too because package cleat's own tests
# import the engine and `go mod tidy` resolves test dependencies.
cat > "$STAGE/go.mod" <<MOD
module cleatports/$NAME

go 1.25

require github.com/cleat-team/cleat/cleat v0.0.0
require github.com/cleat-team/cleat v0.0.0 // indirect

replace github.com/cleat-team/cleat/cleat => ../../cleat
replace github.com/cleat-team/cleat => ../..
MOD

( cd "$STAGE" && GOWORK=off GOFLAGS=-mod=mod go mod tidy ) >&2

mkdir -p "$OUT"
# GOWORK=off: the cleat checkout has a go.work, and a workspace takes
# precedence over the staged package's own go.mod -- go then reports the main
# module as github.com/cleat-team/cleat and refuses to load the package at all,
# because a directory not listed in go.work is not a module of the workspace.
( cd "$STAGE" && GOWORK=off "$ROOT/bin/cleat" build -o "$OUT" . ) >&2

WASM="$(find "$OUT" -maxdepth 1 -name '*.wasm' -print -quit)"
[ -n "$WASM" ] || { echo "cleat build produced no .wasm in $OUT" >&2; exit 1; }
echo "$WASM"
