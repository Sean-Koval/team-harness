#!/bin/bash
# regression-v0 grader (team-harness flightdeck/suites/regression-v0/README.md), from flightdeck's template.
# Runs the merged PR's test file(s) in this directory against the agent's tree, from a pristine copy.
#   the agent's tree   $FLIGHTDECK_WORKDIR, else $HANGAR_REPO (hangar's grader), else the current directory (Harbor)
#   these tests        this script's directory: test_*.py and conftest.py, copied out before the agent's code runs
#   support files      the rest of the tree's tests/ (fixtures, modules they import) and files at the repo root;
#                      every conftest.py under tests/ is replaced by the hidden one, and none above it loads
#   the reward         $FLIGHTDECK_REWARD_DIR/reward.json, else /logs/verifier/reward.json; also $HANGAR_GRADE_OUT
# The image must already have the repository's dependencies and pytest: hangar's grader has no network.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${FLIGHTDECK_WORKDIR:-${HANGAR_REPO:-$PWD}}
OUT=${FLIGHTDECK_REWARD_DIR:-/logs/verifier}
G=$(mktemp -d "${TMPDIR:-/tmp}/grade.XXXXXX")
trap 'rm -rf "$G"' EXIT
mkdir -p "$OUT" 2>/dev/null && [ -w "$OUT" ] || OUT=$G/reward
mkdir -p "$OUT" "$G/hidden"
cp "$HERE"/*.py "$G/hidden/"                            # the pristine copy, outside the agent's tree
cp -R "$WORK" "$G/work" && rm -rf "$G/work/.git"        # the code under test, with its tests/ as support files
mkdir -p "$G/work/tests"
find "$G/work/tests" -name conftest.py -delete          # only the hidden copy's conftest.py loads
cp "$G/hidden/"*.py "$G/work/tests/"                    # the hidden files replace the tree's own copies
cd "$G/work" || exit 2
# Nothing the agent's tree carries loads first: -c /dev/null drops its pytest settings, --confcutdir keeps conftest
# discovery inside the hidden copy, python -I drops sitecustomize.py, the user site and PYTHON* variables.
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 GRADE_WORK="$G/work"
tests=$(cd "$G/hidden" && ls test_*.py | sed "s|^|tests/|")
# shellcheck disable=SC2086
timeout 600 python3 -I -m pytest -p no:cacheprovider -c /dev/null --rootdir "$G/work" --confcutdir "$G/work/tests" \
  -o addopts= -o asyncio_mode=auto -o "pythonpath=$G/work/src $G/work" -q -W ignore::pytest.PytestConfigWarning \
  $tests
code=$?
reward=0; [ "$code" -eq 0 ] && reward=1
echo "{\"reward\": $reward, \"exit_code\": $code}" > "$OUT/reward.json"
[ -n "${HANGAR_GRADE_OUT:-}" ] && cp "$OUT/reward.json" "$HANGAR_GRADE_OUT"
exit "$code"
