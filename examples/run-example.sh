#!/bin/sh
# Build the example superproject in a temp folder and show what
# the checker says about a synced repo, a drifted repo, and a
# fresh clone whose submodules were never initialised. The
# drifted and uninitialised runs fail on purpose, so each run
# is allowed to fail. The temp folder is removed at the end.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
sh "$HERE/make-example.sh" "$TMP"
cd "$TMP"

echo "== synced : submodule checked out at the recorded commit =="
python3 "$ROOT/src/git_submodule_checker.py" synced || true
echo
echo "== super : after the submodule moved on =="
python3 "$ROOT/src/git_submodule_checker.py" super || true
echo
echo "== clone : fresh clone, submodule never initialised =="
python3 "$ROOT/src/git_submodule_checker.py" clone || true
echo
echo "== super --json : the drifted repo as JSON =="
python3 "$ROOT/src/git_submodule_checker.py" --json super || true
