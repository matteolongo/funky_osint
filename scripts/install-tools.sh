#!/usr/bin/env bash
set -e

REPOS_FILE="/repos.yml"
TOOLS_DIR="/tools"
BIN_DIR="/usr/local/bin"

export DEBIAN_FRONTEND=noninteractive

echo "[install-tools] Starting tool installer..."

if ! command -v yq >/dev/null 2>&1 && ! python3 -c "import yaml" >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq python3-yaml >/dev/null 2>&1 || true
fi

if command -v yq >/dev/null 2>&1; then
  PARSER="yq"
elif python3 -c "import yaml" >/dev/null 2>&1; then
  PARSER="pyyaml"
else
  echo "[install-tools] No YAML parser found (need yq or python3-yaml)."
  PARSER="none"
fi

get_count() {
  if [ "$PARSER" = "yq" ]; then
    yq '.tools | length' "$REPOS_FILE"
  elif [ "$PARSER" = "pyyaml" ]; then
    python3 -c "
import yaml
with open('$REPOS_FILE') as f:
    d=yaml.safe_load(f)
print(len(d.get('tools') or []))
" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

count=$(get_count)
echo "[install-tools] Found $count tool(s) in $REPOS_FILE"

i=0
while [ $i -lt $count ]; do
  if [ "$PARSER" = "yq" ]; then
    enabled=$(yq ".tools[$i].enabled" "$REPOS_FILE")
    name=$(yq ".tools[$i].name" "$REPOS_FILE")
    repo=$(yq ".tools[$i].repo" "$REPOS_FILE")
    ref=$(yq ".tools[$i].ref" "$REPOS_FILE")
    dest=$(yq ".tools[$i].dest" "$REPOS_FILE")
    check_bin=$(yq ".tools[$i].check_bin" "$REPOS_FILE")
    apt_deps=$(yq ".tools[$i].build.apt_deps[]?" "$REPOS_FILE" | tr '\n' ' ')
    pre_cmds_count=$(yq ".tools[$i].build.pre_cmds | length" "$REPOS_FILE")
    cmds_count=$(yq ".tools[$i].build.cmds | length" "$REPOS_FILE")
  elif [ "$PARSER" = "pyyaml" ]; then
    read -r enabled name repo ref dest check_bin apt_deps pre_cmds_count cmds_count <<EOF
$(python3 -c "
import yaml
with open('$REPOS_FILE') as f:
    d=yaml.safe_load(f)
t=d['tools'][$i]
enabled=t.get('enabled',True)
name=t.get('name','')
repo=t.get('repo','')
ref=t.get('ref','')
dest=t.get('dest',f'/tools/{name}')
check_bin=t.get('check_bin','')
b=t.get('build') or {}
apt=' '.join(b.get('apt_deps') or [])
pre=len(b.get('pre_cmds') or [])
cmds=len(b.get('cmds') or [])
print(enabled,name,repo,ref,dest,check_bin,apt,pre,cmds)
")
EOF
  else
    i=$((i+1))
    continue
  fi

  [ "$enabled" = "false" ] || [ "$enabled" = "null" ] && echo "[install-tools] Skipping $name (disabled)" && i=$((i+1)) && continue
  [ -z "$name" ] || [ -z "$repo" ] && i=$((i+1)) && continue

  if [ -n "$check_bin" ] && [ "$check_bin" != "null" ] && command -v "$check_bin" >/dev/null 2>&1; then
    echo "[install-tools] $name already installed as $check_bin, skipping"
    i=$((i+1))
    continue
  fi

  echo "[install-tools] Installing $name from $repo"

  if [ -n "$apt_deps" ] && [ "$apt_deps" != "null" ] && [ "$apt_deps" != " " ]; then
    apt-get update -qq
    apt-get install -y -qq $apt_deps >/dev/null 2>&1 || apt-get install -y $apt_deps
  fi

  mkdir -p "$(dirname "$dest")"
  if [ ! -d "$dest/.git" ]; then
    rm -rf "$dest" 2>/dev/null || true
    git clone --depth 1 --branch "${ref:-master}" "$repo" "$dest" 2>/dev/null || git clone --depth 1 "$repo" "$dest"
  else
    echo "[install-tools] Repo already cloned at $dest, updating..."
    git -C "$dest" fetch --depth 1 origin "${ref:-master}" 2>/dev/null || git -C "$dest" fetch --depth 1 2>/dev/null || true
    git -C "$dest" checkout "${ref:-master}" 2>/dev/null || true
    git -C "$dest" pull --ff-only 2>/dev/null || true
  fi

  cd "$dest"
  if [ "$PARSER" = "yq" ]; then
    j=0
    while [ $j -lt $pre_cmds_count ] && [ "$pre_cmds_count" != "0" ] && [ "$pre_cmds_count" != "null" ]; do
      pcmd=$(yq -r ".tools[$i].build.pre_cmds[$j]" "$REPOS_FILE")
      [ "$pcmd" = "null" ] && j=$((j+1)) && continue
      echo "[install-tools]   pre: $pcmd"
      eval "$pcmd" || true
      j=$((j+1))
    done
    j=0
    while [ $j -lt $cmds_count ] && [ "$cmds_count" != "0" ] && [ "$cmds_count" != "null" ]; do
      cmd=$(yq -r ".tools[$i].build.cmds[$j]" "$REPOS_FILE")
      [ "$cmd" = "null" ] && j=$((j+1)) && continue
      echo "[install-tools]   run: $cmd"
      eval "$cmd" || echo "[install-tools]   FAILED: $cmd"
      j=$((j+1))
    done
  elif [ "$PARSER" = "pyyaml" ]; then
    python3 -c "
import yaml,os,subprocess
with open('$REPOS_FILE') as f:
    d=yaml.safe_load(f)
t=d['tools'][$i]
b=t.get('build') or {}
os.chdir('$dest')
for pcmd in b.get('pre_cmds') or []:
    print('[install-tools]   pre:',pcmd)
    subprocess.call(pcmd, shell=True)
for cmd in b.get('cmds') or []:
    print('[install-tools]   run:',cmd)
    r=subprocess.call(cmd, shell=True)
    if r!=0: print('[install-tools]   FAILED:',cmd)
" || true
  fi
  cd - >/dev/null

  if [ -n "$check_bin" ] && [ "$check_bin" != "null" ] && command -v "$check_bin" >/dev/null 2>&1; then
    echo "[install-tools] $name ready: $(command -v $check_bin)"
  else
    echo "[install-tools] $name build finished (check PATH /usr/local/bin)"
  fi

  i=$((i+1))
done

# Install osint workflow helper
if [ -f /scripts/osint-flow.sh ]; then
  ln -sf /scripts/osint-flow.sh /usr/local/bin/osint
  chmod +x /usr/local/bin/osint
  echo "[install-tools] Installed 'osint' helper"
fi

echo "[install-tools] Done. Dropping to shell."
exec "$@"
