#!/usr/bin/env bash
# Self-test for how scripts/worker.sh asks `cleat-worker -h` whether a flag exists.
#
# worker.sh reads the help text into a variable and matches it with `case`. It used
# to do `printf '%s' "$help_text" | grep -q -- "-org "` under `set -o pipefail`,
# which is a race: grep -q exits at its first match, printf is still writing ~55 KB
# and takes SIGPIPE, and pipefail reports the whole pipeline as failed -- so a flag
# that is PRESENT reads as absent, only sometimes (cleat-ports 11-22 and 11-25
# nightlies: "printf: write error: Broken pipe", then "--org is required").
#
# Three things are checked, and the third is the one that keeps this from
# certifying nothing:
#   1. the matching form worker.sh uses finds a present flag 300 times out of 300
#      on a text larger than any pipe buffer, with pipefail on;
#   2. it still says "absent" for an absent flag (a negative control: a matcher that
#      always says yes passes check 1);
#   3. worker.sh contains no `printf ... | grep` over help_text, and that scan DOES
#      flag the old line (a known positive), so a scan that matches nothing is caught.
#
# Exit status: 0 passed, 1 a finding, 2 could not establish what was measured.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
W="$ROOT/scripts/worker.sh"
[ -r "$W" ] || { echo "UNMEASURED: cannot read $W (this is a failure of the check, not a finding about the tree)" >&2; exit 2; }
fails=0

# A 200 KB help text with the flags near the front, where grep -q would exit first.
help_text="$(printf -- '  -create-tenant string\n  -org string\n'; head -c 200000 /dev/zero | tr '\0' 'x')"
[ "${#help_text}" -gt 100000 ] || { echo "UNMEASURED: the synthetic help text is only ${#help_text} bytes" >&2; exit 2; }

has_flag() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

miss=0
for _ in $(seq 300); do has_flag "$help_text" "-org " || miss=$((miss + 1)); done
if [ "$miss" -ne 0 ]; then echo "FAIL  present flag read as absent $miss of 300 times"; fails=$((fails + 1)); else echo "ok    present flag found 300 of 300 (help text ${#help_text} bytes, pipefail on)"; fi

if has_flag "$help_text" "-no-such-flag "; then echo "FAIL  an absent flag was reported present"; fails=$((fails + 1)); else echo "ok    an absent flag is reported absent"; fi

# The scan: a pipe from printf/echo of help_text into grep, comments excluded.
scan() { grep -nE "^[^#]*(printf|echo)[^|]*help_text[^|]*\|[[:space:]]*grep" "$1"; }
printf '%s\n' "  if printf '%s' \"\$help_text\" | grep -q -- \"-org \"; then" > "${TMPDIR:-/tmp}/helptext-positive.$$"
if scan "${TMPDIR:-/tmp}/helptext-positive.$$" >/dev/null; then echo "ok    the scan flags the old printf|grep line (known positive)"; else echo "FAIL  the scan did not flag the old line, so it checks nothing"; fails=$((fails + 1)); fi
rm -f "${TMPDIR:-/tmp}/helptext-positive.$$"
if hits=$(scan "$W"); then echo "FAIL  worker.sh pipes help_text into grep again:"; echo "$hits"; fails=$((fails + 1)); else echo "ok    worker.sh has no printf|grep over help_text"; fi

# worker.sh must still ask both questions with case.
for flag in '-create-tenant' '-org '; do
  grep -qF "*\"$flag\"*" "$W" || { echo "FAIL  worker.sh has no case match for \"$flag\""; fails=$((fails + 1)); }
done

[ "$fails" -eq 0 ] && echo "PASS" || { echo "FAILED: $fails"; exit 1; }
