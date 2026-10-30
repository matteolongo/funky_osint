# Repository guidance

- This repository wraps third-party OSINT tools in a Kali image. The project-owned code is in `scripts/`; external checkouts are stored in the image, and `workspace/` contains investigation data. Avoid committing investigation data as part of wrapper changes.
- `repos.yml` controls pinned installation; runtime tools are registered in `scripts/adapters/`. Update the adapter registry, representative output tests and README when integrating a tool. Both interactive and batch searches use `scripts/case_runner.py`; keep tool logic out of the shell launcher and CLI menus.
- Preserve execution records before parsing, retain each attempt's raw evidence, and use the case writer lock for mutations. Newly discovered leads must not automatically schedule more searches. Resume must skip completed attempts unless rerun is explicitly requested.
- The dashboard reads new `case.json` files and the associated raw scan output from a read-only workspace mount. Preserve evidence and label extracted matches as leads rather than asserting identity relationships.
- Preserve the existing interactive workflow and output files unless a change explicitly requires otherwise. Treat extracted identifiers as unverified leads and handle unavailable or failing tools without losing results from other tools.
- Run only tests affected by a change locally, never the entire backend or frontend test suite. Run relevant static checks and production builds when applicable. The workflow checks are `bash tests/osint-flow-test.sh`, dashboard checks are `python3 tests/test_dashboard.py`, and shell syntax can be checked with `bash -n scripts/*.sh tests/*.sh`.
- Follow `C:\Users\Usuario\.codex\RTK.md` when available; prefix shell commands with `rtk` as instructed there.
- Runner and CLI checks are `tests/test_runner.py` and `tests/test_cli.py`; Linux process cleanup checks are `tests/test_runner_signals.py`. Run affected files or named tests only; CI runs full discovery.
