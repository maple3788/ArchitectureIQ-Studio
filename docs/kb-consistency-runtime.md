# Future KB runtime consistency gate

`tools/kb_consistency_runtime.py` prepares a **new runtime source directory**. It does not deploy, start a loop, contact a model, generate questions, or change the existing monitored run. Studio now owns the complete runner in `tools/kb_loop`, its pairwise evaluator, canonical engine, profiles and templates. Use this repository as the source; no backup checkout or historical server runtime is required. See [the runner guide](kb-loop.md).

Preparation copies source directories (`src`, `profiles`, `tools`, `prompts`, `configs`), installs the current policy and adapter, and patches the checked entrypoint in the copied loop. Datasets, run directories, model weights, environment files, bytecode and dependency caches are excluded. The original files and receipts remain unchanged. Preparation refuses an existing destination or an unknown entrypoint. Review source configuration before choosing a destination because configuration files are copied with the runtime.

Use deployment paths and interpreter values from private configuration:

```sh
PYTHONPATH="$STUDIO_REPO/src:$STUDIO_REPO" "$PYTHON_BIN" \
  "$STUDIO_REPO/tools/kb_consistency_runtime.py" \
  --source-root "$STUDIO_REPO" --destination "$NEXT_RUNTIME"
```

`consistency-runtime.json` records original and installed source hashes. The copied entrypoint verifies installed hashes and Python import provenance on startup. It refuses changed source; prepare another directory for subsequent policy changes.

Only on the authorized Linux execution server, with nonempty matching private `ARCHITECTURE_IQ_KB_AUTHORIZED_HOST` and `ARCHITECTURE_IQ_KB_EXECUTION_HOST`, initialize a new run using the copied entrypoint:

```sh
PYTHONPATH="$NEXT_RUNTIME/src" "$PYTHON_BIN" "$NEXT_RUNTIME/tools/kb_loop/loop.py" init \
  --root "$NEXT_RUN" --config "$NEXT_CONFIG" --seed-claims "$SEED_CLAIMS"

PYTHONPATH="$NEXT_RUNTIME/src" "$PYTHON_BIN" "$NEXT_RUNTIME/tools/kb_loop/loop.py" round \
  --root "$NEXT_RUN" --pilot
```

These are launch instructions, not actions performed by preparation. `NEXT_RUN` must not exist before initialization. Its binding file identifies the prepared runtime. `round` and `run-forever` reject unbound historical runs, and the original run is never rebound to new source. Existing seed claims retain their historical role; the gate applies to newly proposed, revised, and split versions.

Generation and audit use the exact literal DSL from the frozen proposer, including derived field definitions such as `disp` and `eff_lr`; missing or dynamic DSL definitions fail closed. Its content is bound into the configuration hash. Generation uses actual `BUDGETS` and the frozen profile, including family training defaults and the canonical generator's valid batch sizes. Prompts require explicit budget and step constraints in every rule, applying to both candidates. Causal reasoning belongs in `explanation: {"text": "...", "status": "hypothesis"}`. The adapter preserves that field in version records and receipts.

Structured semantic review replaces the legacy boolean check. Reviews bind exact text, rules, explanation and configured scope. Before any registration writes, all new claims, splits and legacy revisions must pass the current policy. Failed requests, malformed responses, missing condition mappings and changed claims block registration. Reading cached proposals does not bypass review; cached preregistration receipts are checked too. A failed audit is saved in `proposals.json` for inspection, and no `DONE_register` marker is produced by the normal loop until registration succeeds.

Registration fails the entire batch if any draft fails; the error identifies the blocked draft and no new versions are written. The full audit is retained in each registered claim's `consistency` object, with `consistent: true` only after the registration gate passes and a concise `issue` field for existing observers. Explanation metadata is attached before version and preregistration receipt writes, so the new receipt hash covers the final record. Existing sealed receipts are never rewritten to add compatibility fields.

No independent training implementation is introduced: question generation and execution continue through the copied canonical engine. The adapter does not edit, automatically repair, or reclassify historical claims.

## Audit existing claims

`tools/audit_kb_consistency.py --runtime "$FROZEN_RUNTIME" --run "$RUN" --output "$PRIVATE_REPORT" --source-identity "$SOURCE_IDENTITY"` runs only on the authorized Linux server. It loads the current policy from the repository without changing the frozen runtime. For source-only deployments, copy this runner, `kb_consistency_runtime.py`, and `claim_consistency.py` together in a separate private audit directory. Model responses are cached there; repeating the same audit revalidates cached responses with the current deterministic checks. Reports bind source identity, claim version, text/rules/explanation hash, and frozen budget context. Studio reads the report as a private annotation beside its observer journal; it never rewrites sealed claims or receipts.
