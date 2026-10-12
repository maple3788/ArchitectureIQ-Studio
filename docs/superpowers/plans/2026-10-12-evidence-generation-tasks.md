# Evidence, live generation, and Task cards

**Goal:** Read full canonical questions from observed evidence and live generation, and organize one-question solving into durable Task cards.

**Design:** Existing read-only observer continues to expose real persisted state. Question bodies are read on demand from a private allowlisted artifact root and cached separately from SSE captures. Task cards reuse public question inputs, existing RAG model execution, and canonical rule prediction. No source experiment changes, model calls, or training are performed locally.

## Contracts and implementation

- [x] Observer backend: add private optional `artifact_root`; `GET /kb-loop/questions/{id}` returns Catalog-compatible public question detail, persisted before delivery. Cache is independent of captures. Browser supplies only question ID; source build records locate artifacts. Refuse links, traversal, mismatched IDs, oversized or incomplete files; never expose GT, raw errors, or paths. Round details add `generation:{total,completed,ok,failed,pending,items:[{item_id,family,question_type,budget,purpose,targets,status,seconds?,question_id?}]}`. Completion comes only from build records; unfinished rows say pending.
- [x] Observer UI: shared full-question reader opens from evidence and completed generation rows. Build node opens a wider live panel listing generated/pending/failed items, with automatic refresh on persisted sequence. Preserve selected question across updates, readable empty/unavailable/disconnected states, source aliases distinct from question letters.
- [x] Task backend: independent CAS-protected card store with name, single question, llm/rules mode, model and auto/manual KB selection. Endpoints list/create/update/detail, frozen preview, idempotent run and card history. LLM path preserves existing guards and RAG admission. Rules path uses public `_case` and `predict_question`, never GT or held-out evaluation accounting. Auto mode checks usable rule KBs; relevant conflicts or conflicting answers abstain. Receipts freeze question and KB identity; editing cards cannot alter receipts. External observed claims are not silently promoted into the KB catalog.
- [x] Task UI: card grid and one create entry, focused task workspace with readable question, mode, model where applicable, KB selection, frozen preview and history. Task remains at `#rag` for compatibility; previous evaluations remain accessible. No fake default tasks, statuses, answers or model streams.
- [x] Verification: mocked backend safety/CAS/preview/idempotency/conflict tests; frontend reader/live refresh/card persistence/mode and stale-preview tests; full frontend suite/build; targeted backend suite; read-only remote smoke and responsive browser checks.

## Review focus

Missing or partial source artifacts must not be replaced with reconstructed question text. Completed generation records can be visible before score records exist. Task edits and source changes invalidate previews. KB conflicts are visible instead of arbitrary tie-breaking. Stale source connections retain last facts and do not invent running states.

## Release

Update the local UI while preserving workflow draft and history, then sync public source to GitHub. Private configuration and runtime state stay local.
