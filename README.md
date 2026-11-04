# osint_me

A local OSINT case workspace: a Python runner coordinates independent tools, preserves their evidence, and exposes accounts and possible relationships in a read-only dashboard. An interactive CLI and JSON case intake use the same execution engine.

## Structure

```
osint_me/
├── Dockerfile          # Cached base dependencies and tool installation
├── docker-compose.yml  # Image build and workspace mount
├── repos.yml           # List of repos to clone/build into the image
├── dashboard/          # Read-only case dashboard and API
├── scripts/
│   ├── install_tools.py # Pinned builds and isolated Python environments
│   ├── adapters/        # Tool commands and output parsers
│   ├── case_runner.py  # Scheduling, deadlines, attempts and recovery
│   ├── case_store.py   # Case persistence, parsing and writer lock
│   ├── evidence.py     # Shared evidence extraction helpers
│   ├── osint_cli.py    # Interactive menus and batch commands
│   └── osint-flow.sh   # Compatibility launcher for the Python CLI
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
2. Runs `maigret` without automatic recursion, then `sherlock` for extra coverage
3. Extracts emails/usernames from results and offers to pivot

### Start from an email
1. `osint` → `3) Email` → enter email
2. Runs `holehe` to find registrations/identifiers
3. Pivot to discovered usernames

### Load existing pivots
`osint` → `4) Load pivots from file` and provide a file with one identifier per line (phone, email, or username). Lines starting with `#` are ignored.

Imported phone numbers can be selected from the pivot menu. Extracted identifiers are pattern matches and should be verified before treating them as linked accounts.

### Batch, resume, rerun and reparse

Run without interactive prompts:

```bash
docker compose run --rm kali osint example_username --batch --timeout 300
docker compose run --rm kali osint --case /workspace/intake.json --batch
```

The timeout is a deadline for each whole tool process, including its network requests (default: 300 seconds). Tools run sequentially. Missing tools, failures and timeouts are recorded and do not stop other searches. Output is saved even when a tool fails; findings from an incomplete attempt are labelled accordingly in the dashboard. Maigret's per-request timeout is separately set to 10 seconds.

Resume a case using its directory printed by the CLI:

```bash
docker compose run --rm kali osint --resume /workspace/osint-YYYYMMDD_HHMMSS-example --batch
```

Resume runs pending tasks and creates new attempts for unsuccessful tasks. Completed tasks are skipped; it does not search newly discovered leads. Add `--rerun` to explicitly repeat completed tasks too. Each attempt retains its own raw output, reports, settings, timestamps and tool revision. `--timeout` on resume changes the deadline for pending/new attempts; historical records stay unchanged. Cases created before the resumable runner can still be viewed and reparsed but have no saved execution plan to resume.

To apply a parser fix to existing evidence without making network requests:

```bash
docker compose run --rm kali osint --reparse /workspace/osint-YYYYMMDD_HHMMSS-example
```

Parsing and execution have separate statuses. A parsing error leaves the original evidence and previously extracted results intact. Reparse replaces that attempt's observations instead of duplicating them. Only one writer can modify a case at a time; the dashboard continues reading atomic JSON snapshots. Ctrl+C and container termination stop the active process group and save the interruption; a stale running scan is marked interrupted when the case is resumed.

### Start with a multi-person case

Put a JSON file in the host `workspace/` directory, for example `workspace/intake.json`:

```json
{
  "people": [
    {"name": "Ana", "inputs": [
      {"type": "phone", "value": "+34123456789", "country_code": "+34", "source": "user supplied"},
      {"type": "profile", "value": "https://www.instagram.com/example/", "notes": "Known profile"},
      {"type": "username", "value": "example"}
    ]},
    {"name": "Carlos", "inputs": [
      {"type": "phone", "value": "+34987654321", "country_code": "+34"}
    ]}
  ],
  "relationships": [{"from": 0, "to": 1, "label": "partner"}]
}
```

