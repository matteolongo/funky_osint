# Multi-input case implementation plan

**Goal:** Run existing tools against supplied case inputs and present evidence-backed cross-input leads.

**Architecture:** Validate a JSON intake before recording people, inputs and supplied relationships. Run supported searches independently, preserve their raw output, and expose exact matches as leads in the dashboard. Keep the existing interactive workflow and pivot review.

**Tech stack:** Bash, Python standard library, browser JavaScript.

## Tasks

- [ ] Add tests for intake validation, person attribution, isolated failures and evidence-backed exact matches.
- [ ] Implement the case runner using existing case storage and tools, then connect it to the shell entry point.
- [ ] Display people, supplied relationships and cross-input leads in the dashboard, including evidence links.
- [ ] Document the intake and run affected tests and static checks.
