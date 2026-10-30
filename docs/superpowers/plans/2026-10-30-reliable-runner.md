# Reliable case runner implementation plan

**Goal:** Replace duplicated shell execution with one recoverable Python workflow while retaining the interactive CLI and read-only dashboard.

**Approved design:** The architecture proposed in the project review: one runner, tool adapters, durable scan states, independent parsing, explicit follow-up searches, JSON cases with one writer, pinned and isolated tools. Implement in the current checkout on `codex/reliable-case-runner`, based on `codex/multi-input-cases`.

**Stack:** Python standard library, existing HTML/JS dashboard, Kali Docker image. No new services or database. Raw investigation files stay out of Git.

## Tasks

- [x] Add focused runner tests using local fake commands: persisted running state, timeout with partial output, parser failure, resume without repeats, new rerun attempts, interrupted recovery, case locking, safe arguments and validated inputs. Run these before implementation.
- [x] Add `scripts/adapters/` with a fixed registry, per-tool argument builders and parsers; use pinned Maigret JSON reports when supported and retain text evidence. Extract existing text parsing into shared evidence helpers. Keep legacy `add_scan` for evidence ingestion tests.
- [x] Extend `case_store.py` with a lock, input validation, independent idempotent parsing and pivot exports. A scan's execution status is saved before parser execution; failed parsing leaves earlier observations intact. JSON and report publication use atomic replacement.
- [x] Replace `case_runner.py` with sequential planning/execution/resume. Persist every planned task before launching, use process groups and a whole-process deadline, record command/version/settings/times, preserve attempts, handle SIGINT/SIGTERM and stale running states. Recovery verifies process identity before stopping leftovers from a killed runner.
- [x] Add `osint_cli.py` for existing menus and `--case`, plus `--resume`, `--rerun`, `--reparse`, `--batch`, `--timeout`. Reduce `osint-flow.sh` to a launcher. All paths call the same engine; discovery never automatically schedules scans. Preserve target files and pivot lists.
- [x] Update dashboard scan details and progress for running, failed, interrupted, timeout and parse failure states. Keep GET-only API and evidence allowlisting. Add focused dashboard checks.
- [x] Pin tool commits, install Python tools into individual virtual environments, record installed revisions and dependency versions in an image manifest, and validate each environment. Update Dockerfile, image smoke checks, README and AGENTS guidance. Build a separate PR image tag without recreating running services.
- [x] Run only affected local checks, shell/Python/JS syntax checks and the production image build/smoke check. Add Linux CI for full checks. Review fixes cover process-group cleanup, unfinished parsing recovery, legacy writer locking, path validation, and atomic report publication.
- [ ] Commit, push and open a PR against `codex/multi-input-cases` (PR #1).

## Acceptance checks

1. Both interactive and JSON intake paths launch identical tool commands.
2. A timeout or missing executable does not prevent other tools completing.
3. Killing/restarting a runner preserves original raw evidence and allows resumption.
4. Reparse never launches a tool and never duplicates observations.
5. Concurrent writers are rejected; dashboard readers continue using atomic snapshots.
6. Unverified leads and user-supplied relationships remain distinct.
7. Fixture-only tests do not contact external OSINT services.
