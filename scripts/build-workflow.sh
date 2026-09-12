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

# CLEAR THE OUTPUT DIRECTORY'S .wasm FILES BEFORE BUILDING, because the tail of
# this script picks one by `find ... -print -quit` and a directory that is never
# emptied can hold more than one.
#
# The name of the .wasm is DERIVED FROM THE ENTRY POINT, not from the package:
# `HandleReuse` becomes handle_reuse.wasm and `HandleIDReuse` becomes
# handle_i_d_reuse.wasm. So renaming an exported function -- or replacing one
# entry point with another, which is an ordinary edit to a workflow under
# development -- leaves the previous build sitting beside the new one under a
# different name, and `find -print -quit` takes whichever the directory lists
# first.
#
# THAT ORDER IS ARBITRARY -- measured three times, with three different
# explanations falsified:
#
#   1. Renaming this package's `HandleIDReuse` to `HandleReuse` and rebuilding
#      into a dirty directory returned the OLD handle_i_d_reuse.wasm and its
#      old SHA256, identical to the previous deploy. The build had succeeded
#      and written a second, different file.
#   2. So: creation order, oldest first? No. A decoy planted AFTER a good
#      build, sorting first alphabetically, was NOT returned.
#   3. So: alphabetical? No. A .port-results/wasm/plugincall/ directory
#      holding two .wasm files a day apart returns the NEWER one.
#
# Each of those, taken alone, supports a tidy rule about which file wins. None
# of the rules survives the other two measurements, which is the point: there
# is nothing here to reason about, only a directory whose listing order the
# script must not depend on.
#
# The failure is silent either way: the build succeeds, writes the new file,
# and the script reports some other path. The deploy that follows ships source
# that no longer exists, and the port then measures it.
rm -f "$OUT"/*.wasm

# GOWORK=off: the cleat checkout has a go.work, and a workspace takes
# precedence over the staged package's own go.mod -- go then reports the main
# module as github.com/cleat-team/cleat and refuses to load the package at all,
# because a directory not listed in go.work is not a module of the workspace.
# CLEAT_PORTS_BUILD_EXTRA_FLAGS appends flags to `cleat build`, mirroring
# CLEAT_PORTS_WORKER_EXTRA_FLAGS (ports#70) for the worker. Added for
# `-version N`, which sets the version embedded in the WASM metadata --
# cmd/deploy-workflow's chooseDeployVersion prefers the embedded value over
# auto-increment, so it is the only way a port can deploy two known versions of
# one definition and say which is which.
#
# Unquoted on purpose: the value is a flag list, and quoting it would pass the
# whole string as a single argument. Unset means no extra flags, so every
# existing caller behaves exactly as before.
# shellcheck disable=SC2086
( cd "$STAGE" && GOWORK=off "$ROOT/bin/cleat" build ${CLEAT_PORTS_BUILD_EXTRA_FLAGS:-} -o "$OUT" . ) >&2

# Remove the staging copy. It lives INSIDE the cleat checkout -- it has to, for
# `cleat build` to find the SDK -- so leaving it behind puts untracked Go files
# in that repo's working tree, where a `git add -A` sweeps them into a commit
# and gofmt lints them. That has happened once; hence this line.
rm -rf "$STAGE"

# EXACTLY ONE, asserted rather than assumed. With the directory cleared above
# this build is the only writer, so two files means `cleat build` emitted two
# entry points from one package -- at which point "the .wasm" is not a thing
# this script can return, and silently choosing one is the failure it was just
# fixed for. Fail naming both.
WASM_LIST="$(find "$OUT" -maxdepth 1 -name '*.wasm' | sort)"
WASM_COUNT="$(printf '%s' "$WASM_LIST" | grep -c . || true)"
case "$WASM_COUNT" in
  1) ;;
  0) echo "cleat build produced no .wasm in $OUT" >&2; exit 1 ;;
  *) echo "cleat build produced $WASM_COUNT .wasm files in $OUT; this script returns one path and cannot choose:" >&2
     echo "$WASM_LIST" >&2
     exit 1 ;;
esac
WASM="$WASM_LIST"
echo "$WASM"
