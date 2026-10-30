#!/usr/bin/env bash
set -eu
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/osint_cli.py" "$@"
