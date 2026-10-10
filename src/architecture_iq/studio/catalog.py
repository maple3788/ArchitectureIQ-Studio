"""Read-only source adapters and an immutable, revision-aware question catalog.

No source modules are imported or executed. SQLite stores the small index; frozen
JSON records contain the public projection and separately gated stored feedback.
Filesystem references are confined to the explicitly imported source root.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any

from architecture_iq.kb.rules import CONTROL_FIELDS, public_views
from .rag_inputs import rag_ready
from architecture_iq.studio.pairs import pair_manifest, pair_provenance


_CANDIDATE_KEYS = frozenset("schema_version candidate_id dataset_id family profile profile_hash budget model optimizer loss execution files trainable_parameter_count".split())
_DATASET_KEYS = frozenset("schema_version dataset_id family profile profile_hash selection_metric params seeds seed files synthesis task".split())
_CODE_FILES = ("model.py", "optimizer.py", "loss.py", "train.py")
# These are public structural schemas, not pool inventories. They mirror the
# fields consumed by model/loss/optimizer renderers. Extending a renderer's
# structure requires extending this projection; unknown fields never become
# serialized CONTROL_FIELDS fingerprints.
_NUM = (int, float)
_MODEL_STRUCTURE = {**{key: int for key in "depth width input_dim output_dim vocab_size context_length d_model embed_dim num_layers num_heads d_ff ff_dim".split()},
    "type": str, "activation": str, "activations": [str], "layer_norm": [bool],
    "residual": bool, "layer_residual": bool, "leaky_relu_slope": _NUM}
_OPTIMIZER_STRUCTURE = {"type": str, "lr": _NUM, "weight_decay": _NUM, "momentum": _NUM, "betas": [_NUM]}
_LOSS_STRUCTURE = {"loss_id": str, "type": str, "lambda": _NUM}
_PARAM_STRUCTURE = {**{key: int for key in "instance_seed input_dim output_dim num_classes train_size test_size vocab_size context_length sequence_seed table_seed n_active_features".split()},
    **{key: _NUM for key in "alpha spiral_turns noise_std margin label_noise scale".split()},
    "expression": str, "rule_family": str, "layout": str, "domain": [_NUM], "active_features": [int],
    "sampler": {"id": str, "seed": int, "max_depth": int, "retry": int},
    "point_sampling": {"distribution": str, "seed": int}}
_BUDGET_STRUCTURE = {"training_steps": int, "batch_size": int, "total_samples_seen": int, "mixed": bool}
_FILE_STRUCTURE = {key: str for key in "synthesize train test transition model optimizer loss".split()}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scalar(value: Any) -> bool:
    return value is None or type(value) in (str, bool, int) or type(value) is float and math.isfinite(value)


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _structure(value: Any, schema: dict, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    projected = {}
    for key, descriptor in schema.items():
        if key not in value:
            continue
        item = value[key]
        if isinstance(descriptor, dict):
            projected[key] = _structure(item, descriptor, f"{label}.{key}")
        elif isinstance(descriptor, list):
            if not isinstance(item, list) or len(item) > 4096:
                raise ValueError(f"{label}.{key} must be a bounded list")
            element = descriptor[0]
            allowed = element if isinstance(element, tuple) else (element,)
            if any(type(v) not in allowed or not _scalar(v) for v in item):
                raise ValueError(f"Invalid value in {label}.{key}")
            if key == "betas" and len(item) != 2:
                raise ValueError(f"{label}.betas requires two numbers")
            projected[key] = item
        else:
            allowed = descriptor if isinstance(descriptor, tuple) else (descriptor,)
            if type(item) not in allowed or not _scalar(item):
                raise ValueError(f"Invalid value for {label}.{key}")
            projected[key] = item
    return projected


def _budget(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key in {
            "training_steps", "batch_size", "total_samples_seen", "mixed"} and (
                type(item) in (int, float, bool) or isinstance(item, list) and all(type(v) in (int, float) for v in item))}
    return value if type(value) in (int, float) else None


def _spec(value: Any, keys: frozenset) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Spec must be an object")
    shapes = {"model": _MODEL_STRUCTURE, "optimizer": _OPTIMIZER_STRUCTURE, "loss": _LOSS_STRUCTURE,
              "params": _PARAM_STRUCTURE, "budget": _BUDGET_STRUCTURE, "execution": {"device": str},
              "files": _FILE_STRUCTURE, "seeds": {"expression": int, "point": int, "sequence": int, "table": int}}
    result = {}
    for key, item in value.items():
        if key not in keys:
            continue
        if key in shapes:
            result[key] = _structure(item, shapes[key], key)
        elif _scalar(item):
            result[key] = item
        else:
            raise ValueError(f"Invalid spec field: {key}")
    return result


def _public_view(value: Any) -> dict:
    result = {}
    control_shapes = {"arch_key": _MODEL_STRUCTURE, "opt_key": _OPTIMIZER_STRUCTURE, "loss_key": _LOSS_STRUCTURE}
    for key, item in _object(value).items():
        if key not in CONTROL_FIELDS or not _scalar(item):
            continue
        if key in control_shapes:
            if not isinstance(item, str) or len(item) > 65536:
                continue
            try:
                item = _json(_structure(json.loads(item), control_shapes[key], key))
            except (ValueError, TypeError, RecursionError):
                continue
        result[key] = item
    return result


def _public_question(value: dict) -> dict:
    allowed = {"id", "family", "dataset_id", "lineage_id", "prompt", "split", "pair_id", "profile_hash"}
    result = {key: item for key, item in value.items() if key in allowed and isinstance(item, str)}
    choices = value.get("choices", [])
    if not isinstance(choices, list):
        raise ValueError("Stored public choices must be a list")
    result["choices"] = [{"id": choice.get("id"), "letter": choice.get("letter"),
                          "view": _public_view(choice.get("view"))} for choice in choices if isinstance(choice, dict)]
    return result


def _read(path: Path, boundary: Path) -> Any:
    path = _bound(path, boundary)
    def invalid(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid)


def _bound(path: Path, boundary: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(boundary.resolve()):
        raise ValueError(f"Artifact outside source root: {path}")
    return resolved


def _text(path: Path, boundary: Path) -> str:
    return _bound(path, boundary).read_text(encoding="utf-8")


def _identifier(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value else fallback


class Catalog:
    """Thread-safe through per-operation SQLite connections and frozen files."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "records").mkdir(exist_ok=True)
        (self.root / "sets").mkdir(exist_ok=True)
        self.db = self.root / "catalog.sqlite3"
        with closing(self._connect()) as conn, conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS questions (
                    key TEXT PRIMARY KEY, id TEXT NOT NULL, hash TEXT NOT NULL,
                    family TEXT, type TEXT, lineage_id TEXT, split TEXT, summary TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS question_id ON questions(id);
                CREATE INDEX IF NOT EXISTS question_family ON questions(family, type);
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL,
                    hash TEXT NOT NULL, imported_at TEXT NOT NULL, report TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS aliases (
                    source_id TEXT NOT NULL, key TEXT NOT NULL, origin TEXT NOT NULL,
                    issues TEXT NOT NULL DEFAULT '[]', blocked INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(source_id, key, origin));
                CREATE INDEX IF NOT EXISTS aliases_key ON aliases(key);
                CREATE TABLE IF NOT EXISTS question_sets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL,
                    created_at TEXT NOT NULL, count INTEGER NOT NULL);
            """)
            alias_columns = {row["name"] for row in conn.execute("PRAGMA table_info(aliases)")}
            if "issues" not in alias_columns:
                conn.execute("ALTER TABLE aliases ADD COLUMN issues TEXT NOT NULL DEFAULT '[]'")
            if "blocked" not in alias_columns:
                conn.execute("ALTER TABLE aliases ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _freeze(self, path: Path, value: dict) -> None:
        serialized = _json(value)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != serialized:
                raise ValueError("Immutable catalog record was changed")

    def _source_files(self, source: Path) -> list[Path]:
        if source.is_file():
            return [source]
        if not source.is_dir():
            raise ValueError(f"Source does not exist: {source}")
        files = []
        excluded = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", "results"}
        metadata_files = {"set.json", "run.json", "manifest.json", "private_feedback.json", "source_manifest.json"}
        for directory, dirs, names in os.walk(source, followlinks=False):
            files.extend(Path(directory) / d for d in sorted(dirs) if d not in excluded
                         and (Path(directory) / d).is_symlink())
            dirs[:] = sorted(d for d in dirs if d not in excluded and not d.startswith(".pytest")
                             and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                if name.endswith(".json") and name not in metadata_files and not name.endswith("_spec.json"):
                    files.append(Path(directory) / name)
        return files

    def _pairmap(self, path: Path | None) -> tuple[dict, str | None]:
        if path is None:
            return {}, None
        # A pairmap is another explicit input; its own path is authorized, while
        # none of the artifact references inside it are followed.
        payload = _read(path, path.parent)
        if not isinstance(payload, list) and not (isinstance(payload, dict) and "pairs" in payload):
            raise ValueError("Pairmap requires a list or an object containing pairs")
        rows = payload if isinstance(payload, list) else payload["pairs"]
        if not isinstance(rows, list):
            raise ValueError("Pairmap requires a list of pair records")
        payload_hash = _hash(payload)
        mapping = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Pairmap entry must be an object")
            original, counter = row.get("original_question"), row.get("counterfactual_question")
            if not isinstance(original, str) or not isinstance(counter, str):
                raise ValueError("Pairmap requires original_question and counterfactual_question")
            family = row.get("family", "")
            pair_id = _identifier(row.get("pair_id"), "pair_" + _hash({"family": family,
                "original": original, "counterfactual": counter})[:24])
            # The original dataset is the shared lineage even across separate
            # DataFlip files. Do not let aliases in a source override this link.
            lineage = _identifier(row.get("lineage_id"), f"{family}:{row.get('original_dataset') or original}")
            for role, question, dataset in (("original", original, row.get("original_dataset")),
                                             ("counterfactual", counter, row.get("counterfactual_dataset"))):
                for identifier in {question, Path(question).name}:
                    lookup = (family, identifier)
                    item = {"verification": "pairmap", "pair_id": pair_id, "lineage_id": lineage, "role": role,
                            "original_question_id": Path(original).name,
                            "counterfactual_question_id": Path(counter).name,
                            "dataset_id": _identifier(dataset),
                            "original_dataset_id": _identifier(row.get("original_dataset")),
                            "counterfactual_dataset_id": _identifier(row.get("counterfactual_dataset")),
                            "pairmap_hash": payload_hash}
                    if "candidate_mapping" in row:
                        item["candidate_mapping"] = row["candidate_mapping"]
                    item["selection_history"] = row.get("selection_history", "unknown")
                    item = pair_provenance(item)
                    if lookup in mapping and mapping[lookup] != item:
                        raise ValueError(f"Ambiguous pairmap question: {identifier}")
                    mapping[lookup] = item
        return mapping, payload_hash

    def _raw_question(self, path: Path, boundary: Path) -> tuple[dict, list[str]]:
        raw = _read(path, boundary)
        if not isinstance(raw, dict):
            raise ValueError("question.json must be an object")
        issues = []
        qdir = path.parent
        ds_files = {}
        for parent in (qdir, *qdir.parents):
            if not parent.is_relative_to(boundary):
                break
            ds_path = parent / "dataset_spec.json"
            if ds_path.exists():
                for name in ("dataset_spec.json", "synthesize.py"):
                    item = parent / name
                    if item.exists():
                        ds_files[name] = _read(item, boundary) if name.endswith("json") else _text(item, boundary)
                break
        if not ds_files:
            issues.append("Missing dataset_spec.json inside source root")
        choices, candidate_metrics = [], {}
        for index, choice in enumerate(raw.get("choices", [])):
            if not isinstance(choice, dict):
                issues.append(f"Malformed choice {index}")
                continue
            files = {}
            reference = choice.get("candidate_path")
            try:
                if not isinstance(reference, str) or not reference:
                    raise ValueError("Missing candidate_path")
                candidates = [Path(reference)] if Path(reference).is_absolute() else [boundary / reference, qdir / reference]
                # Artifact-root-relative paths can refer from nested questions;
                # search only known ancestor roots within the registered root.
                if not Path(reference).is_absolute():
                    candidates.extend(parent / reference for parent in qdir.parents if parent.is_relative_to(boundary))
                    # Canonical paths are relative to data/. A source may be
                    # data/datasets/ itself; the referenced object must still
                    # resolve strictly underneath that registered boundary.
                    candidates.append(boundary.parent / reference)
                resolved = [item.resolve() for item in candidates if item.resolve().is_relative_to(boundary)]
                if not resolved:
                    raise ValueError(f"Artifact outside source root: {reference}")
                candidate_dir = next((item for item in resolved if (item / "candidate_spec.json").is_file()), resolved[0])
                files["candidate_spec.json"] = _read(candidate_dir / "candidate_spec.json", boundary)
                for name in _CODE_FILES:
                    code = candidate_dir / name
                    if code.exists():
                        files[name] = _text(code, boundary)
                summary = candidate_dir / "results" / "summary.json"
                if summary.exists():
                    candidate_metrics[choice.get("candidate_id", "")] = _read(summary, boundary)
            except (OSError, ValueError, TypeError) as exc:
                issues.append(f"Choice {choice.get('letter', index)}: {exc}")
            choices.append({"letter": choice.get("letter"), "candidateId": choice.get("candidate_id"), "files": files})
        try:
            prompt = _text(qdir / "prompt.txt", boundary)
        except (OSError, ValueError) as exc:
            prompt = ""
            issues.append(f"Prompt unavailable: {exc}")
        adapted = {**raw, "id": raw.get("question_id"), "datasetId": raw.get("dataset_id"),
                   "metric": _object(raw.get("evaluation")).get("selection_metric") or _object(raw.get("significance")).get("metric"),
                   "detail": {"prompt": prompt, "dataset": {"files": ds_files}, "choices": choices},
                   "feedback": {"correct_letter": raw.get("correct_letter"), "candidate_metrics": candidate_metrics},
                   "_raw_question": raw}
        return adapted, issues

    def _entries(self, path: Path, boundary: Path) -> list[tuple[str, Any, list[str]]]:
        if path.name == "question.json":
            raw, issues = self._raw_question(path, boundary)
            return [(raw.get("id") or path.parent.name, raw, issues)]
        payload = _read(path, boundary)
        if isinstance(payload, dict) and "byId" in payload:
            by_id = payload["byId"]
            if not isinstance(by_id, dict):
                raise ValueError("Bake byId must be an object")
            entries, used = [], set()
            for summary in payload.get("questions", []):
                identifier = summary.get("id") if isinstance(summary, dict) else summary
                if not isinstance(identifier, str):
                    entries.append(("", None, ["Malformed Bake summary ID"]))
                    continue
                used.add(identifier)
                item = by_id.get(identifier)
                if isinstance(item, dict):
                    item = {**_object(summary), **item}
                entries.append((identifier, item, [] if item is not None else ["Bake summary missing byId record"]))
            for identifier, item in by_id.items():
                if identifier not in used:
                    entries.append((identifier, item, ["Bake byId record absent from ordered summaries"]))
            return entries
        feedback = {}
        private_path = path.parent / "private_feedback.json"
        if path.name == "public_questions.json" and private_path.exists():
            feedback = _read(private_path, boundary)
            if not isinstance(feedback, dict):
                raise ValueError("private_feedback.json must be an object")
        if isinstance(payload, dict) and isinstance(payload.get("public_questions"), list):
            feedback = _object(payload.get("private_feedback", feedback))
            payload = payload["public_questions"]
        elif isinstance(payload, dict) and isinstance(payload.get("questions"), list):
            feedback = _object(payload.get("feedback", feedback))
            payload = payload["questions"]
        elif isinstance(payload, dict) and (payload.get("id") or payload.get("question_id")):
            payload = [payload]
        if not isinstance(payload, list):
            raise ValueError("Unsupported source: expected Bake, public records, or question.json")
        entries = []
        for index, raw in enumerate(payload):
            identifier = _object(raw).get("id") or _object(raw).get("question_id") or f"entry-{index}"
            if isinstance(raw, dict) and identifier in feedback:
                raw = {**raw, "feedback": feedback[identifier]}
            entries.append((identifier, raw, []))
        return entries

    def _normalize(self, identifier: str, raw: dict, initial_issues: list[str], pairs: dict) -> dict:
        # Source-local diagnostics belong to aliases/import reports. They must
        # not turn otherwise identical question content into another revision.
        issues = []
        detail = _object(raw.get("detail"))
        ds = _spec(_object(_object(detail.get("dataset")).get("files")).get("dataset_spec.json")
                   or raw.get("dataset_spec"), _DATASET_KEYS)
        family = _identifier(raw.get("family"), _identifier(ds.get("family")))
        dataset_id = _identifier(raw.get("dataset_id") or raw.get("datasetId"), _identifier(ds.get("dataset_id")))
        embedded_id = _identifier(ds.get("dataset_id"))
        detail_id = _identifier(_object(detail.get("dataset")).get("datasetId")
                                or _object(detail.get("dataset")).get("dataset_id"))
        if embedded_id and embedded_id != dataset_id:
            issues.append("Dataset spec binding mismatch")
        if detail_id and detail_id != dataset_id:
            issues.append("Dataset detail binding mismatch")
        ds = {**ds, "family": family, "dataset_id": dataset_id}
        metric = (_identifier(raw.get("metric")) or _identifier(ds.get("selection_metric"))
                  or _identifier(_object(raw.get("evaluation")).get("selection_metric"))) or None
        if metric:
            ds.setdefault("selection_metric", metric)
        prompt = detail.get("prompt") if isinstance(detail.get("prompt"), str) else raw.get("prompt")
        prompt = prompt if isinstance(prompt, str) else ""
        pair = (pairs.get((family, identifier)) or pairs.get((family, Path(identifier).name))
                or pairs.get(("", identifier)) or pairs.get(("", Path(identifier).name)) or {})
        pair_id = _identifier(pair.get("pair_id") or raw.get("pair_id")) or None
        if pair.get("dataset_id") and pair["dataset_id"] != dataset_id:
            issues.append("Pairmap dataset binding mismatch")
        verified_reuse = (pair.get("role") == "counterfactual" and pair.get("dataset_id") == dataset_id
                          and bool(pair.get("original_dataset_id")) and pair.get("counterfactual_dataset_id") == dataset_id
                          and not any("Dataset" in issue for issue in issues))
        lineage = (_identifier(pair.get("lineage_id"), f"pair:{pair_id}") if pair_id
                   else _identifier(raw.get("lineage_id"), f"{family}:{dataset_id}"))
        split = _identifier(raw.get("split", "discovery"), "invalid")
        public = {"id": identifier, "family": family, "dataset_id": dataset_id, "lineage_id": lineage,
                  "prompt": prompt, "split": split, "choices": []}
        if pair_id:
            public["pair_id"] = pair_id
        profile_hash = _identifier(raw.get("profile_hash")) or _identifier(raw.get("profileHash"))
        if isinstance(profile_hash, str) and profile_hash:
            public["profile_hash"] = profile_hash
        display_choices, model_types = [], set()
        source_choices = detail.get("choices", raw.get("choices", []))
        if not isinstance(source_choices, list):
            source_choices = []
            issues.append("choices must be a list")
        for index, choice in enumerate(source_choices):
            if not isinstance(choice, dict):
                issues.append(f"Malformed choice {index}")
                continue
            letter = choice.get("letter")
            files = _object(choice.get("files"))
            spec = _spec(files.get("candidate_spec.json") or choice.get("spec"), _CANDIDATE_KEYS)
            cid = _identifier(choice.get("candidateId") or choice.get("candidate_id") or choice.get("id"),
                              _identifier(spec.get("candidate_id")))
            view = {}
            provenance = None
            if spec:
                source_spec = dict(spec)
                reused = bool(verified_reuse and spec.get("dataset_id") == pair.get("original_dataset_id")
                              and spec.get("dataset_id") != dataset_id)
                if spec.get("dataset_id") and spec["dataset_id"] != dataset_id:
                    if not reused:
                        issues.append(f"Choice {letter}: dataset binding mismatch")
                if spec.get("family") and spec["family"] != family:
                    issues.append(f"Choice {letter}: family binding mismatch")
                summary = (_object(_object(_object(raw.get("reveal")).get("files")).get(letter)).get("summary.json")
                           or _object(_object(raw.get("feedback")).get("candidate_metrics")).get(cid))
                gt_dataset = _identifier(_object(summary).get("dataset_id") or _object(summary).get("datasetId")) or None
                if gt_dataset is not None and gt_dataset != dataset_id:
                    issues.append(f"Choice {letter}: ground-truth dataset binding mismatch")
                if reused:
                    provenance = {"source_candidate_spec": source_spec,
                                  "dataset_binding": {"verification": "pairmap", "pair_id": pair_id,
                                      "pairmap_hash": pair["pairmap_hash"], "original_dataset_id": source_spec["dataset_id"],
                                      "effective_dataset_id": dataset_id, "ground_truth_dataset_id": gt_dataset}}
                spec.update(dataset_id=dataset_id, family=family)
                try:
                    view = public_views(ds, [spec])[0]
                except (ValueError, KeyError, TypeError, ArithmeticError, OverflowError) as exc:
                    issues.append(f"Choice {letter}: cannot derive public features ({exc})")
                model_type = _object(spec.get("model")).get("type")
                if isinstance(model_type, str):
                    model_types.add(model_type)
            else:
                view = _public_view(choice.get("view"))
                if not view:
                    issues.append(f"Choice {letter}: missing candidate spec/public view")
                if isinstance(view.get("model_type"), str):
                    model_types.add(view["model_type"])
            view = _public_view(view)
            public["choices"].append({"id": cid, "letter": letter, "view": view})
            shown = {"letter": letter, "candidateId": cid, "files": {}}
            if spec:
                shown["files"]["candidate_spec.json"] = spec
            if provenance is not None:
                shown["provenance"] = provenance
            for name in _CODE_FILES:
                if isinstance(files.get(name), str):
                    shown["files"][name] = files[name]
            display_choices.append(shown)
        feedback = dict(_object(raw.get("feedback")))
        reveal = _object(raw.get("reveal"))
        if "correct_letter" not in feedback:
            feedback["correct_letter"] = reveal.get("correctLetter") or raw.get("correct_letter")
        candidate_metrics = dict(_object(feedback.get("candidate_metrics")))
        for choice in public["choices"]:
            summary = _object(_object(reveal.get("files")).get(choice["letter"])).get("summary.json")
            if isinstance(summary, dict):
                candidate_metrics[choice["id"]] = summary
        feedback["candidate_metrics"] = candidate_metrics
        if reveal:
            feedback["reveal"] = reveal
        for required, value in (("family", family), ("dataset_id", dataset_id), ("prompt", prompt)):
            if not value:
                issues.append(f"Missing {required}")
        if split not in {"discovery", "development", "final"}:
            issues.append("Invalid split")
        letters = [choice["letter"] for choice in public["choices"]]
        ids = [choice["id"] for choice in public["choices"]]
        if len(letters) < 2 or any(not isinstance(letter, str) or len(letter) != 1 or letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for letter in letters) or len(set(letters)) != len(letters):
            issues.append("Need at least two distinct valid choice letters")
        if not all(ids) or len(set(ids)) != len(ids):
            issues.append("Missing/duplicate candidate IDs")
        if feedback.get("correct_letter") not in letters:
            issues.append("Missing/invalid private correct_letter")
        ds_display = {"family": family, "datasetId": dataset_id, "files": {"dataset_spec.json": ds}}
        ds_source_files = _object(_object(detail.get("dataset")).get("files"))
        if isinstance(ds_source_files.get("synthesize.py"), str):
            ds_display["files"]["synthesize.py"] = ds_source_files["synthesize.py"]
        for name in ("selection_metric", "params"):
            if name in ds:
                ds_display["selectionMetric" if name == "selection_metric" else name] = ds[name]
        # Missing views do not prevent testing the complete canonical prompt;
        # scientific KB operations need usable spec-derived views as well.
        evaluation_issues = [issue for issue in issues if not ("cannot derive public features" in issue
            or "missing candidate spec/public view" in issue or "absent from ordered summaries" in issue)]
        evaluation_ready = not evaluation_issues
        kb_ready = evaluation_ready and len(letters) >= 3 and all(c["view"] for c in public["choices"]) and not any(
            "cannot derive public features" in issue for issue in issues)
        missing_metadata = [field for field, value in (("profile", raw.get("profile")), ("profile_hash", profile_hash),
            ("type", raw.get("type")), ("metric", metric), ("budget", raw.get("budget"))) if value is None or value == ""]
        summary = {"id": identifier, "family": family, "type": _identifier(raw.get("type")), "dataset_id": dataset_id,
                   "profile": _identifier(raw.get("profile")), "model_types": sorted(model_types), "choices": len(letters),
                   "budget": _budget(raw.get("budget")), "metric": metric, "pair_id": pair_id,
                   "lineage_id": lineage, "split": split, "ready": evaluation_ready, "evaluation_ready": evaluation_ready,
                   "kb_ready": kb_ready, "missing_metadata": missing_metadata, "issues": list(dict.fromkeys(issues))}
        if profile_hash:
            summary["profile_hash"] = profile_hash
        record = {"schema_version": 1, "public": public, "detail": {"prompt": prompt, "dataset": ds_display,
                  "choices": display_choices}, "metadata": summary, "feedback": feedback}
        if pair:
            provenance = pair_provenance(pair)
            # Bind the actual imported ID while retaining path-qualified IDs in
            # source maps as a supported legacy lookup form.
            provenance[provenance["role"] + "_question_id"] = identifier
            record["detail"]["pair_provenance"] = provenance
        # Preserve the raw question privately for audit, never expose it to the
        # public detail projection or pass it to downstream roles.
        if "_raw_question" in raw:
            record["raw_question"] = raw["_raw_question"]
        digest = _hash(record)
        key = f"{identifier}@{digest[:24]}"
        record["public"]["id"] = key
        record["metadata"].update(key=key, hash=digest)
        return record

    def import_source(self, path: Path, *, name: str | None = None, pairmap_path: Path | None = None) -> dict:
        source = Path(path).absolute()
        boundary = source.resolve() if source.is_dir() else source.parent.resolve()
        report = {"found": 0, "added": 0, "duplicates": 0, "conflicts": 0, "errors": [], "entries": []}
        prepared, fingerprints = [], []
        pair_error = None
        try:
            pairs, pair_hash = self._pairmap(Path(pairmap_path).absolute() if pairmap_path else None)
        except (OSError, ValueError, TypeError) as exc:
            pairs, pair_hash = {}, None
            pair_error = str(exc)
            report["errors"].append({"path": str(pairmap_path), "error": str(exc)})
        if pairmap_path is not None:
            fingerprints.append(("pairmap_request", {"path": str(pairmap_path), "hash": pair_hash, "error": pair_error}))
        if pair_hash:
            fingerprints.append((str(pairmap_path), pair_hash))
        try:
            source_files = self._source_files(source)
            if not source_files:
                report["errors"].append({"path": str(source), "error": "No supported question artifacts found"})
        except (OSError, ValueError) as exc:
            source_files = []
            report["errors"].append({"path": str(source), "error": str(exc)})
        for source_file in source_files:
            origin = str(source_file)
            try:
                fingerprints.append((origin, hashlib.sha256(_bound(source_file, boundary).read_bytes()).hexdigest()))
                entries = self._entries(source_file, boundary)
            except (OSError, ValueError, TypeError) as exc:
                report["errors"].append({"path": origin, "error": str(exc)})
                report["entries"].append({"path": origin, "id": None, "status": "error", "issues": [str(exc)]})
                continue
            for identifier, raw, issues in entries:
                report["found"] += 1
                entry_origin = f"{origin}#{identifier}"
                if not isinstance(raw, dict):
                    error = "; ".join(issues) or "Question record must be an object"
                    report["errors"].append({"path": origin, "id": identifier, "error": error})
                    report["entries"].append({"path": entry_origin, "id": identifier, "status": "error", "issues": [error]})
                    continue
                try:
                    actual_id = _identifier(raw.get("id") or raw.get("question_id"), identifier)
                    family = _identifier(raw.get("family"))
                    pair = (pairs.get((family, actual_id)) or pairs.get((family, Path(actual_id).name))
                            or pairs.get(("", actual_id)) or pairs.get(("", Path(actual_id).name)))
                    if pairmap_path is not None and (pair_error or not pair):
                        issues = [*issues, "Unresolved supplied pairmap: " + (pair_error or f"No mapping for {actual_id}")]
                    record = self._normalize(actual_id, raw, issues, pairs)
                    prepared.append((entry_origin, record, issues))
                    fingerprints.append((entry_origin, record["metadata"]["hash"]))
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    report["errors"].append({"path": entry_origin, "id": identifier, "error": str(exc)})
                    report["entries"].append({"path": entry_origin, "id": identifier, "status": "error", "issues": [str(exc)]})
        source_hash = _hash(fingerprints)
        source_id = "src_" + _hash({"path": str(source), "hash": source_hash})[:24]
        report.update(source_id=source_id, path=str(source), source_hash=source_hash)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            for origin, record, source_issues in prepared:
                summary = record["metadata"]
                key, digest = summary["key"], summary["hash"]
                exists = conn.execute("SELECT 1 FROM questions WHERE key=?", (key,)).fetchone()
                conflict = conn.execute("SELECT 1 FROM questions WHERE id=? AND key<>?", (summary["id"], key)).fetchone() is not None
                status = "duplicate" if exists else "conflict" if conflict else "added"
                report["duplicates" if exists else "added"] += 1
                if conflict and not exists:
                    report["conflicts"] += 1
                self._freeze(self.root / "records" / (digest + ".json"), record)
                conn.execute("INSERT OR IGNORE INTO questions VALUES (?,?,?,?,?,?,?,?)",
                             (key, summary["id"], digest, summary["family"], summary["type"], summary["lineage_id"], summary["split"], _json(summary)))
                source_blocked = any("absent from ordered summaries" not in issue for issue in source_issues)
                conn.execute("INSERT OR IGNORE INTO aliases (source_id,key,origin,issues,blocked) VALUES (?,?,?,?,?)",
                             (source_id, key, origin, _json(source_issues), int(source_blocked)))
                entry_issues = list(dict.fromkeys([*summary["issues"], *source_issues]))
                report["entries"].append({"path": origin, "id": summary["id"], "key": key,
                    "status": status, "issues": entry_issues, "blocked": source_blocked})
                if not summary["ready"] or source_blocked:
                    report["errors"].append({"path": origin, "id": summary["id"], "error": "; ".join(entry_issues)})
            # A repeated unchanged source has the same identity and can be safely
            # refreshed without overwriting any question or source revision.
            conn.execute("INSERT INTO sources VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET report=excluded.report",
                         (source_id, str(source), name or source.name, source_hash, _now(), _json(report)))
        return report

    def list_questions(self, *, search: str = "", family: str = "", question_type: str = "",
                       source_id: str = "", split: str = "", offset: int = 0, limit: int = 50) -> dict:
        if split not in ("", "discovery", "development", "final"):
            raise ValueError("split must be discovery, development, or final")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("offset must be nonnegative and limit must be between 1 and 1000")
        filters, values = [], []
        for column, value in (("q.family", family), ("q.type", question_type), ("q.split", split)):
            if value:
                filters.append(f"{column}=?")
                values.append(value)
        if search:
            filters.append("(q.id LIKE ? ESCAPE '\\' OR q.family LIKE ? ESCAPE '\\' OR q.summary LIKE ? ESCAPE '\\')")
            query = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            values.extend([query] * 3)
        if source_id:
            filters.append("EXISTS (SELECT 1 FROM aliases a WHERE a.key=q.key AND a.source_id=?)")
            values.append(source_id)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with closing(self._connect()) as conn:
            total = conn.execute("SELECT COUNT(*) FROM questions q" + where, values).fetchone()[0]
            rows = conn.execute("SELECT q.hash, q.summary, (SELECT COUNT(DISTINCT source_id) FROM aliases a WHERE a.key=q.key) AS source_count FROM questions q"
                + where + " ORDER BY q.id, q.key LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
            items = []
            for row in rows:
                summary = {**json.loads(row["summary"]), "source_count": row["source_count"]}
                stored = _read(self.root / 'records' / (row['hash'] + '.json'), self.root)
                summary['rag_ready'] = rag_ready(_public_question(stored['public']))
                query = "SELECT issues, blocked FROM aliases WHERE key=?"
                alias_params = [summary["key"]]
                if source_id:
                    query += " AND source_id=?"
                    alias_params.append(source_id)
                items.append(self._source_state(summary, conn.execute(query, alias_params).fetchall()))
        return {"items": items, "total": total}

    @staticmethod
    def _source_state(summary: dict, aliases: list) -> dict:
        source_issues = list(dict.fromkeys(issue for alias in aliases for issue in json.loads(alias["issues"])))
        if source_issues:
            summary["source_issues"] = source_issues
            summary["issues"] = list(dict.fromkeys([*summary["issues"], *source_issues]))
        if aliases and all(alias["blocked"] for alias in aliases):
            summary.update(ready=False, evaluation_ready=False, kb_ready=False, rag_ready=False)
        return summary

    def _load_frozen_record(self, key: str) -> dict:
        """Verified server-only record, before the public projection is applied."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT hash FROM questions WHERE key=?", (key,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown question revision: {key}")
        record = _read(self.root / "records" / (row["hash"] + ".json"), self.root)
        original = json.loads(_json(record))
        original["public"]["id"] = original["metadata"]["id"]
        original["metadata"].pop("key", None)
        original["metadata"].pop("hash", None)
        if _hash(original) != row["hash"]:
            raise ValueError("Question record integrity check failed")
        return record

    def get_question(self, key: str, *, include_private: bool = False) -> dict:
        record = self._load_frozen_record(key)
        with closing(self._connect()) as conn:
            aliases = conn.execute("SELECT source_id, origin, issues, blocked FROM aliases WHERE key=? ORDER BY source_id, origin", (key,)).fetchall()
        # Stored revisions from previous catalog versions remain immutable.
        # Apply the current public structural boundary on every read as well,
        # so older snapshots cannot bypass tightened import projections.
        record["public"] = _public_question(record["public"])
        record['metadata']['rag_ready'] = rag_ready(record['public'])
        if "pair_provenance" in record["detail"]:
            record["detail"]["pair_provenance"] = pair_provenance(record["detail"]["pair_provenance"])
        for choice in record["detail"].get("choices", []):
            files = _object(choice.get("files"))
            shown = {name: value for name, value in files.items() if name in _CODE_FILES and isinstance(value, str)}
            if "candidate_spec.json" in files:
                shown["candidate_spec.json"] = _spec(files["candidate_spec.json"], _CANDIDATE_KEYS)
            choice["files"] = shown
        dataset = _object(record["detail"].get("dataset"))
        ds_files = _object(dataset.get("files"))
        shown_ds = {"synthesize.py": ds_files["synthesize.py"]} if isinstance(ds_files.get("synthesize.py"), str) else {}
        if "dataset_spec.json" in ds_files:
            shown_ds["dataset_spec.json"] = _spec(ds_files["dataset_spec.json"], _DATASET_KEYS)
        dataset["files"] = shown_ds
        if "params" in dataset:
            dataset["params"] = _structure(dataset["params"], _PARAM_STRUCTURE, "params")
        if not include_private:
            record.pop("feedback", None)
            record.pop("raw_question", None)
        record["metadata"]["source_count"] = len({alias["source_id"] for alias in aliases})
        record["metadata"] = self._source_state(record["metadata"], aliases)
        record["sources"] = [{**dict(alias), "issues": json.loads(alias["issues"])} for alias in aliases]
        return record

    def list_sources(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY imported_at, id").fetchall()
        return [{**dict(row), "report": json.loads(row["report"])} for row in rows]

    def stats(self) -> dict:
        with closing(self._connect()) as conn:
            questions = conn.execute("SELECT key, summary, id FROM questions").fetchall()
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            sets = conn.execute("SELECT COUNT(*) FROM question_sets").fetchone()[0]
            summaries = [self._source_state(json.loads(row["summary"]), conn.execute(
                "SELECT issues,blocked FROM aliases WHERE key=?", (row["key"],)).fetchall()) for row in questions]
        ids = {row["id"] for row in questions}
        return {"questions": len(questions), "question_ids": len(ids), "sources": sources, "question_sets": sets,
                "ready": sum(bool(row["ready"]) for row in summaries), "conflicts": len(questions) - len(ids),
                "families": sorted({row["family"] for row in summaries if row["family"]})}

    def _question_pairs(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT key,summary FROM questions ORDER BY id,key").fetchall()
        groups = {}
        for row in rows:
            summary = json.loads(row["summary"])
            if summary.get("pair_id"):
                groups.setdefault(summary["pair_id"], []).append(self.get_question(row["key"]))
        return [pair_manifest(groups[identifier]) for identifier in sorted(groups)]

    def list_question_pairs(self, *, search: str = "", family: str = "", question_type: str = "",
                            split: str = "", offset: int = 0, limit: int = 25) -> dict:
        if split not in ("", "discovery", "development", "final"):
            raise ValueError("split must be discovery, development, or final")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("offset must be nonnegative and limit must be between 1 and 1000")
        items = []
        for pair in self._question_pairs():
            # Filtering selects complete units; it must never trim one member.
            if any(value and not any(member.get(field) == value for member in pair["members"])
                   for field, value in (("family", family), ("type", question_type), ("split", split))):
                continue
            if search and search.casefold() not in _json(pair).casefold():
                continue
            items.append(pair)
        return {"items": items[offset:offset + limit], "total": len(items)}

    def get_question_pair(self, pair_key: str) -> dict:
        for pair in self._question_pairs():
            if pair["pair_key"] == pair_key:
                return pair
        raise KeyError(f"Unknown question pair revision: {pair_key}")

    def create_question_pair_set(self, name: str, pair_keys: list[str]) -> dict:
        return self.save_question_pair_set(pair_keys, name=name)

    def save_question_pair_set(self, pair_keys: list[str], *, name: str) -> dict:
        if not isinstance(name, str) or not name.strip() or not isinstance(pair_keys, list) or not pair_keys or any(
                not isinstance(key, str) for key in pair_keys):
            raise ValueError("Question pair set requires a name and nonempty ordered pair revision keys")
        if len(set(pair_keys)) != len(pair_keys):
            raise ValueError("Duplicate question pair revision in set")
        # Hold the catalog write lock from validation through publication, so
        # a concurrently imported conflicting revision cannot split validation
        # and the atomic insertion of this frozen set.
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            available = {pair["pair_key"]: pair for pair in self._question_pairs()}
            selected, keys = [], []
            for key in pair_keys:
                if key not in available:
                    raise KeyError(f"Unknown question pair revision: {key}")
                pair = available[key]
                if not pair["ready"]:
                    raise ValueError(f"Question pair is not ready: {key}: {pair['issues']}")
                selected.append(pair)
                keys.extend(member["key"] for member in pair["members"])
            body = self._question_set_body(name, keys)
            body.update(selection_mode="pairs", pair_keys=pair_keys, pairs=selected,
                        pair_count=len(selected), count=len(keys))
            identifier = self._store_question_set(body, conn)
        return self.get_question_set(identifier)

    def _question_set_body(self, name: str, keys: list[str]) -> dict:
        if not isinstance(name, str) or not name.strip() or not isinstance(keys, list) or not keys or any(not isinstance(key, str) for key in keys):
            raise ValueError("Question set requires a name and nonempty ordered revision keys")
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate question revision in set")
        questions, hashes, feedback, lineages, datasets, pairs = [], [], {}, {}, {}, {}
        for key in keys:
            record = self.get_question(key, include_private=True)
            if not record["metadata"]["ready"]:
                raise ValueError(f"Question is not ready: {key}: {record['metadata']['issues']}")
            question = record["public"]
            for group, identifier in ((lineages, question["lineage_id"]), (datasets, question["dataset_id"])):
                if identifier in group and group[identifier] != question["split"]:
                    raise ValueError("A dataset or DataFlip lineage cannot cross question-set splits")
                group[identifier] = question["split"]
            if question.get("pair_id"):
                pair_id = question["pair_id"]
                if pair_id in pairs and pairs[pair_id] != question["split"]:
                    raise ValueError("A DataFlip pair cannot cross question-set splits")
                pairs[pair_id] = question["split"]
            questions.append(question)
            hashes.append(record["metadata"]["hash"])
            feedback[key] = record["feedback"]
        body = {"schema_version": 1, "name": name.strip(), "keys": keys, "hashes": hashes,
                "questions": questions, "feedback": feedback}
        return body

    def _store_question_set(self, body: dict, conn: sqlite3.Connection) -> str:
        digest = _hash(body)
        identifier = "qs_" + digest[:24]
        existing = conn.execute("SELECT id FROM question_sets WHERE id=?", (identifier,)).fetchone()
        if not existing:
            body.update(id=identifier, created_at=_now(), hash=digest)
            self._freeze(self.root / "sets" / (digest + ".json"), body)
            conn.execute("INSERT INTO question_sets VALUES (?,?,?,?,?)",
                         (identifier, body["name"], digest, body["created_at"], len(body["keys"])))
        return identifier

    def _bound_question_set_body(self, name, keys, dataset_binding, pairs=None):
        body = self._question_set_body(name, keys)
        if dataset_binding is not None:
            if dataset_binding['keys'] != keys or dataset_binding['hashes'] != body['hashes']:
                raise ValueError('Dataset binding does not match frozen questions')
            body['dataset_binding'] = dataset_binding
        if pairs is not None:
            checked = [pair_manifest([self.get_question(m['key']) for m in p['members']]) for p in pairs]
            if any(not p['ready'] or p['pair_key'] != original['pair_key'] for p, original in zip(checked, pairs)):
                raise ValueError('Frozen pair identity or availability changed')
            if [m['key'] for p in checked for m in p['members']] != keys:
                raise ValueError('Pair members do not match Dataset selection')
            body.update(selection_mode='pairs', pairs=checked, pair_keys=[p['pair_key'] for p in checked],
                        pair_count=len(checked), count=len(keys))
        return body

    def create_question_set(self, name: str, keys: list[str], *, dataset_binding: dict | None = None) -> dict:
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            body = self._bound_question_set_body(name, keys, dataset_binding)
            identifier = self._store_question_set(body, conn)
        return self.get_question_set(identifier)

    def create_bound_pair_set(self, name: str, pairs: list[dict], *, dataset_binding: dict) -> dict:
        keys = [m['key'] for p in pairs for m in p['members']]
        with closing(self._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            body = self._bound_question_set_body(name, keys, dataset_binding, pairs)
            identifier = self._store_question_set(body, conn)
        return self.get_question_set(identifier)

    def list_question_sets(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM question_sets ORDER BY created_at DESC, id").fetchall()
        items = []
        for row in rows:
            frozen = self.get_question_set(row["id"])
            items.append({**dict(row), "selection_mode": frozen.get("selection_mode", "single"),
                          "pair_count": frozen.get("pair_count", 0), "pair_keys": frozen.get("pair_keys", [])})
        return items

    def get_question_set(self, id: str, *, include_private: bool = False) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT hash FROM question_sets WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown question set: {id}")
        result = _read(self.root / "sets" / (row["hash"] + ".json"), self.root)
        original = {key: value for key, value in result.items() if key not in {"id", "created_at", "hash"}}
        if _hash(original) != row["hash"]:
            raise ValueError("Question-set integrity check failed")
        result["questions"] = [_public_question(question) for question in result["questions"]]
        result.setdefault("selection_mode", "single")
        result.setdefault("count", len(result["questions"]))
        if not include_private:
            result.pop("feedback", None)
        return result
