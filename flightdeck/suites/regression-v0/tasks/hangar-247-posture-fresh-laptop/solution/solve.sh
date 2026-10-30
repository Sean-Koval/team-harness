#!/bin/bash
# Harbor's oracle: the merged pull request's change (without its hidden tests), applied in the working directory.
set -eu
git apply --whitespace=nowarn "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reference.patch"
