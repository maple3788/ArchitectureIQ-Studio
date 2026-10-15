# ArchitectureIQ Studio

This is the independently extracted Studio project. Work only in this repository for implementation and tests. The source worktree is a migration backup, not a runtime dependency.

- Verify `git rev-parse --show-toplevel` before editing/testing.
- Verify Python import provenance with the exact test interpreter; `architecture_iq.__file__` must be under this repository's `src/architecture_iq`.
- Real LLM calls and generated-code GT experiments run only on the authorized Linux execution server, whose connection details belong in private deployment configuration. `ARCHITECTURE_IQ_KB_EXECUTION_HOST` must match the nonempty private `ARCHITECTURE_IQ_KB_AUTHORIZED_HOST`. Local UI/build and mocked unit tests are allowed.
- GT remains spec → generated code → execution → stored results. Reuse the bundled canonical engine; never implement parallel training logic.
- Do not disclose GT to Solver before answer commitment. Repeated questions are research practice, not independent evaluation.
- Preserve existing scientific/paired methods, drafts, sealed receipts, and historical runs. Never rewrite frozen hashes to resume old runs under new source.
- New KB evolution runs must use the prepared consistency-gated runtime described in `docs/kb-consistency-runtime.md`. New, revised, and split claims require a passing version-bound text/rule audit with frozen DSL and budget context before registration; do not resume historical runs with patched source.
- Real status and text come from persisted backend events/SSE. Never simulate model output in the production workflow.
- Runtime state, source datasets, secrets, model weights, and build/dependency caches must not be committed.
- Provenance of imported source lives in `migration/source-manifest.json`. Studio owns `src/architecture_iq/studio`, `src/architecture_iq/kb`, `services/kb_workflow_api`, `frontend/workflow`; other `architecture_iq` modules are the bundled benchmark engine snapshot.
