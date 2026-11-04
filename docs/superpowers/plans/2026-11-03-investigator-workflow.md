# Investigator Workflow Implementation Plan

Status: implemented in four stacked PRs: [evidence cards #4](https://github.com/matteolongo/funky_osint/pull/4), [LLM triage #5](https://github.com/matteolongo/funky_osint/pull/5), [candidate clusters #6](https://github.com/matteolongo/funky_osint/pull/6), and [offline report #7](https://github.com/matteolongo/funky_osint/pull/7). All four CI test jobs passed on the implementation commits. Image validation runs in CI; see each PR for its current result. No PR was merged.

Execution decisions: reuse the current checkout on feature branches; perform all test execution in CI, overriding older skill/repository test instructions. Candidate clusters initially represent explicit pairwise hypotheses, which may overlap; they never merge person records transitively. Complete all four deliverables in this implementation session.

Review decision: candidate generation selects at most 2,000 pairs and explicitly reports limited coverage if more exist. Every selected pair must complete; omitted comparisons remain unknown. This avoids a permanently blocked case that has no supported narrowing command. New parsed evidence invalidates old clusters in the same atomic save.

**Goal:** Turn collected OSINT results into traceable, reviewable leads and candidate groups before the next already-planned tool executes.

**Architecture:** Retain the shared runner, adapters, case JSON and read-only dashboard. Save raw evidence first, parse it deterministically, then persist a separate LLM assessment. Extend the existing gate instead of introducing an autonomous agent or a second orchestrator.

**Tech stack:** Existing Python standard library, OpenAI Responses API, vanilla JavaScript dashboard and Docker image. No new service or database for this iteration.

**Basis:** User request of 3 November 2026; inspected `case_runner.py`, `llm_review.py`, `case_store.py`, `evidence.py`, adapters, CLI, dashboard and CI. PRs #1, #2 and #3 are still open; #2 and #3 have successful test and image checks. New work depends on that stack, particularly #3.

## Current assessment

- The runner already saves attempts, supports resume and invokes an opt-in LLM gate between tools.
- The LLM produces summary/findings/continue-or-pause, not per-result triage or cross-scan candidate groups.
- Prior context contains scan metadata, rather than the profile evidence required to compare findings across tools.
- Context truncation limits lists to 30 entries. A verdict cannot imply that omitted findings were examined.
- Account observations retain scan provenance, but extracted identifier mentions link to the scan rather than the precise account/field that mentioned them.
- Exact account URL equality removes some duplication. It does not establish common ownership across profiles.
- The dashboard already has graph/list views, profile fields and reported image URLs. Extend these rather than replace them.

## Constraints shared by every PR

- Raw output and tool observations remain intact. Filtering changes presentation and recommendations, never evidence storage.
- Separate supplied assertions, tool observations, model assessments and explicit user decisions.
- Preserve the existing fail-closed review gate on resume. Manual approval of a pause is not approval of a cluster or an identity claim.
- Newly extracted identifiers and model suggestions never schedule searches automatically. Existing tools consume validated identifiers, not model prose.
- Treat profile text as untrusted input. Model output must use validated IDs and schema; never accept commands or arbitrary new targets.
- Reparse remains offline. Changed inputs invalidate derived assessments without deleting historical reviews.
- Preserve the case writer lock, atomic saves, runtime-only keys and read-only dashboard.
- No local test execution. Add focused synthetic tests and execute them in CI. Local work may run relevant static checks and production builds. Align the contradictory older local-test wording in AGENTS.md with this latest instruction when implementation starts.

## PR 1 — Traceable evidence cards

**Deliverable:** Each extracted lead shows exactly which account field or output location produced it, with a link to the original evidence.

**Files:** `scripts/evidence.py`, `scripts/case_store.py`, affected adapters, `dashboard/static/app.js`, representative fixtures in `tests/test_dashboard.py` and `tests/test_case_intake.py`, README.

- [x] Add stable evidence references to observations/mentions: source scan, raw filename, field path or line span, original value and artifact hash. Keep offsets relative to the saved artifact; do not invent source locations.
- [x] Preserve the originating account when extracting an email/username from a profile field. Distinguish profile evidence from general scan output.
- [x] Add a conservative comparison key while retaining original values: lowercase URL hostname and email domain; preserve email local part, URL path and platform-dependent username case. Do not infer missing phone country codes or strip meaningful query parameters.
- [x] Display evidence cards through the existing detail panel. Include scan collection time, tool, source field and raw-evidence link.
- [x] Cover equivalent host casing, distinct profile paths, source association and stable references across an unchanged offline reparse in CI.

**Acceptance example:** An email extracted from a profile biography opens that biography's source account and scan. Two tools reporting the same profile retain both observations; this is not represented as two independent identity confirmations.

## PR 2 — LLM triage after every scan

**Depends on:** PR 1.

**Deliverable:** A result list filterable by `relevant`, `uncertain`, `likely_noise` and `unreviewed`, with reasons and citations.

**Files:** `scripts/llm_review.py`, `scripts/case_runner.py`, `dashboard/static/app.js`, `tests/test_llm_review.py`, README and `.env.example` if budget configuration is added.

- [x] Extend the existing structured review with per-evidence classifications: evidence reference, label, short rationale and supporting references. Relevance means relevance to supplied case inputs; it is not an identity probability.
- [x] Batch normalized findings in deterministic order within the context limit. Persist completed batches and resume only missing/failed batches. Show reviewed/total counts and mark every omitted item unreviewed.
- [x] Apply an explicit configurable per-step request cap. Reaching it pauses the gate with pending coverage visible; it must not silently approve the next scan. Persist usage already returned by the provider.
- [x] Validate exactly which input IDs each classification covers. Invalid references or missing coverage prevent a completed assessment. Keep existing pause/error handling and schema-version invalidation.
- [x] Add dashboard filters and a visible count of filtered results. Keep all results available; do not delete likely noise or change existing all-leads exports.
- [x] In CI cover 100-result input, duplicate/missing IDs, interrupted batch resume, request cap, malicious instructions embedded in biographies, API failures and stale evidence.

**Acceptance example:** A tool returns 100 profiles. All 100 are classified or explicitly counted as pending; the next tool cannot start on the basis of a silently truncated review. An unrelated same-name profile remains inspectable with the model's reason for downranking it.

## PR 3 — Candidate clusters across scans

**Depends on:** PR 2.

**Deliverable:** Expandable candidate groups in the dashboard, with supporting and conflicting evidence and an unassigned group.

**Files:** new `scripts/analysis.py` for candidate generation and cluster validation; `scripts/llm_review.py`, `scripts/case_runner.py`, `dashboard/static/app.js`, `dashboard/static/style.css`, new `tests/test_analysis.py`, `tests/test_llm_review.py`, README.

- [x] Generate a bounded set of comparison candidates from exact reported links, shared identifiers and matching profile fields. Common usernames/names alone are weak signals and never automatic merges.
- [x] Pass relevant prior evidence plus new observations to the LLM. Ask for proposed group membership, supporting references, contradicting references and a short rationale. Reuse batching and request limits from PR 2.
- [x] Store candidate groups as a versioned derived case assessment referencing a frozen input manifest. Do not rewrite accounts or person ownership. Later scans may create a new cluster revision without invalidating unchanged earlier per-scan triage.
- [x] Validate member IDs, cited evidence and relationship types. A missing profile field is not a contradiction. Conflicting location alone is not proof of separate people. Repeated reports of one source do not multiply independent support.
- [x] Show cluster cards, expand-to-members navigation and possible-link graph edges visually distinct from observed links. Keep ambiguous items unassigned or explicitly ambiguous; do not imply calibrated confidence percentages.
- [x] In CI cover unrelated reused usernames, explicit cross-profile links, shared organizational email, contradictory observations, duplicate reports, stale clusters and repeatable resume.

**Acceptance example:** Two profiles explicitly link to the same personal site and one links to the other. They appear in a suggested group with those links cited. A third profile sharing only the handle stays separate/uncertain. No new search starts.

## PR 4 — Exportable investigation brief

**Depends on:** PR 3; stretch deliverable if the first three consume today's capacity.

**Deliverable:** One offline HTML report that can be opened and printed from a browser.

**Files:** new `scripts/report.py`, `scripts/osint_cli.py`, new `tests/test_report.py`, README. Reuse existing case data and review text; no additional model call.

- [x] Add proposed CLI command `osint --report CASE_DIRECTORY` to generate a timestamped report inside that case under the writer lock, without running tools or contacting OpenAI.
- [x] Include supplied inputs, tool execution coverage, reviewed/unreviewed counts, candidate groups, conflicting evidence, source references and suggested manual checks.
- [x] Separate observations and model hypotheses in the report. Include generation time, reviewed artifact hashes and a manifest describing the snapshot. Hashes detect changed artifacts; they do not prove that a source claim is true.
- [x] Escape all untrusted content; use local evidence links and no automatically loaded remote images. Include a print stylesheet.
- [x] In CI cover HTML/script injection, missing artifacts, partially reviewed cases and generation with network/API unavailable.

**Acceptance example:** Another analyst can read the brief, distinguish observations from hypotheses, see what remains unchecked and trace each reported connection back to its source.

## Today's order and definition of done

Build PRs 1 → 2 → 3 as the core delivery. PR 4 is the first stretch item. Scope estimates are roughly one focused day for the first three, subject to parser edge cases and review/CI turnaround; do not compress source traceability or failure handling to meet the estimate.

Each PR includes its feature, minimal UI where needed, representative synthetic fixtures, documentation, relevant static checks and a green CI run before merging. No live investigations or private case uploads are needed for validation. Use the existing dependency stack or merge it in order before basing new PRs on master; do not merge existing PRs merely as part of this planning request.

Deferred: additional collectors, autonomous pivots, broad web crawling, facial identification, vector databases and a replacement frontend. The current bottleneck is interpretable evidence and result quality.

Methodological reference: the [Berkeley Protocol project](https://humanrights.berkeley.edu/projects/developing-the-berkeley-protocol-on-digital-open-source-investigations/) separates collection, preservation, verification and analysis. This roadmap adopts that separation; it does not claim legal compliance or evidentiary certification.
