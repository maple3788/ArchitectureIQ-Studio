#!/usr/bin/env python3
"""Prepare a separate KB runtime with fail-closed semantic registration gates.

Preparation only copies source; it never starts models or generates questions.
The copied ``tools/kb_loop/loop.py`` remains the supported runtime entry point.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import shutil
from contextvars import ContextVar
from typing import Any

MANIFEST = "consistency-runtime.json"
RUN_MARKER = "consistency-runtime-binding.json"
_context: ContextVar[dict] = ContextVar("claim_budget_context")
ENTRY_ANCHOR = '\nif __name__ == "__main__":\n    main()\n'


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _policy():
    from architecture_iq.kb import claim_consistency
    return claim_consistency


def require_authorized_execution() -> None:
    authorized = os.environ.get("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST", "").strip()
    execution = os.environ.get("ARCHITECTURE_IQ_KB_EXECUTION_HOST", "").strip()
    if platform.system() != "Linux" or not authorized or execution != authorized:
        raise RuntimeError("KB execution requires Linux and matching nonempty private authorized/execution hosts")


def _literal_constants(path: Path) -> dict:
    constants = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"BUDGETS", "FAMILIES", "FAMILY_WEIGHTS"}:
                    expected = ast.parse("tuple(f for f, _ in FAMILY_WEIGHTS)", mode="eval").body
                    if target.id == "FAMILIES" and ast.dump(node.value) == ast.dump(expected):
                        constants["FAMILIES"] = tuple(f for f, _ in constants["FAMILY_WEIGHTS"])
                    else:
                        constants[target.id] = ast.literal_eval(node.value)
    return constants


def _frozen_rule_semantics(path: Path) -> str:
    """Read the frozen proposer DSL as data, without importing runtime code."""
    try:
        assignments = [node.value for node in ast.parse(path.read_text()).body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "DSL" for target in node.targets)]
        if len(assignments) != 1:
            raise ValueError("expected exactly one DSL assignment")
        semantics = ast.literal_eval(assignments[0])
        if not isinstance(semantics, str) or not semantics.strip():
            raise ValueError("DSL must be a nonempty literal string")
        return semantics
    except (OSError, SyntaxError, TypeError, ValueError) as exc:
        raise ValueError("frozen proposer DSL semantics are missing or unsupported") from exc


def budget_context(runtime_root: Path, cfg: dict) -> dict:
    """Resolve exact allowed steps from frozen settings, never evidence extrema."""
    from architecture_iq.profile import Profile
    from architecture_iq.candidates.generator import valid_batch_sizes

    root = Path(runtime_root).resolve()
    constants = _literal_constants(root / "tools/kb_loop/questions.py")
    semantics = _frozen_rule_semantics(root / "tools/kb_loop/proposer.py")
    budgets, families = constants.get("BUDGETS"), constants.get("FAMILIES")
    if not budgets or not families or any(type(x) is not int or x <= 0 for x in budgets):
        raise ValueError("frozen questions must declare positive BUDGETS and nonempty FAMILIES")
    profile_path = (root / "profiles" / f"{cfg['profile']}.yaml").resolve()
    if not profile_path.is_relative_to(root / "profiles"):
        raise ValueError("profile must be within the frozen runtime")
    profile = Profile.load(profile_path)
    combinations = []
    for family in families:
        defaults = profile.family_training_defaults(family)
        for budget in sorted(set(budgets)):
            batches = ([defaults["batch_size"]] if defaults and budget == defaults["total_samples_seen"]
                       else valid_batch_sizes(profile, budget))
            if not batches:
                raise ValueError(f"no configured batch size for {family}, budget {budget}")
            for batch in batches:
                if type(batch) is not int or batch <= 0 or budget % batch:
                    raise ValueError("invalid frozen budget/batch combination")
                combinations.append({"family": family, "budget": budget, "batch_size": batch, "steps": budget // batch})
    return {"status": "configured", "source": "frozen_runtime_profile",
            "budget_values": sorted(set(budgets)), "steps_values": sorted({c["steps"] for c in combinations}),
            "profile": profile.name, "combinations": combinations,
            "rule_semantics": semantics, "rule_semantics_source": "tools/kb_loop/proposer.py:DSL",
            "config_hash": _digest({"profile": profile.raw, "constants": constants, "loop_config": cfg,
                                    "rule_semantics": semantics})}


def drafts(props: dict):
    """Enumerate every supported registration branch, including legacy revisions."""
    for cid, rows in props.get("splits", {}).items():
        for index, claim in enumerate(rows):
            yield f"{cid}#{index}", claim
    for cid, claim in props.get("revisions", {}).items():
        if claim:
            yield cid, claim
    for index, claim in enumerate(props.get("new", [])):
        yield f"new{index}", claim


def gate_proposals(props: dict, context: dict) -> None:
    policy = _policy()
    audits = props.get("consistency") or {}
    for key, claim in drafts(props):
        try:
            policy.gate_claim(claim, context, audits.get(key))
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"registration blocked for {key}: {exc}") from exc


def _compatible_audit(claim: dict, context: dict, audit: dict) -> dict:
    """Keep the full bound audit while supporting existing boolean projections."""
    result = copy.deepcopy(audit)
    try:
        _policy().gate_claim(claim, context, result)
    except (TypeError, ValueError, KeyError) as exc:
        result["consistent"] = False
        if result.get("status") == "passed":
            result["status"] = "needs_review"
            result.setdefault("issues", []).append({"code": "registration_gate_failed", "message": str(exc)})
        messages = [issue["message"] for issue in result.get("issues", [])
                    if isinstance(issue, dict) and isinstance(issue.get("message"), str)]
        result["issue"] = "; ".join(messages)[:1000] or str(exc)[:1000]
    else:
        result.update(consistent=True, issue="")
    return result


def _generation_messages(messages: list[dict], context: dict) -> list[dict]:
    messages = copy.deepcopy(messages)
    messages.append({"role": "user", "content": (
        'Mandatory claim schema: each claim has text, rules, rationale, and explanation '
        '({"text": "...", "status": "hypothesis"}). '
        "Put causal hypotheses only in explanation.text; text must contain no causal clause. "
        "State explicit numeric budget or training-step scope in text AND encode it in every rule, "
        "applying to BOTH candidates: constrain budget to budget_values AND steps to steps_values "
        "in every rule's scope. Use the actual frozen configuration below; the generic legacy "
        "short-budget description above is superseded by these values. No broader scope is permitted. "
        "The text must describe all rule conditions and the exact prediction with identical direction.\n"
        + json.dumps(context, sort_keys=True))})
    return messages


def _parse_claims(reply: str, extract_json, *, revision: bool = False):
    data = extract_json(reply)
    items = [data] if revision else data.get("claims", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("claim reply must contain a claims list")
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("rules"), list):
            raise ValueError("each claim requires text and rules")
        explanation = item.get("explanation", {"text": "", "status": "hypothesis"})
        if not isinstance(explanation, dict) or not isinstance(explanation.get("text"), str) or explanation.get("status") != "hypothesis":
            raise ValueError("explanation must be a separate text/status hypothesis object")
        out.append({"text": item["text"].strip(), "rules": item["rules"],
                    "rationale": str(item.get("rationale", "")), "explanation": explanation})
    return out[0] if revision else out


class _GenerationPool:
    """Replace obsolete weak consistency calls; outer stage performs structured audit."""
    def __init__(self, pool):
        self.pool = pool

    @property
    def stats(self):
        return self.pool.stats

    def map(self, jobs):
        jobs = list(jobs)
        if jobs and all(str(job[2]).startswith("cons:") for job in jobs):
            # An operational skip, never a fabricated model response. The original
            # stage records unchecked and the outer stage stores the real audit.
            return [RuntimeError("legacy check superseded by structured semantic audit") for _ in jobs]
        if any(str(job[2]).startswith("cons:") for job in jobs):
            raise ValueError("unsupported mixed generation/legacy consistency batch")
        return self.pool.map(jobs)


class _RegistrationStore:
    """Preserve explanation before original version/receipt/claims persistence."""
    def __init__(self, store, props):
        self.store = store
        self.explanations = {_digest(props["consistency"][key]): c.get("explanation")
                             for key, c in drafts(props)}

    def __getattr__(self, name):
        return getattr(self.store, name)

    def write_version(self, claim):
        key = _digest(claim["consistency"])
        claim["explanation"] = self.explanations[key]
        self.store.write_version(claim)


def install(loop, runtime_root: Path) -> None:
    """Install guards in the copied loop. No network or training occurs here."""
    if getattr(loop, "_semantic_gate_installed", False):
        return
    expected = {"stage_propose": ["store", "k", "cfg"], "stage_register": ["store", "k", "props"],
                "_pool": ["store", "cfg"], "stage_build": ["store", "k", "cfg"]}
    for name, parameters in expected.items():
        if list(inspect.signature(getattr(loop, name)).parameters) != parameters:
            raise ValueError(f"unsupported frozen loop signature: {name}")
    original_propose, original_register, original_pool = loop.stage_propose, loop.stage_register, loop._pool
    proposer = loop.proposer

    for name in ("proposal_messages", "revision_messages"):
        original = getattr(proposer, name)
        def messages(*args, _original=original, **kwargs):
            return _generation_messages(_original(*args, **kwargs), _context.get())
        setattr(proposer, name, messages)
    proposer.parse_proposals = lambda reply: _parse_claims(reply, proposer.extract_json)
    proposer.parse_revision = lambda reply: _parse_claims(reply, proposer.extract_json, revision=True)
    def parse_consistency(reply):
        data = proposer.extract_json(reply)
        if not isinstance(data, dict) or type(data.get("consistent")) is not bool:
            raise ValueError("consistency result must contain a boolean")
        return data
    proposer.parse_consistency = parse_consistency

    def pool(store, cfg):
        require_authorized_execution()
        return _GenerationPool(original_pool(store, cfg))

    def propose(store, k, cfg):
        context = budget_context(runtime_root, cfg)
        token = _context.set(context)
        try:
            props = original_propose(store, k, cfg)
        finally:
            _context.reset(token)
        rows = list(drafts(props))
        if not rows:
            return props
        policy = _policy()
        require_authorized_execution()
        audit_pool = original_pool(store, cfg)
        temperature = loop._proposer_cfg(cfg)["check_temperature"]
        jobs = [(policy.audit_messages(claim, context), temperature,
                 f"semantic:{k}:{key}:{policy.claim_hash(claim)}:{context['config_hash']}") for key, claim in rows]
        replies = list(audit_pool.map(jobs))
        if len(replies) != len(rows):
            raise ValueError("semantic audit reply count mismatch")
        audits = {}
        for (key, claim), reply in zip(rows, replies):
            try:
                data = proposer.extract_json(reply) if not isinstance(reply, Exception) else None
            except (ValueError, TypeError, KeyError):
                data = None
            audits[key] = _compatible_audit(claim, context, policy.validate_audit(claim, context, data))
        props["consistency"] = audits
        props["budget_context"] = context
        loop._dump(store.round_dir(k) / "proposals.json", props)
        return props

    def register(store, k, props):
        guard = getattr(loop, "_require_prepared_runtime", None)
        if guard is not None:
            guard(store.root)
        context = budget_context(runtime_root, store.config())
        gate_proposals(props, context)
        receipt = store.round_dir(k) / "preregistered.json"
        if receipt.exists():
            # The original function returns immediately here. Validate its persisted claims too.
            for claim in loop._json(receipt)["claims"]:
                _policy().gate_claim(claim, context, claim.get("consistency"))
        else:
            # A valid cached structured proposal may predate the compatibility fields.
            # Normalize only the new version payload, never a sealed receipt.
            props = copy.deepcopy(props)
            for key, claim in drafts(props):
                props["consistency"][key] = _compatible_audit(claim, context, props["consistency"][key])
        return original_register(_RegistrationStore(store, props), k, props)

    original_build = loop.stage_build
    def build(store, k, cfg):
        require_authorized_execution()
        return original_build(store, k, cfg)

    loop._pool, loop.stage_propose, loop.stage_register, loop.stage_build = pool, propose, register, build
    loop._semantic_gate_installed = True


def bootstrap(loop, runtime_root: Path) -> None:
    """Bind the supported command to copied source and a newly initialized run."""
    import architecture_iq
    root = Path(runtime_root).resolve()
    if not Path(architecture_iq.__file__).resolve().is_relative_to(root / "src/architecture_iq"):
        raise RuntimeError("architecture_iq import must resolve inside the new runtime source")
    manifest = json.loads((root / MANIFEST).read_text())
    for relative, expected in manifest["installed_hashes"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"prepared runtime changed: {relative}; prepare a new runtime")
    install(loop, root)
    original_init = loop.cmd_init
    def initialize(args):
        require_authorized_execution()
        if args.root.exists():
            raise ValueError("initialize requires a new run directory; historical runs cannot be rebound")
        original_init(args)
        (args.root / RUN_MARKER).write_text(json.dumps({"runtime_manifest_hash": _digest(manifest)}) + "\n")
    loop.cmd_init = initialize
    for name in ("cmd_round", "cmd_forever"):
        original = getattr(loop, name)
        def command(args, _original=original):
            require_authorized_execution()
            marker = args.root / RUN_MARKER
            if not marker.is_file() or json.loads(marker.read_text()).get("runtime_manifest_hash") != _digest(manifest):
                raise ValueError("run is not bound to this prepared runtime; never resume frozen runs with new source")
            return _original(args)
        setattr(loop, name, command)


def prepare_runtime(source_root: Path, destination: Path, *, policy_path: Path | None = None) -> dict:
    """Copy source-only directories to an absent destination, then install the gate."""
    source, destination = Path(source_root).resolve(), Path(destination).resolve()
    if destination.exists() or destination == source or destination.is_relative_to(source):
        raise ValueError("destination must be a new directory outside the original runtime")
    loop_path = source / "tools/kb_loop/loop.py"
    loop_text = loop_path.read_text()
    if loop_text.count(ENTRY_ANCHOR) != 1:
        raise ValueError("unsupported loop entrypoint; checked anchor must occur exactly once")
    for relative in ("src/architecture_iq", "profiles", "tools/kb_loop"):
        if not (source / relative).is_dir():
            raise ValueError(f"complete runtime source required: missing {relative}")
    policy_path = policy_path or Path(__file__).resolve().parents[1] / "src/architecture_iq/kb/claim_consistency.py"
    policy_bytes = policy_path.read_bytes()
    adapter_bytes = Path(__file__).read_bytes()
    copied = {}
    # Never copy run state, datasets, weights, .env, VCS metadata, or dependency caches.
    allowed_suffixes = {".py", ".yaml", ".yml", ".json", ".j2", ".jinja", ".jinja2", ".txt", ".md"}
    created = False
    try:
        destination.mkdir(parents=True, exist_ok=False)
        created = True
        for directory in ("src", "profiles", "tools", "prompts", "configs"):
            for file in sorted((source / directory).rglob("*")):
                if file.is_symlink():
                    raise ValueError("runtime source symlinks are unsupported")
                if not file.is_file() or file.suffix not in allowed_suffixes or any(part.startswith(".") or part == "__pycache__" for part in file.relative_to(source).parts):
                    continue
                relative = file.relative_to(source)
                data = file.read_bytes()
                copied[str(relative)] = hashlib.sha256(data).hexdigest()
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        target_policy = destination / "src/architecture_iq/kb/claim_consistency.py"
        target_policy.parent.mkdir(parents=True, exist_ok=True)
        (target_policy.parent / "__init__.py").touch(exist_ok=True)
        target_policy.write_bytes(policy_bytes)
        (destination / "tools/kb_consistency_runtime.py").write_bytes(adapter_bytes)
        replacement = ('\nfrom kb_consistency_runtime import bootstrap as _consistency_bootstrap\n'
                       '_consistency_bootstrap(sys.modules[__name__], Path(__file__).resolve().parents[2])\n'
                       + ENTRY_ANCHOR)
        (destination / "tools/kb_loop/loop.py").write_text(loop_text.replace(ENTRY_ANCHOR, replacement))
        installed = {str(file.relative_to(destination)): hashlib.sha256(file.read_bytes()).hexdigest()
                     for file in sorted(destination.rglob("*")) if file.is_file()}
        manifest = {"schema_version": 1, "source_hashes": copied, "installed_hashes": installed}
        (destination / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return manifest
    except BaseException:
        if created:
            shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="complete frozen runtime source, read only")
    parser.add_argument("--destination", type=Path, required=True, help="new source directory outside original runtime")
    args = parser.parse_args()
    manifest = prepare_runtime(args.source_root, args.destination)
    print(json.dumps({"destination": str(args.destination.resolve()), "files": len(manifest["installed_hashes"]),
                      "entrypoint": "PYTHONPATH=<new-runtime>/src python <new-runtime>/tools/kb_loop/loop.py"}))


if __name__ == "__main__":
    main()
