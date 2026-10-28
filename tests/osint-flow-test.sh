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
grep -q 'Maigret failed' "$tmp/scan-output"

mkdir "$tmp/phone-workspace"
export WORKSPACE="$tmp/phone-workspace"
printf '+1234567890' > "$tmp/phones.txt"
printf '4\n%s\n10\n1\n8\n5\n' "$tmp/phones.txt" | bash "$root/scripts/osint-flow.sh" > "$tmp/phone-output" 2>&1
grep -qx '+1234567890' "$tmp/phone-workspace"/osint-*/target_phone.txt
echo 'osint-flow checks passed'
