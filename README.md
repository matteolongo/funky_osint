# osint_me

A minimal Kali Linux Docker setup for OSINT investigations with automatic installation of common phone number & social account enumeration tools, plus a smart pivoting workflow.

## Structure

```
osint_me/
├── docker-compose.yml  # Container config (mounts scripts/repos.yml, runs installer)
├── repos.yml           # List of repos to clone/build on container startup
├── scripts/
│   ├── install-tools.sh # Auto-installer (reads repos.yml, builds tools, installs osint)
│   └── osint-flow.sh    # Smart pivoting workflow (phone -> username -> email etc.)
├── tools/              # Cloned tools live here (mounted to /tools in container)
└── workspace/          # Investigation outputs (mounted to /workspace in container)
```

## Installed Tools (via repos.yml)

| Tool | Purpose | Binary |
|---|---|---|
| [phoneinfoga](https://github.com/sundowndev/phoneinfoga) | Phone number intelligence (carrier, line type, scanners) | `phoneinfoga` |
| [sherlock](https://github.com/sherlock-project/sherlock) | Username enumeration across 400+ sites | `sherlock` |
| [maigret](https://github.com/soxoj/maigret) | Deep username profiling across 5900+ sites with recursive search | `maigret` |
| [holehe](https://github.com/megadose/holehe) | Email -> sites it's registered on | `holehe` |
| [ignorant](https://github.com/megadose/ignorant) | Phone number -> social accounts/platform registrations | `ignorant` |
| [scylla](https://github.com/DoubleThreatSecurity/Scylla) | Username/email/phone OSINT aggregation | `scylla` |

## Quick Start

### 1) Build and start the container
From the repo root (`C:\Users\Usuario\tools\osint_me\`):

```bash
docker compose up -d --build
```

On first start, `install-tools.sh` will:
- Install minimal dependencies (git, python3, pip, golang, build tools as needed)
- Clone/update repos from `repos.yml`
- Build/install tools and put binaries in `/usr/local/bin`
- Install a launcher for the workflow script as `osint`

This can take several minutes on first run depending on network/speed.

### 2) Enter the container

```bash
docker exec -it osint_me_kali bash
```

### 3) Run the smart workflow

With no arguments, it'll ask you what you have to start with:

```bash
osint
```

Or run the script directly:

```bash
/scripts/osint-flow.sh
```

## Usage Examples

### Start from a phone number
1. `osint` → choose `1) Phone number`
2. Enter e.g. `+1234567890`
3. Runs `phoneinfoga` and `ignorant` automatically
4. Discovered usernames/emails appear in the pivot menu - pick any to run `maigret`/`sherlock` or `holehe`/`scylla` on them
5. Keep pivoting as the tool discovers more identifiers

### Start from a username
1. `osint` → `2) Username` → enter username
2. Runs `maigret` (comprehensive) then `sherlock` for extra coverage
3. Extracts emails/usernames from results and offers to pivot

### Start from an email
1. `osint` → `3) Email` → enter email
2. Runs `holehe` and `scylla` to find registrations/identifiers
3. Pivot to discovered usernames

### Load existing pivots
`osint` → `4) Load pivots from file` and provide a file with one identifier per line (phone, email, or username). Lines starting with `#` are ignored.

Imported phone numbers can be selected from the pivot menu. Extracted identifiers are pattern matches and should be verified before treating them as linked accounts.

## Outputs

All results are saved under `/workspace/osint-YYYYMMDD_HHMMSS/` with:
- Raw tool outputs (e.g. `maigret_scan.txt`, `ignorant_scan.txt`, `holehe_scan.txt`)
- Pivot lists (`pivot_usernames.txt`, `pivot_emails.txt`)
- Target files for each starting point

Repeating a scan for the same identifier can overwrite its existing output in the current case. The workspace is mounted on the host, so results persist after the container stops.

## Extending and testing

Add installation details to `repos.yml` to install another tool. To use it in the interactive workflow, also add its invocation and any output extraction to `scripts/osint-flow.sh`; installation alone does not add a menu action. Keep tool failures isolated so other searches can continue.

Run the focused workflow checks with `bash tests/osint-flow-test.sh` and check shell syntax with `bash -n scripts/*.sh tests/*.sh`. The checks use temporary files and a fake failing Maigret command; they do not query external services. Set `WORKSPACE` to change where the workflow writes cases (the default is `/workspace`).

## Tips

- Tools may hit rate limits depending on the sites queried. If that happens, slow down or use VPN/rotation as appropriate for your use case.
- `maigret` can take a while with `-a` (all sites). The workflow uses reasonable timeouts by default.
- If a tool isn't installed (or build failed), the workflow will just skip it gracefully.
- You can add/remove tools by editing `repos.yml` and restarting the container.

## Troubleshooting

**Rebuild tools after changing `repos.yml`:**
```bash
docker compose down
docker compose up -d
```
The installer will skip tools that already have their `check_bin` in PATH.

**Check installed tools:**
```bash
which phoneinfoga maigret sherlock holehe ignorant scylla osint
```

**View installer logs:**
```bash
docker compose logs -f
```
