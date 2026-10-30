#!/usr/bin/env bash
set -eu
python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/install_tools.py"
if [ "$#" -gt 0 ]; then exec "$@"; fi