Run `docker compose run --rm kali osint --case /workspace/intake.json`. Input types are `phone`, `email`, `username`, and `profile`. Phone numbers use `+` and digits; `country_code` is optional and enables the Ignorant search. Profile URLs are saved for comparison, not automatically searched as usernames: add an explicit `username` input if you want that search. Names are context, not search queries. Each input can include `source` and `notes`; relationship indexes refer to positions in the `people` list, starting at zero.

The run searches the supplied phone numbers, emails and usernames with the available tools, records missing or failed tools, and then opens the existing pivot menu for manual follow-up. It does not automatically search newly extracted leads. In the dashboard, supplied people and relationships are distinguished from possible matches: exact supplied identifiers mentioned in scan output and exact profile URL matches link back to the evidence. These are leads, not identity verification. The intake file contains personal information; keep it in the workspace and do not commit it.

## Outputs

All results are saved under a uniquely named `/workspace/osint-YYYYMMDD_HHMMSS-.../` directory with:
- `case.json`, which records identifiers, scans, reported accounts, and evidence links
- A separate raw output file for each scan
- Structured reports where available (Maigret JSON), exposed as evidence in the dashboard
- `artifacts/<scan-id>/` for each attempt's additional tool-generated files
- Pivot lists (`pivot_usernames.txt`, `pivot_emails.txt`)
- Target files for each starting point

The dashboard links an identifier to each search, and a search to accounts explicitly reported by Sherlock or Maigret and to identifiers mentioned in its output. Maigret's recursive searches retain their searched identifier and are hidden by default; select **Include recursive searches** to explore them. Account details and image URLs are shown with their source scan. Profile images load directly from the reported site and may expire or be unavailable. Holehe scan details distinguish reported results, negative results, rate limits, and errors. These links are leads, not proof that identifiers belong to the same person. Select a scan to inspect the underlying output. Output formats from the tools vary, so some results may only appear in the raw output. The workspace is mounted on the host, so results persist after the container stops.

## Extending and testing

Add installation details with a full commit SHA to `repos.yml`, then add a module in `scripts/adapters/` and register it in `scripts/adapters/__init__.py`. Each adapter declares its input kind, builds an argument list and parses its output. Returning `None` from its argument builder means the supplied input lacks required information. Use `python_env: true` for Python tools. Both interactive and batch workflows automatically use registered adapters for the selected input kind; the shell launcher contains no tool-specific logic.

Use structured output when the pinned tool supports it, and include a representative synthetic fixture test. Maigret prefers its simple JSON report, with text parsing retained for interrupted runs and older evidence. Increment the adapter's parser version when changing its interpretation of output. Profiles, extracted identifiers and pictures remain source-backed leads; finding the same username does not prove identity.

Run only the tests affected by a local change. Runner checks are in `tests/test_runner.py`, CLI checks in `tests/test_cli.py`, and Linux cancellation checks in `tests/test_runner_signals.py`. Existing workflow checks are `bash tests/osint-flow-test.sh`; select affected methods from `tests/test_dashboard.py` and `tests/test_case_intake.py`. Check shell syntax with `bash -n scripts/*.sh tests/*.sh`. CI runs the full suite. After building, run `bash tests/image-smoke-test.sh IMAGE_TAG` to check the image's tools and workflow without querying external services. Set `WORKSPACE` to change where the workflow writes cases (the default is `/workspace`).

Each Python tool has an independent environment under `/opt/tools/<name>`. The installer checks each environment's dependencies and writes source revisions and resolved package versions to `/tools/versions.json`. Tool revisions are pinned; OS packages and transitive Python dependencies are resolved at build time, so an uncached rebuild is not guaranteed to be byte-identical. Application-only edits reuse the dependency and tool installation layers.

## Tips

- Tools may hit rate limits depending on the sites queried. If that happens, slow down or use VPN/rotation as appropriate for your use case.
- `maigret` can take a while with `-a` (all sites). The workflow uses reasonable timeouts by default.
- If a tool isn't installed (or build failed), the workflow will just skip it gracefully.
- After editing `repos.yml` or the scripts, rebuild and recreate the container with `docker compose up -d --build`.
- Update the pinned commit in `repos.yml` deliberately when upgrading a tool, then validate its adapter fixtures and rebuild.

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
