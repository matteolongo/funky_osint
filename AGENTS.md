# Repository guidance

- This repository wraps third-party OSINT tools in a Kali container. The project-owned code is in `scripts/`; `tools/` contains external checkouts and `workspace/` contains investigation data. Avoid editing or committing either directory as part of wrapper changes.
- `repos.yml` controls installation; adding a tool there does not automatically add it to the interactive workflow. Update `scripts/osint-flow.sh` and the README when integrating a tool into a search flow.
- Preserve the existing interactive workflow and output files unless a change explicitly requires otherwise. Treat extracted identifiers as unverified leads and handle unavailable or failing tools without losing results from other tools.
- Run only tests affected by a change locally, never the entire backend or frontend test suite. Run relevant static checks and production builds when applicable. The workflow regression checks are `bash tests/osint-flow-test.sh`; shell syntax can be checked with `bash -n scripts/*.sh tests/*.sh`.
- Follow `C:\Users\Usuario\.codex\RTK.md` when available; prefix shell commands with `rtk` as instructed there.
