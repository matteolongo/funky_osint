# osint_me

A minimal Kali Linux Docker setup for OSINT investigations with automatic installation of common phone number & social account enumeration tools, plus a smart pivoting workflow.

## Structure

```
osint_me/
├── Dockerfile          # Cached base dependencies and tool installation
├── docker-compose.yml  # Image build and workspace mount
├── repos.yml           # List of repos to clone/build into the image
├── dashboard/          # Read-only case dashboard and API
├── scripts/
│   ├── install-tools.sh # Build-time installer (reads repos.yml and builds tools)
│   ├── case_store.py    # Structured case data and evidence links
│   └── osint-flow.sh    # Smart pivoting workflow (phone -> username -> email etc.)
└── workspace/          # Investigation outputs (mounted to /workspace in container)
```

Tool checkouts are stored in the image at `/tools`. Investigation results are kept separately in the host workspace.

## Installed Tools (via repos.yml)

| Tool | Purpose | Binary |
|---|---|---|
| [phoneinfoga](https://github.com/sundowndev/phoneinfoga) | Phone number intelligence (carrier, line type, scanners) | `phoneinfoga` |
| [sherlock](https://github.com/sherlock-project/sherlock) | Username enumeration across 400+ sites | `sherlock` |
| [maigret](https://github.com/soxoj/maigret) | Deep username profiling across 5900+ sites with recursive search | `maigret` |
| [holehe](https://github.com/megadose/holehe) | Email -> sites it's registered on | `holehe` |
| [ignorant](https://github.com/megadose/ignorant) | Phone number -> social accounts/platform registrations | `ignorant` |

## Quick Start

### 1) Start the container
From the repo root (`C:\Users\Usuario\tools\osint_me\`):

```bash
docker compose up -d --build
```

Open the local dashboard at [http://localhost:8765](http://localhost:8765). It reads the workspace through a read-only mount and refreshes as investigations run. Only cases created by the current workflow appear; older cases do not contain the structured case data.

The first build installs the base dependencies, clones the configured repositories, and builds the tools. It can take several minutes and requires network access. Docker caches the dependency and tool layers for subsequent builds. Starting an already-built image does not reinstall tools.

### 2) Enter the container

```bash
docker exec -it osint_me_kali bash
```

### 3) Run the smart workflow

With no arguments, it'll ask you what you have to start with:

```bash
osint
```

Alternatively, run a one-off investigation directly from the host with `docker compose run --rm kali osint`. The workspace mount keeps the results after that container exits.

To start directly with a username, use `docker compose run --rm kali osint username`. The dashboard container has read-only workspace access; run investigations in the Kali service rather than inside the dashboard container.

Or run the script directly:

```bash
/scripts/osint-flow.sh
```

## Usage Examples

### Start from a phone number
1. `osint` → choose `1) Phone number`
2. Enter e.g. `+1234567890`
3. Runs `phoneinfoga`, then asks for the country calling code to run `ignorant`
4. Discovered usernames/emails appear in the pivot menu - pick any to run `maigret`/`sherlock` or `holehe` on them
5. Keep pivoting as the tool discovers more identifiers

### Start from a username
1. `osint` → `2) Username` → enter username
2. Runs `maigret` (comprehensive) then `sherlock` for extra coverage
3. Extracts emails/usernames from results and offers to pivot

### Start from an email
1. `osint` → `3) Email` → enter email
2. Runs `holehe` to find registrations/identifiers
3. Pivot to discovered usernames

### Load existing pivots
`osint` → `4) Load pivots from file` and provide a file with one identifier per line (phone, email, or username). Lines starting with `#` are ignored.

Imported phone numbers can be selected from the pivot menu. Extracted identifiers are pattern matches and should be verified before treating them as linked accounts.

## Outputs

All results are saved under a uniquely named `/workspace/osint-YYYYMMDD_HHMMSS-.../` directory with:
- `case.json`, which records identifiers, scans, reported accounts, and evidence links
- A separate raw output file for each scan
- Pivot lists (`pivot_usernames.txt`, `pivot_emails.txt`)
- Target files for each starting point

The dashboard links an identifier to each search, and a search to accounts explicitly reported by Sherlock or Maigret and to identifiers mentioned in its output. Maigret's recursive searches retain their searched identifier and are hidden by default; select **Include recursive searches** to explore them. Account details and image URLs are shown with their source scan. Profile images load directly from the reported site and may expire or be unavailable. Holehe scan details distinguish reported results, negative results, rate limits, and errors. These links are leads, not proof that identifiers belong to the same person. Select a scan to inspect the underlying output. Output formats from the tools vary, so some results may only appear in the raw output. The workspace is mounted on the host, so results persist after the container stops.

## Extending and testing

Add installation details to `repos.yml` to install another tool. To use it in the interactive workflow, also add its invocation and any output extraction to `scripts/osint-flow.sh`; installation alone does not add a menu action. Keep tool failures isolated so other searches can continue.

Run the focused workflow checks with `bash tests/osint-flow-test.sh` and the dashboard checks with `python3 tests/test_dashboard.py`; check shell syntax with `bash -n scripts/*.sh tests/*.sh`. After building, run `bash tests/image-smoke-test.sh` to check the image's tools and workflow without querying external services. Set `WORKSPACE` to change where the workflow writes cases (the default is `/workspace`).

## Tips

- Tools may hit rate limits depending on the sites queried. If that happens, slow down or use VPN/rotation as appropriate for your use case.
- `maigret` can take a while with `-a` (all sites). The workflow uses reasonable timeouts by default.
- If a tool isn't installed (or build failed), the workflow will just skip it gracefully.
- After editing `repos.yml` or the scripts, rebuild and recreate the container with `docker compose up -d --build`.
- Configured branches and the Kali base image can change upstream; rebuilding without cache fetches current versions.

## Troubleshooting

**Rebuild tools after changing `repos.yml`:**
```bash
docker compose up -d --build
```
To fetch fresh upstream versions even when Docker has cached layers, use `docker compose build --pull --no-cache`, then `docker compose up -d`.

**Check installed tools:**
```bash
which phoneinfoga maigret sherlock holehe ignorant osint
```

**View build output:**
```bash
docker compose --progress plain build
```
