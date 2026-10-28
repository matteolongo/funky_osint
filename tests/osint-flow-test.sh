#!/usr/bin/env bash
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/workspace"
printf '#!/usr/bin/env bash\nexit 0\n' > "$tmp/bin/sleep"
printf '#!/usr/bin/env bash\nexit 0\n' > "$tmp/bin/clear"
printf '#!/usr/bin/env bash\necho scan failed\nexit 1\n' > "$tmp/bin/maigret"
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" WORKSPACE="$tmp/workspace"

printf 'alice\nalice@example.com\n' > "$tmp/pivots.txt"
printf '4\n%s\n9\n' "$tmp/pivots.txt" | bash "$root/scripts/osint-flow.sh" > "$tmp/import-output"
grep -qx 'alice' "$tmp/workspace"/osint-*/pivot_usernames.txt
grep -qx 'alice@example.com' "$tmp/workspace"/osint-*/pivot_emails.txt

printf '2\nalice\n9\n' | bash "$root/scripts/osint-flow.sh" > "$tmp/scan-output"
grep -q 'maigret failed' "$tmp/scan-output"

mkdir "$tmp/phone-workspace"
export WORKSPACE="$tmp/phone-workspace"
printf '+1234567890' > "$tmp/phones.txt"
printf '4\n%s\n10\n1\n8\n5\n' "$tmp/phones.txt" | bash "$root/scripts/osint-flow.sh" > "$tmp/phone-output" 2>&1
grep -qx '+1234567890' "$tmp/phone-workspace"/osint-*/target_phone.txt

printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$@" > "$WORKSPACE/ignorant-args"\n' > "$tmp/bin/ignorant"
chmod +x "$tmp/bin/ignorant"
mkdir "$tmp/ignorant-workspace"
export WORKSPACE="$tmp/ignorant-workspace"
printf '1\n+1234567890\n+1\n9\n' | bash "$root/scripts/osint-flow.sh" > "$tmp/ignorant-output" 2>&1
printf '+1\n234567890\n' > "$tmp/expected-args"
cmp "$tmp/expected-args" "$tmp/ignorant-workspace/ignorant-args"

printf '#!/usr/bin/env bash\nprintf "[+] Example: https://example.org/alice\\n"\n' > "$tmp/bin/sherlock"
chmod +x "$tmp/bin/sherlock"
mkdir "$tmp/graph-workspace"
export WORKSPACE="$tmp/graph-workspace"
printf '2\nalice\n9\n' | bash "$root/scripts/osint-flow.sh" > "$tmp/graph-output" 2>&1
python3 - "$tmp/graph-workspace" <<'PY'
import json, pathlib, sys
case = next(pathlib.Path(sys.argv[1]).glob('osint-*/case.json'))
data = json.loads(case.read_text())
assert {s['status'] for s in data['scans']} == {'failed', 'completed'}
assert data['accounts'][0]['url'] == 'https://example.org/alice'
assert data['relationships'][0]['source'] == next(s['id'] for s in data['scans'] if s['tool'] == 'sherlock')
assert all((case.parent / s['output']).is_file() for s in data['scans'])
PY

mkdir "$tmp/argument-workspace"
export WORKSPACE="$tmp/argument-workspace"
printf '9\n' | bash "$root/scripts/osint-flow.sh" direct_username > "$tmp/argument-output" 2>&1
grep -qx 'direct_username' "$tmp/argument-workspace"/osint-*/target_username.txt
echo 'osint-flow checks passed'
