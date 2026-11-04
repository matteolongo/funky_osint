# OpenAI step review

Approved behavior: review saved results after every tool execution, before the next tool starts. OpenAI API is the selected provider. A failed or paused review blocks continuation without losing evidence; resume retries missing/failed reviews without repeating completed searches.

- [x] Add focused synthetic HTTP and runner tests for continue/pause/error/refusal, resume caching, explicit human approval, changed evidence, bounded input, and secret isolation.
- [x] Add `scripts/llm_review.py`: fixed Responses API endpoint, strict JSON schema and independent validation, evidence-linked findings, persisted history, input fingerprint and prompt version. No tools or automated pivots. Use configurable model (default `gpt-5-mini`), `store: false`, bounded context and output, and one request per attempt.
- [x] Add the review gate to the shared runner, including recovered output. Persist opt-in policy per case and preserve it across CLI actions/resume. Keep parsing-only commands offline. Strip the OpenAI key from child-tool environments.
- [x] Add CLI activation and explicit, recorded approval of a model pause; errors cannot be silently bypassed. Display review state, summary, concerns, sources and suggested checks in the read-only dashboard.
- [x] Wire runtime environment configuration only to the runner service, ignore secret files in Git/build context, and document usage and data sent to OpenAI.
- [x] Run affected local checks, syntax checks and cached image build; review changes. Deliver as a separate PR based on the runner branch.

Response contract: `decision` (`continue` or `pause`), `summary`, `findings` (severity, description, evidence IDs), `suggested_checks` (text only). Preserve raw evidence and user-supplied relationships. Model output never becomes an identity assertion or executable instruction.

Sources: [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini).
