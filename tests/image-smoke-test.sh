#!/usr/bin/env bash
set -eu

image=${1:-osint_me:local}
docker run --rm --entrypoint bash "$image" -c '
    set -eu
    for tool in phoneinfoga sherlock maigret holehe ignorant; do
        "$tool" --help >/dev/null 2>&1
    done
    for tool in sherlock maigret holehe ignorant; do
        /opt/tools/$tool/bin/python -m pip check
        test "$(readlink /usr/local/bin/$tool)" = "/opt/tools/$tool/bin/$tool"
    done
    python3 -c "import json; d=json.load(open(\"/tools/versions.json\")); assert len(d)==5; assert all(len(t[\"revision\"])==40 for t in d.values())"
    export TERM=xterm WORKSPACE=/tmp/osint-test
    printf "alice\nalice@example.com\n" > /tmp/pivots
    printf "4\n/tmp/pivots\n9\n" | osint >/dev/null
    grep -qx alice /tmp/osint-test/osint-*/pivot_usernames.txt
    grep -qx alice@example.com /tmp/osint-test/osint-*/pivot_emails.txt
    python3 - <<EOF
import glob, json
paths = glob.glob("/tmp/osint-test/osint-*/case.json")
assert len(paths) == 1
data = json.load(open(paths[0]))
assert {i["value"] for i in data["identifiers"]} == {"alice", "alice@example.com"}
EOF
'
docker run --rm --entrypoint bash "$image" -c '
    set -eu
    git init -q -b master /tmp/source
    git -C /tmp/source -c user.name=test -c user.email=test@example.com commit -q --allow-empty -m fixture
    revision=$(git -C /tmp/source rev-parse HEAD)
    cat > /repos.yml <<EOF
tools:
  - name: failing-tool
    repo: /tmp/source
    ref: $revision
    dest: /tmp/checkout
    enabled: true
    check_bin: failing-tool
    build:
      apt_deps: [git]
      pre_cmds: []
      cmds: ["false"]
EOF
    if INSTALL_SKIP_APT=1 bash /scripts/install-tools.sh true >/tmp/install.log 2>&1; then
        echo "installer accepted a failed command" >&2
        exit 1
    fi
    grep -q "returned non-zero exit status 1" /tmp/install.log
'
if output=$(docker run --rm --read-only --entrypoint osint "$image" example_username 2>&1); then
    echo 'read-only workspace unexpectedly accepted an investigation' >&2
    exit 1
fi
printf '%s\n' "$output" | grep -q 'dashboard container'
echo 'image smoke checks passed'
