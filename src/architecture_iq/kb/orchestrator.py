"""A file-backed scientific workflow. Models propose; programs execute and publish."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import time
from pathlib import Path
from typing import Any, Callable

from .evidence import describe_evidence, summarize_confirmation
from .experience import ExperienceStore, build_episode, apply_operations
from .retrieval import retrieve_experience
from .inputs import is_basic_learning, validate_public_inputs
from .pair_learning import (PROTOCOLS, validate_pair_config, ordered_pair_questions,
                            pair_members, research_pair)
from .roles import RoleCaller, exclusive_lock, read_receipt, role_prompt, _seal, validate_role_instructions
from .rules import CONTROL_FIELDS, validate_rule, match_rule, match_validated_scope
from .store import KBStore, canonical_hash, write_json_atomic


DEFAULTS = dict(
    max_rounds=3,
    discovery_per_round=12,
    packet_size=3,
    max_calls_per_round=100,
    max_tokens_per_round=1_200_000,
    max_candidate_seed_runs=1600,
    exploration_count=6,
    n_seeds=10,
    enable_confirmation=True,
    confirmation_count=48,
    seed_start=81_000_000,
    profile="v1.5",
    wall_time_seconds=14400,
    context_size=32768,
)


def source_fingerprint() -> str:
    return canonical_hash(
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        }
    )


def _read(path: Path):
    return json.loads(path.read_text())


def _save(path: Path, value: Any) -> None:
    write_json_atomic(path, value)


def _step(path: Path, inputs: Any, execute: Callable):
    fingerprint = canonical_hash(inputs)
    if path.exists():
        saved = read_receipt(path)
        if saved["input_hash"] != fingerprint:
            raise ValueError(f"Step inputs changed: {path.name}")
        return saved["result"]
    result = execute()
    _save(path, _seal({"input_hash": fingerprint, "result": result}))
    return result


def _validate_config(config: dict) -> dict:
    config = {**DEFAULTS, **copy.deepcopy(config)}
    if config.get("learning_protocol", "single") not in PROTOCOLS:
        raise ValueError("Unknown learning_protocol")
    if config.get("experience_mode", "off") not in {"off", "expel_inspired", "basic_learning"}:
        raise ValueError("Unknown experience_mode")
    basic = is_basic_learning(config)
    if basic or config.get("experience_mode") == "basic_learning":
        if not basic or config.get("experience_mode") != "basic_learning":
            raise ValueError("basic_learning requires its explicit frozen method recipe")
        required = {"discovery_per_round": 1, "packet_size": 1, "max_calls_per_round": 2,
                    "loop_mode": "manual", "learning_protocol": "single",
                    "enable_confirmation": False, "enable_evaluation": False}
        if any(config.get(key) != value for key, value in required.items()):
            raise ValueError("basic_learning requires the two-call manual single-question protocol")
        for key in ("use_previous_experience", "record_conditions"):
            if type(config.setdefault(key, True)) is not bool:
                raise ValueError(f"{key} must be boolean")
    if config.get("initial_kb"):
        if not basic:
            raise ValueError("Initial library KB requires basic_learning")
        from .initial_knowledge import validate_initial_knowledge
        validate_initial_knowledge(config["initial_kb"])
    for key in ("experience_byte_budget",):
        if key in config and (type(config[key]) is not int or not 0 <= config[key] <= 16000):
            raise ValueError(f"{key} must be an integer from zero to 16000")
    for key in (
        "max_rounds",
        "discovery_per_round",
        "packet_size",
        "max_calls_per_round",
        "max_tokens_per_round",
        "max_candidate_seed_runs",
        "exploration_count",
        "n_seeds",
        "seed_start",
        "wall_time_seconds",
        "context_size",
    ):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if config["max_rounds"] > 3:
        raise ValueError("At most three rounds/confirmation attempts")
    if type(config["enable_confirmation"]) is not bool:
        raise ValueError("enable_confirmation must be boolean")
    if "role_instructions" in config:
        config["role_instructions"] = validate_role_instructions(config["role_instructions"])
    if "enable_evaluation" in config and type(config["enable_evaluation"]) is not bool:
        raise ValueError("enable_evaluation must be boolean")
    if config["enable_confirmation"] and (
        config["n_seeds"] != 10 or config["confirmation_count"] != 48
    ):
        raise ValueError("Confirmation requires 48 independent datasets and ten seeds")
    if (
        not isinstance(config.get("runtime_fingerprint"), str)
        or not config["runtime_fingerprint"]
    ):
        raise ValueError("A frozen runtime fingerprint is required")
    if not isinstance(config.get("model"), dict) or not config["model"].get("name"):
        raise ValueError("Frozen model configuration required")
    if (
        type(config["model"].get("max_tokens")) is not int
        or config["model"]["max_tokens"] <= 0
    ):
        raise ValueError("Positive model max_tokens required")
    return config


def prepare_run(
    out: Path,
    config: dict,
    public_questions: list[dict],
    private_feedback: dict,
    legacy_claims: list[dict],
) -> dict:
    out = Path(out)
    config = _validate_config(config)
    if is_basic_learning(config) and legacy_claims:
        raise ValueError("basic_learning starts with empty knowledge and experience")
    questions = validate_public_inputs(config, public_questions, private_feedback)
    pairs = validate_pair_config(config, questions)
    discovery = [q for q in questions if q["split"] == "discovery"]
    if pairs:
        discovery = ordered_pair_questions(discovery, [p for p in pairs if p["split"] == "discovery"])
    payloads = {
        "config.json": config,
        "public_questions.json": questions,
        "private_feedback.json": private_feedback,
        "legacy_claims.json": legacy_claims,
    }
    manifest = {
        "schema_version": "kb_workflow_v1",
        "config": config,
        "source_fingerprint": source_fingerprint(),
        "inputs": {name: canonical_hash(value) for name, value in payloads.items()},
        "round_questions": {
            str(i + 1): [
                q["id"]
                for q in discovery[
                    i * config["discovery_per_round"] : (i + 1)
                    * config["discovery_per_round"]
                ]
            ]
            for i in range(config["max_rounds"])
        },
    }
    if is_basic_learning(config):
        manifest["round_questions"] = {str(i): [discovery[0]["id"]]
                                       for i in range(1, config["max_rounds"] + 1)}
        manifest["practice"] = {"kind": "same_question_practice", "question_id": discovery[0]["id"],
                                "independent_evaluation": False}
    with exclusive_lock(out / "workflow.lock"):
        if (out / "manifest.json").exists():
            old = _verify(out)
            if old != manifest:
                raise ValueError("Prepared run inputs changed")
            return old
        for name, value in payloads.items():
            path = out / name
            if path.exists() and _read(path) != value:
                raise ValueError(f"Partial preparation differs: {name}")
            _save(path, value)
        KBStore(out / "kb").initialize(legacy_claims)
        if config.get("experience_mode", "off") != "off":
            ExperienceStore(out / "experience").initialize()
        _save(out / "manifest.json", manifest)
    return manifest


def _verify(out: Path) -> dict:
    manifest = _read(out / "manifest.json")
    if manifest["source_fingerprint"] != source_fingerprint():
        raise ValueError("Workflow source changed after prepare")
    for name, expected in manifest["inputs"].items():
        if canonical_hash(_read(out / name)) != expected:
            raise ValueError(f"Frozen input integrity failure: {name}")
    if manifest["config"] != _read(out / "config.json"):
        raise ValueError("Manifest config changed")
    return manifest


def _model(config: dict):
    from tools.llm_eval.llm_client import ModelConfig

    return ModelConfig(**config["model"])


def _caller(out: Path, client, config: dict, *, final=False):
    return RoleCaller(
        out,
        client,
        _model(config),
        fingerprint=config["runtime_fingerprint"],
        max_calls=180 if final else config["max_calls_per_round"],
        max_tokens=config["max_tokens_per_round"],
        max_context=config["context_size"],
        instructions=config.get("role_instructions"),
        allow_model_alias=(is_basic_learning(config)
                           and config.get("runtime_identity", {}).get("kind") == "api_configuration"
                           and config["runtime_identity"].get("weights_verified") is False),
    )


def _memory_payload(question: dict, snapshot: dict, config: dict, *, role: str, payload: dict, mode="combined", field="experience", initial_learning=False) -> dict:
    instruction = config.get("role_instructions", {}).get(role)
    fixed = len(role_prompt(role, payload, instruction=instruction).encode())
    available = max(0, config["context_size"] - config["model"]["max_tokens"] - 256 - fixed - 1024)
    budget = min(config.get("experience_byte_budget", 6000), available)
    memory = retrieve_experience(question, snapshot, mode=mode, byte_budget=budget,
                                 repeated_practice=is_basic_learning(config) and not initial_learning, initial_learning=initial_learning)
    while (memory["examples"] or memory["lessons"]) and (
        len(role_prompt(role, {**payload, field: memory}, instruction=instruction).encode())
        + config["model"]["max_tokens"] + 256 > config["context_size"]
    ):
        budget = max(0, budget // 2)
        memory = retrieve_experience(question, snapshot, mode=mode, byte_budget=budget,
                                     repeated_practice=is_basic_learning(config) and not initial_learning, initial_learning=initial_learning)
    return memory



def _initial_experience_payload(payload: dict, config: dict) -> dict:
    initial = config.get("initial_kb")
    if not initial or initial["kind"] != "experience":
        return payload
    memory = _memory_payload(payload["question"], initial["snapshot"], config, role="solver",
                             payload=payload, mode="lessons", field="initial_experience", initial_learning=True)
    return {**payload, "initial_experience": memory}

def _consolidation_payload(snapshot: dict, episodes: list[dict], config: dict) -> dict:
    payload = {"scientific_status": "unverified", "version": snapshot["version"],
               "lessons": copy.deepcopy(snapshot["lessons"][-12:]), "episodes": copy.deepcopy(episodes),
               "omitted": {"lessons": max(0, len(snapshot["lessons"]) - 12), "episodes": 0}}
    instruction = config.get("role_instructions", {}).get("experience_curator")
    limit = min(16000, config["context_size"] - config["model"]["max_tokens"] - 256)
    while len(role_prompt("experience_curator", payload, instruction=instruction).encode()) > limit:
        field = "lessons" if payload["lessons"] else "episodes"
        if not payload[field]:
            break  # RoleCaller rejects oversized mandatory contract before submission.
        payload[field].pop()
        payload["omitted"][field] += 1
    return payload


def _knowledge(question: dict, claims: list[dict], *, legacy=False) -> list[dict]:
    result = []
    for claim in claims:
        if not claim.get("rule") or (
            not legacy
            and not (claim["status"] == "replicated_in_scope" and claim.get("enabled"))
        ):
            continue
        try:
            applicable = any(
                (
                    legacy
                    and claim["status"] == "legacy_unverified"
                    or match_validated_scope(question, claim, a["view"], b["view"])
                )
                and match_rule(claim["rule"], a["view"], b["view"]) is not None
                for a, b in itertools.combinations(question["choices"], 2)
            )
        except (ValueError, KeyError, TypeError):
            applicable = False
        if applicable:
            note = {k: claim[k] for k in ("id", "revision", "text", "rule")}
            note["status"] = claim["status"]
            if claim.get("validated_scope"):
                note["validated_scope"] = claim["validated_scope"]
            result.append(note)
    return sorted(result, key=lambda c: (c["id"], c["revision"]))[:12]


def _answer(raw: dict, question: dict, notes: list[dict]) -> dict:
    letters = [c["letter"] for c in question["choices"]]
    ranking = raw.get("ranking")
    valid = (
        not raw.get("_invalid")
        and isinstance(ranking, list)
        and all(isinstance(x, str) for x in ranking)
        and len(ranking) == len(letters)
        and set(ranking) == set(letters)
    )
    citations = raw.get("citations", [])
    malformed_citations = not isinstance(citations, list) or any(
        not isinstance(x, str) for x in citations
    )
    bad_citations = malformed_citations or any(
        x not in {c["id"] for c in notes} for x in citations
    )
    valid = valid and not malformed_citations
    return {
        "valid": bool(valid),
        "ranking": ranking if valid else [],
        "knowledge_count": len(notes),
        "citations": citations,
        "invalid_citations": bad_citations,
        "rationale": raw.get("rationale", ""),
        "raw": raw,
    }


def _dsl_packet() -> dict:
    return {
        "factors": ["layernorm", "activation", "residual", "depth", "width"],
        "predicate": ["field", "eq|ne|lt|le|gt|ge|in|nin", "value"],
        "fields": [
            "family",
            "model_type",
            "depth",
            "width",
            "activation",
            "residual",
            "ln_count",
            "ln_all",
            "opt",
            "lr",
            "budget",
            "batch_size",
            "steps",
            "input_dim",
            "rule_family",
            "target_oscillatory",
            "train_size",
        ],
        "equality_control_fields": ["arch_key", "opt_key", "loss_key"],
        "prediction_examples": [
            {"higher_better": "width"},
            {"lower_better": "ln_count"},
            {"better": ["ln_all", "eq", False], "worse": ["ln_all", "eq", True]},
        ],
        "prediction_contract": (
            "Choose exactly one prediction form and use its exact keys. "
            "higher_better predicts the candidate with the larger numeric feature value; "
            "lower_better predicts the smaller value. better/worse uses predicates "
            "to identify the predicted winning and losing candidates. "
            "The executor handles selection metric direction. Equality control fields "
            "are allowed only in same/differ lists."
        ),
        "example_rule": {
            "scope": [["family", "eq", "univariate_regression"]],
            "same": [
                "depth",
                "width",
                "activation",
                "residual",
                "opt_key",
                "budget",
                "batch_size",
            ],
            "predict": {"higher_better": "ln_count"},
        },
        "instruction": "Test one architecture factor while keeping other settings equal. "
        "Scope should be feasible on fresh data sampled from the profile; "
        "avoid exact dataset-specific numerical statistics.",
    }


def _candidate(raw: dict, packet_index: int) -> dict | None:
    if raw.get("_invalid"):
        raise ValueError("Invalid hypothesis response")
    hypothesis = raw.get("hypothesis")
    if hypothesis is None:
        return None
    if (
        not isinstance(hypothesis, dict)
        or not isinstance(hypothesis.get("text"), str)
        or not hypothesis["text"].strip()
        or len(hypothesis["text"]) > 4000
    ):
        raise ValueError("Malformed hypothesis")
    if set(hypothesis) - {
        "text",
        "rule",
        "experiment",
        "boundary",
        "competing_explanation",
        "revises",
    }:
        raise ValueError(
            "Unknown hypothesis fields; identity and status belong to coordinator"
        )
    validate_rule(hypothesis["rule"])
    experiment = hypothesis["experiment"]
    if (
        set(experiment) != {"family", "factor"}
        or experiment["factor"] not in _dsl_packet()["factors"]
    ):
        raise ValueError("Unsupported experiment proposal")
    for name in ("boundary", "competing_explanation"):
        if not isinstance(hypothesis.get(name), str) or not hypothesis[name].strip():
            raise ValueError(f"Hypothesis must state {name}")
    identity = canonical_hash({"text": hypothesis["text"], "rule": hypothesis["rule"]})[
        :16
    ]
    return {
        "id": "H" + identity,
        "revision": 1,
        **hypothesis,
        "status": "proposed",
        "enabled": False,
        "evidence_ids": [],
        "packet_index": packet_index,
    }


def _feedback_brief(feedback: dict, *, question: dict | None = None) -> dict:
    """Project stored GT into scientific facts; never recompute or truncate GT.

    Studio BakeFiles nest presentation curves/files inside ``reveal``. Neither
    that container nor arbitrary summary fields belong in a model context.
    Full evidence remains in the frozen private_feedback.json artifact.
    """
    missing = []

    def object_value(value, name):
        if not isinstance(value, dict):
            raise ValueError(f"Invalid feedback object: {name}")
        return value

    def agree(values, name):
        values = [v for v in values if v is not None]
        if values and any(v != values[0] for v in values[1:]):
            raise ValueError(f"Conflicting feedback {name}")
        return copy.deepcopy(values[0]) if values else None

    object_value(feedback, "feedback")
    reveal = object_value(feedback.get("reveal", {}), "reveal")
    significance = {}
    significance_fields = {
        "passed", "gap", "win_rate", "separation_margin", "metric",
        "selection_metric", "higher_is_better", "reason", "gap_min", "gap_max",
        "win_rate_min", "require_full_separation", "use_non_overlap",
    }
    for source in (feedback, reveal):
        for key, value in object_value(source.get("significance", {}), "significance").items():
            if key in significance_fields:
                if value is not None and type(value) not in (str, int, float, bool):
                    raise ValueError(f"Invalid significance field: {key}")
                significance[key] = agree([significance.get(key), value], f"significance.{key}")
    # Keep a scientific reason bounded, recording that full text is archived.
    if isinstance(significance.get("reason"), str) and len(significance["reason"]) > 1200:
        significance["reason"] = significance["reason"][:1200]
        missing.append("significance.reason remainder retained in artifact")

    letters = {}
    for choice in (question or {}).get("choices", []):
        letters[choice["letter"]] = choice["id"]
    ranked = reveal.get("ranked", [])
    if not isinstance(ranked, list):
        raise ValueError("Invalid feedback ranked rows")
    sources = {}

    def add(identifier, value):
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Missing feedback candidate identity")
        value = object_value(value, identifier)
        agree([identifier, value.get("candidate_id"), value.get("candidateId")], "candidate identity")
        sources.setdefault(identifier, []).append(value)

    for row in ranked:
        object_value(row, "ranked row")
        identifier, letter = row.get("candidateId"), row.get("letter")
        if not isinstance(letter, str) or not letter:
            raise ValueError("Missing feedback choice letter")
        identifier = agree([identifier, letters.get(letter)], "choice identity")
        add(identifier, row)
        letters[letter] = identifier
    for identifier, value in object_value(feedback.get("candidate_metrics", {}), "candidate_metrics").items():
        add(identifier, value)
    for letter, files in object_value(reveal.get("files", {}), "reveal.files").items():
        summary = object_value(files, "choice files").get("summary.json")
        if summary is None:
            continue
        object_value(summary, "summary.json")
        identifier = agree([letters.get(letter), summary.get("candidate_id")], "choice identity")
        if identifier is None:
            missing.append(f"reveal.files.{letter}: candidate identity unavailable")
            continue
        letters[letter] = identifier
        add(identifier, summary)

    declarations = [feedback, reveal, significance, *[v for rows in sources.values() for v in rows]]
    metric = agree([value.get(key) for value in declarations for key in ("selection_metric", "metric")], "selection_metric")
    if metric is not None and (not isinstance(metric, str) or not metric.strip()):
        raise ValueError("Invalid feedback selection_metric")
    directions = [value.get("higher_is_better") for value in declarations]
    if any(value is not None and type(value) is not bool for value in directions):
        raise ValueError("Invalid feedback higher_is_better")
    higher = agree(directions, "higher_is_better")
    correct = agree([feedback.get("correct_letter"), reveal.get("correctLetter")], "correct_letter")
    result = {"correct_letter": correct, "selection_metric": metric,
              "higher_is_better": higher, "candidate_metrics": {}}
    for field in ("selection_metric", "higher_is_better"):
        if result[field] is None:
            missing.append(field)
    if significance:
        result["significance"] = significance
    else:
        missing.append("significance")
    if ranked:
        result["recorded_ranking"] = [row["letter"] for row in ranked]

    for identifier, rows in sources.items():
        candidate = {"selection_metric": metric}
        mapped = [letter for letter, cid in letters.items() if cid == identifier]
        if len(mapped) > 1:
            raise ValueError("Conflicting feedback choice letters")
        if mapped:
            candidate["letter"] = mapped[0]
        for field in ("mean", "std", "n_seeds", "failed_seeds", "excluded"):
            keys = (field, f"{field}_{metric}") if field in {"mean", "std"} and metric else (field,)
            value = agree([row.get(key) for row in rows for key in keys], f"{identifier}.{field}")
            if value is not None:
                if field == "excluded":
                    valid = type(value) is bool
                elif field in {"n_seeds", "failed_seeds"}:
                    valid = type(value) is int and value >= 0
                else:
                    valid = type(value) in (int, float)
                if not valid:
                    raise ValueError(f"Invalid feedback {identifier}.{field}")
                candidate[field] = value
            elif field != "excluded":
                missing.append(f"candidate_metrics.{identifier}.{field}")
        seed_sets = []
        for row in rows:
            if "seed_results" not in row:
                continue
            if not isinstance(row["seed_results"], list):
                raise ValueError("Invalid feedback seed_results")
            projected = []
            for seed in row["seed_results"]:
                object_value(seed, "seed result")
                if "seed" in seed and type(seed["seed"]) is not int:
                    raise ValueError("Invalid feedback seed identifier")
                if "failed" in seed and type(seed["failed"]) is not bool:
                    raise ValueError("Invalid feedback seed failure status")
                if metric and seed.get(f"final_{metric}") is not None and type(seed[f"final_{metric}"]) not in (int, float):
                    raise ValueError("Invalid feedback final selection metric")
                fields = {"seed", "failed"} | ({f"final_{metric}"} if metric else set())
                projected.append({key: copy.deepcopy(value) for key, value in seed.items() if key in fields})
            seed_sets.append(projected)
        seeds = agree(seed_sets, f"{identifier}.seed_results")
        if seeds is not None:
            candidate["seed_results"] = seeds
            if candidate.get("n_seeds") is not None and candidate["n_seeds"] != len(seeds):
                raise ValueError(f"Conflicting feedback {identifier}.n_seeds and seed_results")
            if any("seed" not in row or "failed" not in row or (metric and f"final_{metric}" not in row) for row in seeds):
                missing.append(f"candidate_metrics.{identifier}.seed_results has incomplete rows")
        else:
            missing.append(f"candidate_metrics.{identifier}.seed_results")
        if metric is None:
            missing.append(f"candidate_metrics.{identifier}.selection_metric")
        result["candidate_metrics"][identifier] = candidate
    if not sources:
        missing.append("candidate_metrics")
    result["summary"] = {
        "schema": "discovery_feedback_v1",
        "full_evidence": "Frozen private_feedback.json for this episode.question.id",
        "policy": "Stored final statistics and all seed final outcomes only; no recomputed GT. "
                  "Full curves, files, environment and other fields remain in the artifact. "
                  "Public question and data conditions are unchanged. Unknown direction is null, never inferred.",
        "missing": missing,
    }
    return result


def _answer_brief(answer: dict) -> dict:
    brief = {
        key: answer[key]
        for key in ("valid", "ranking", "invalid_citations")
        if key in answer
    }
    brief["rationale"] = str(answer.get("rationale", ""))[:1200]
    brief["citations"] = (
        answer.get("citations", [])[:12]
        if isinstance(answer.get("citations"), list)
        else []
    )
    return brief


def _research_agenda(questions: list[dict], snapshot: dict) -> list[dict]:
    """Expose prior research after answering, independently of solver eligibility.

    The legacy_agenda packet key remains compatible with recorded first-round
    calls. Unconfirmed research enters this packet only, never solver knowledge.
    """
    families = {question["family"] for question in questions}
    research = []
    for claim in snapshot["claims"]:
        if claim["status"] in ("legacy_unverified", "retired"):
            continue
        if claim.get("experiment", {}).get("family") not in families:
            continue
        records = {
            record["id"]: record
            for record in snapshot.get("evidence", [])
            if record["claim_id"] == claim["id"]
            and record["revision"] == claim["revision"]
            and record["id"] in claim["evidence_ids"]
        }
        note = {key: claim[key] for key in ("id", "revision", "status", "enabled")}
        note["text"] = claim["text"][:800]
        note["evidence_summary"] = {
            outcome: sum(record["outcome"] == outcome for record in records.values())
            for outcome in ("support", "refute", "inconclusive")
        }
        if claim.get("validated_scope"):
            note["validated_scope"] = claim["validated_scope"]
        research.append(note)
    legacy = {
        note["id"]: {"id": note["id"], "text": note["text"][:800]}
        for question in questions
        for note in _knowledge(question, snapshot["claims"], legacy=True)
        if note["status"] == "legacy_unverified"
    }
    return (
        sorted(research, key=lambda item: item["id"])
        + sorted(legacy.values(), key=lambda item: item["id"])
    )[:3]


def _prior_research(
    out: Path, round_index: int, questions: list[dict], snapshot: dict
) -> list[dict]:
    """Retain completed research observations even when Curator chose no patch."""
    families = {question["family"] for question in questions}
    published = {claim["id"] for claim in snapshot["claims"]}
    result = []
    for previous_round in range(round_index - 1, 0, -1):
        base = out / "rounds" / str(previous_round)
        previous = read_receipt(base / "result.json")["result"]
        records = read_receipt(base / "evidence.json")["result"]
        for claim in sorted(previous["candidates"], key=lambda item: item["id"]):
            if claim["experiment"]["family"] not in families:
                continue
            relevant = {
                record["id"]: record
                for record in records
                if record["claim_id"] == claim["id"]
                and record["revision"] == claim["revision"]
            }
            counts = (
                {
                    outcome: sum(
                        record["outcome"] == outcome for record in relevant.values()
                    )
                    for outcome in ("support", "refute", "inconclusive")
                }
                if relevant
                else {}
            )
            result.append(
                {
                    "id": claim["id"],
                    "revision": claim["revision"],
                    "round": previous_round,
                    "text": claim["text"][:800],
                    "experiment": claim["experiment"],
                    "evidence": counts,
                    "published_in_kb": claim["id"] in published,
                    "revision_contract": "Only IDs in legacy_agenda may be revised. Other observations "
                    "may inform a new hypothesis with a new identity.",
                }
            )
            if relevant:
                example = describe_evidence(next(iter(relevant.values())))
                result[-1]["observed_design"] = {
                    "controlled_factor": example["controlled_factor"],
                    "fixed_sections": example["fixed_sections"],
                    "n_seeds_per_candidate": example["n_seeds_per_candidate"],
                    "dataset_params": {
                        key: value
                        for key, value in example["dataset_params"].items()
                        if key
                        in {
                            "expression",
                            "input_dim",
                            "rule_family",
                            "train_size",
                            "test_size",
                        }
                    },
                    "models": [
                        candidate["model"] for candidate in example["candidates"]
                    ],
                }
            if len(result) == 3:
                return result
    return result


def _evidence_brief(records: list[dict]) -> dict:
    by_claim = {}
    for record in records:
        row = by_claim.setdefault(
            record["claim_id"],
            {"support": 0, "refute": 0, "inconclusive": 0, "examples": []},
        )
        row[record["outcome"]] += 1
        if "design_example" not in row:
            row["design_example"] = describe_evidence(record)
        if len(row["examples"]) < 3:
            row["examples"].append(
                {k: record[k] for k in ("id", "phase", "dataset_id", "outcome")}
            )
    for claim_id, row in by_claim.items():
        relevant = [record for record in records if record["claim_id"] == claim_id]
        row["independent_datasets"] = len({record["dataset_id"] for record in relevant})
        row["training_seed_counts"] = sorted(
            {len(record["seed_ids"]) for record in relevant}
        )
    return by_claim


def canonical_backend(
    request: dict, out: Path, max_candidate_seed_runs: int, *, safe_boundary=None
) -> list[dict]:
    from .experiments import plan_experiment, execute_experiment

    plan = plan_experiment(request, out)
    if not plan.get("complete"):
        return []
    return execute_experiment(
        out / "plan.json", max_candidate_seed_runs=max_candidate_seed_runs,
        safe_boundary=safe_boundary,
    )


def _plan_sources(path: Path) -> tuple[set[str], set[str]]:
    if not path.exists():
        return set(), set()
    seal = path.parent / "plan.sha256"
    if (
        not seal.exists()
        or hashlib.sha256(path.read_bytes()).hexdigest() != seal.read_text().strip()
    ):
        raise ValueError("Experiment source inventory integrity failure")
    pairs = _read(path)["pairs"]
    return {p["dataset_id"] for p in pairs}, {p["lineage_id"] for p in pairs}


def _source_exclusions(out: Path, round_index: int) -> dict:
    questions = _read(out / "public_questions.json")
    datasets = {q["dataset_id"] for q in questions}
    lineages = {q["lineage_id"] for q in questions} | {
        f"{q['family']}:{q['dataset_id']}" for q in questions
    }
    for i in range(1, round_index):
        for path in (out / "rounds" / str(i) / "experiments").glob("*/plan.json"):
            ds, ls = _plan_sources(path)
            datasets.update(ds)
            lineages.update(ls)
    return {
        "excluded_dataset_ids": sorted(datasets),
        "excluded_lineage_ids": sorted(lineages),
    }


def _experiment(out: Path, request: dict, backend, config: dict) -> list[dict]:
    path = out / f"{request['phase']}_{canonical_hash(request['claim_id'])[:16]}"
    receipt = path / "coordinator_receipt.json"
    planned = request["count"] * 2 * request["n_seeds"]
    existing = [read_receipt(p) for p in out.glob("*/coordinator_receipt.json")]
    expected = canonical_hash(request)
    if receipt.exists():
        saved = read_receipt(receipt)
        if saved["input_hash"] != expected:
            raise ValueError("Experiment request changed")
        if saved["status"] != "complete":
            raise RuntimeError(
                "Experiment pending/uncertain; inspect reservation before resuming"
            )
        return saved["records"]
    spent = sum(r["reserved_training_runs"] for r in existing)
    if spent + planned > config["max_candidate_seed_runs"]:
        raise RuntimeError("Training budget exhausted before execution")
    record = {
        "input_hash": expected,
        "request": request,
        "status": "pending",
        "reserved_training_runs": planned,
    }
    _save(receipt, _seal(record))
    records = backend(request, path, config["max_candidate_seed_runs"] - spent)
    if not isinstance(records, list):
        raise ValueError("Experiment backend must return evidence records")
    record.update(status="complete", records=records)
    _save(receipt, _seal(record))
    return records


def _experience_operations(proposed: dict, payload: dict, snapshot: dict, episodes: list[dict],
                           *, record_conditions: bool = True) -> tuple[list[dict], list[dict]]:
    operations, rejections = [], []
    raw_ops = proposed.get("operations", [])
    if not isinstance(raw_ops, list) or len(raw_ops) > 12 or proposed.get("_invalid"):
        rejections.append({"reason": "Malformed experience operations"})
        raw_ops = []
    visible_ids = {e["id"] for e in payload["episodes"]} | {
        eid for lesson in payload["lessons"] for eid in lesson["source_episode_ids"]}
    all_episodes = snapshot["episodes"] + episodes
    for operation in raw_ops:
        try:
            if (not isinstance(operation, dict)
                    or not isinstance(operation.get("source_episode_ids"), list)
                    or any(not isinstance(eid, str) or eid not in visible_ids
                           for eid in operation["source_episode_ids"])):
                raise ValueError("Experience source not present in consolidation context")
            operation = copy.deepcopy(operation)
            if not record_conditions and operation.get("op") in {"add", "edit"}:
                operation.update(conditions=[], exceptions=[])
            apply_operations(snapshot["lessons"], all_episodes, operations + [operation])
            operations.append(operation)
        except (ValueError, TypeError, KeyError) as exc:
            rejections.append({"reason": str(exc)})
    return operations, rejections


def _finish_basic_round(out, base, config, manifest, started, answers, episodes, caller, call_role, event, check_time, retrievals, round_index):
    """Seal empirical practice without entering any scientific publication route."""
    check_time()
    payload = _consolidation_payload(started["experience"], episodes, config)
    payload.update(practice=manifest["practice"], record_conditions=config["record_conditions"])
    # Conditions are explicit optional structured fields. Both the model request
    # and accepted operations honor the user's choice; provenance is always kept.
    payload["condition_policy"] = ("Record supported conditions and exceptions; do not invent them."
                                  if config["record_conditions"] else
                                  "Return empty conditions and exceptions arrays; only save the lesson text.")
    proposed = call_role("experience_curator", payload, key="experience-consolidate", round_index=round_index)
    operations, rejections = _experience_operations(proposed, payload, started["experience"], episodes,
                                                   record_conditions=config["record_conditions"])
    check_time()
    event("experience_save", "ready")
    snapshot = ExperienceStore(out / "experience").publish(started["experience"]["version"], episodes, operations)
    for path in sorted((base / "retrievals").glob("*.json")):
        saved = read_receipt(path)["result"]
        retrievals[saved["identity"]] = saved["memory"]
    experience = {"before": started["experience"]["version"], "after": snapshot["version"],
                  "operations": snapshot["operations"], "episode_ids": [e["id"] for e in episodes],
                  "retrievals": retrievals, "rejections": rejections,
                  "episode_provenance": {e["id"]: {"question_id": e["question"]["id"], "round": e["round"],
                      "source_refs": copy.deepcopy(e["source_refs"])} for e in snapshot["episodes"]},
                  "after_snapshot": {k: snapshot[k] for k in ("version", "parent_version", "scientific_status", "lessons")}}
    result = {"round": round_index, "status": "complete", "answers": answers,
              "candidates": [], "rejections": [], "confirmation_attempted": False, "evidence_count": 0,
              "patch": {"parent_version": started["kb"]["version"], "operations": []},
              "kb_before": started["kb"]["version"], "kb_after": started["kb"]["version"],
              "usage": caller.usage(round_index), "experience": experience,
              "practice": copy.deepcopy(manifest["practice"])}
    _save(base / "result.json", _seal({"result": result}))
    event("experience_save", "complete")
    event("loop", "complete")
    return result


def run_round(
    out: Path, client, experiment_backend=None, *, round_index: int,
    stage_observer: Callable[[dict], None] | None = None,
    control_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Execute or replay a round, with optional observation and safe control.

    Control callbacks may block at ready/complete boundaries to implement pause.
    No callback runs between a model/GT reservation and its durable completion.
    Raising during active experiment control preserves its uncertain reservation;
    callers must block/resume in place rather than retry uncertain execution.
    """
    out = Path(out)

    def event(node_id, state, *, key=None, safe=True, **details):
        value = {"node_id": node_id, "state": state, "round_index": round_index,
                 "safe_boundary": safe, **details}
        if key is not None:
            value["key"] = key
        if stage_observer is not None:
            stage_observer(copy.deepcopy(value))
        if safe and control_callback is not None:
            control_callback(copy.deepcopy(value))

    with exclusive_lock(out / "workflow.lock"):
        manifest = _verify(out)
        config = manifest["config"]
        if not 1 <= round_index <= config["max_rounds"]:
            raise ValueError("Round outside configured range")
        base = out / "rounds" / str(round_index)
        completed = base / "result.json"
        if completed.exists():
            event("loop", "complete", replayed=True)
            return read_receipt(completed)["result"]
        if (out / "learning_completion.json").exists():
            raise RuntimeError("Learning is complete; no further rounds may start")
        if (
            round_index > 1
            and not (out / "rounds" / str(round_index - 1) / "result.json").exists()
        ):
            raise RuntimeError("Previous round must finish first")
        started = _step(
            base / "start.json",
            manifest,
            lambda: {
                "time": time.time(),
                "kb": KBStore(out / "kb").current(),
                "exclusions": _source_exclusions(out, round_index),
                **({"experience": ExperienceStore(out / "experience").current()}
                   if config.get("experience_mode", "off") != "off" else {}),
            },
        )

        def check_time():
            if time.time() - started["time"] > config["wall_time_seconds"]:
                raise RuntimeError("Round wall-time budget exhausted")

        check_time()
        caller = _caller(out, client, config)

        retrievals = {}
        def call_role(role, payload, *, key, round_index):
            node = ("experience_curator" if role == "experience_curator" and is_basic_learning(config)
                    else "discoverer" if role in {"pair_researcher", "experience_curator"} else role)
            details = {"role": role} if role in {"pair_researcher", "experience_curator"} else {}
            if role == "pair_researcher":
                details["step_id"] = "pair_" + payload["stage"]
            elif role == "experience_curator":
                details["step_id"] = "experience_consolidate"
            elif role == "solver" and "provisional_learning" in payload:
                details["step_id"] = "pair_transfer"
            if role == "solver" and is_basic_learning(config):
                payload = _initial_experience_payload(payload, config)
                if "initial_experience" in payload:
                    identity = f"{role}-initial:{key}"
                    retrieval_record = {"identity": identity, "memory": payload["initial_experience"]}
                    _step(base / "retrievals" / f"{canonical_hash(identity)}.json", retrieval_record,
                          lambda r=retrieval_record: r)
                    retrievals[identity] = copy.deepcopy(payload["initial_experience"])
            if ("experience" in started and role in {"solver", "discoverer", "pair_researcher"}
                    and (not is_basic_learning(config) or config["use_previous_experience"])):
                target = payload.get("question") or payload.get("original", {}).get("question")
                if target is None and payload.get("episodes"):
                    target = payload["episodes"][0]["question"]
                if target is not None:
                    memory_config = {**config, "experience_byte_budget": max(0, config.get("experience_byte_budget", 6000)
                                    - payload.get("initial_experience", {}).get("content_bytes", 0))}
                    memory = _memory_payload(target, started["experience"], memory_config, role=role, payload=payload)
                    payload = {**payload, "experience": memory}
                    identity = f"{role}:{key}"
                    retrieval_record = {"identity": identity, "memory": memory}
                    _step(base / "retrievals" / f"{canonical_hash(identity)}.json", retrieval_record,
                          lambda r=retrieval_record: r)
                    retrievals[identity] = copy.deepcopy(memory)
            event(node, "ready", key=key, **details)
            event(node, "running", key=key, safe=False, **details)
            result = caller.call(role, payload, key=key, round_index=round_index)
            # RoleCaller has sealed its response before this safe boundary.
            event(node, "complete", key=key, **details)
            return result

        event("input", "ready")
        questions_by_id = {q["id"]: q for q in _read(out / "public_questions.json")}
        questions = [
            questions_by_id[qid]
            for qid in manifest["round_questions"][str(round_index)]
        ]
        event("input", "complete")
        answers = {}
        for question in questions:
            check_time()
            claims = started["kb"]["claims"]
            initial = config.get("initial_kb")
            if initial and initial["kind"] == "formal":
                claims = initial["snapshot"]["claims"] + claims
            notes = _knowledge(question, claims)
            raw = call_role(
                "solver",
                {"question": question, "knowledge": notes},
                key=question["id"],
                round_index=round_index,
            )
            event("commit", "ready", key=question["id"])
            answers[question["id"]] = _step(
                base / "answers" / f"{canonical_hash(question['id'])}.json",
                raw,
                lambda r=raw, q=question, n=notes: _answer(r, q, n),
            )
            event("commit", "complete", key=question["id"])
        # Every answer is durably saved before private feedback enters any role.
        event("reveal", "ready")
        feedback = _read(out / "private_feedback.json")
        episodes = []
        if "experience" in started:
            for question in questions:
                answer_path = base / "answers" / f"{canonical_hash(question['id'])}.json"
                feedback_path = base / "revealed" / f"{canonical_hash(question['id'])}.json"
                revealed = {"question_id": question["id"], "feedback": feedback[question["id"]]}
                _step(feedback_path, revealed, lambda r=revealed: r)
                episodes.append(build_episode(out, round_index=round_index, question=question,
                                              answer_path=answer_path, feedback_path=feedback_path))
        event("reveal", "complete")
        if is_basic_learning(config):
            return _finish_basic_round(out, base, config, manifest, started, answers, episodes, caller, call_role, event, check_time,
                                       retrievals, round_index)
        protocol = config.get("learning_protocol", "single")
        paired = protocol != "single"
        round_pairs = []
        if paired:
            selected = {q["id"] for q in questions}
            round_pairs = [
                p for p in config["pair_manifest"]
                if p["split"] == "discovery"
                and {q["id"] for q in pair_members(p, questions_by_id).values()} <= selected
            ]
            position = {q["id"]: i for i, q in enumerate(questions)}
            round_pairs.sort(key=lambda p: min(position[q["id"]] for q in pair_members(p, questions_by_id).values()))
            packets = [[pair_members(p, questions_by_id)[role] for role in ("original", "counterfactual")]
                       for p in round_pairs]
        else:
            packets = [questions[i:i + config["packet_size"]]
                       for i in range(0, len(questions), config["packet_size"])][:4]
        candidates = []
        rejections = []
        learning_traces = []
        proposed_ids = set()
        for i, packet in enumerate(packets):
            check_time()
            if paired:
                pair = round_pairs[i]
                original, counterfactual = packet
                context = {"dsl": _dsl_packet(),
                           "legacy_agenda": _research_agenda([original], started["kb"])}
                trace_inputs = {
                    "pair": pair, "protocol": protocol,
                    "original": original, "counterfactual": counterfactual,
                    "answers": {q["id"]: _answer_brief(answers[q["id"]]) for q in packet},
                    "feedback": {q["id"]: _feedback_brief(feedback[q["id"]], question=q) for q in packet},
                    "knowledge": _knowledge(counterfactual, started["kb"]["claims"]),
                    "context": context,
                }
                trace = _step(
                    base / "learning" / f"{pair['pair_key']}.json", trace_inputs,
                    lambda: research_pair(
                        **trace_inputs,
                        call=lambda role, payload, *, key: call_role(role, payload, key=key, round_index=round_index),
                        answer=_answer, check_time=check_time,
                    ),
                )
                learning_traces.append(trace)
                raw = trace["revision" if protocol == "paired_progressive" else "contrastive"]
            else:
                data = {
                    "episodes": [
                        {
                            "question": q,
                            "answer": _answer_brief(answers[q["id"]]),
                            "feedback": _feedback_brief(feedback[q["id"]], question=q),
                        }
                        for q in packet
                    ],
                    "dsl": _dsl_packet(),
                    "legacy_agenda": _research_agenda(packet, started["kb"]),
                }
                prior_research = _prior_research(out, round_index, packet, started["kb"])
                if prior_research:
                    data["prior_research"] = prior_research
                    # Drop older optional research first if the fixed context is
                    # tight. Current questions/answers/feedback remain intact.
                    while data["prior_research"] and (
                        len(role_prompt("discoverer", data, instruction=config.get("role_instructions", {}).get("discoverer")).encode())
                        + config["model"]["max_tokens"]
                        + 256
                        > config["context_size"]
                    ):
                        data["prior_research"].pop()
                    if not data["prior_research"]:
                        data.pop("prior_research")
                raw = call_role(
                    "discoverer", data, key=f"packet-{i}", round_index=round_index
                )
            try:
                claim = _candidate(raw, i)
                if claim is None:
                    continue
                if claim.get("revises"):
                    parent = next(
                        (
                            c
                            for c in started["kb"]["claims"]
                            if c["id"] == claim["revises"]
                        ),
                        None,
                    )
                    if parent is None:
                        raise ValueError("Unknown revised claim")
                    claim.update(
                        id=parent["id"],
                        revision=parent["revision"] + 1,
                        parent_revision=parent["revision"],
                    )
                old = next(
                    (c for c in started["kb"]["claims"] if c["id"] == claim["id"]), None
                )
                if old is not None and not claim.get("revises"):
                    rejections.append(
                        {
                            "packet": i,
                            "reason": "Duplicate existing hypothesis; select another question",
                        }
                    )
                    continue
                if claim["id"] in proposed_ids:
                    rejections.append(
                        {
                            "packet": i,
                            "id": claim["id"],
                            "reason": "A proposal for this claim was already reviewed in this round",
                        }
                    )
                    continue
                proposed_ids.add(claim["id"])
            except (ValueError, KeyError, TypeError) as exc:
                rejections.append({"packet": i, "reason": str(exc)})
                continue
            check_time()
            critique = call_role(
                "skeptic",
                {
                    "hypothesis": claim,
                    "dsl": _dsl_packet(),
                    "budget": config["max_candidate_seed_runs"],
                },
                key=claim["id"],
                round_index=round_index,
            )
            if (
                critique.get("accept") is not True
                or critique.get("experiment") != claim["experiment"]
            ):
                rejections.append(
                    {
                        "id": claim["id"],
                        "reason": critique.get("reason", "Invalid/revised experiment"),
                    }
                )
                continue
            candidates.append(claim)
        # Public, deterministic tie break; never choose experiments on their GT.
        candidates = sorted(
            {c["id"]: c for c in candidates}.values(), key=lambda c: c["id"]
        )[:3]
        records = []
        def canonical_control(value):
            detail = {k: v for k, v in value.items() if k not in {"node_id", "state", "safe_boundary", "round_index"}}
            event(value["node_id"], value["state"], **detail)

        if experiment_backend is None:
            def backend(request, path, budget):
                return canonical_backend(request, path, budget, safe_boundary=canonical_control)
        else:
            backend = experiment_backend
        excluded = copy.deepcopy(started["exclusions"])
        for i, claim in enumerate(candidates):
            check_time()
            request = {
                **claim["experiment"],
                **copy.deepcopy(excluded),
                "claim_id": claim["id"],
                "revision": claim["revision"],
                "rule": claim["rule"],
                "phase": "exploration",
                "profile": config["profile"],
                "count": config["exploration_count"],
                "n_seeds": config["n_seeds"],
                "seed_start": config["seed_start"]
                + round_index * 1_000_000
                + i * 10_000,
            }
            event("experiment", "ready", key=claim["id"])
            event("experiment", "running", key=claim["id"], safe=False)
            records.extend(_experiment(base / "experiments", request, backend, config))
            event("experiment", "complete", key=claim["id"])
            path = (
                base
                / "experiments"
                / f"exploration_{canonical_hash(claim['id'])[:16]}"
                / "plan.json"
            )
            ds, ls = _plan_sources(path)
            excluded = {
                "excluded_dataset_ids": sorted(
                    set(excluded["excluded_dataset_ids"]) | ds
                ),
                "excluded_lineage_ids": sorted(
                    set(excluded["excluded_lineage_ids"]) | ls
                ),
            }
            claim["status"] = "exploring"
        confirmed = False
        if candidates and config["enable_confirmation"]:
            check_time()
            claim = candidates[0]  # Fixed before observing confirmation outcomes.
            request = {
                **claim["experiment"],
                **copy.deepcopy(excluded),
                "claim_id": claim["id"],
                "revision": claim["revision"],
                "rule": claim["rule"],
                "phase": "confirmation",
                "profile": config["profile"],
                "count": 48,
                "n_seeds": 10,
                "seed_start": config["seed_start"] + round_index * 1_000_000 + 500_000,
            }
            event("confirmation", "ready", key=claim["id"])
            event("confirmation", "running", key=claim["id"], safe=False)
            records.extend(_experiment(base / "experiments", request, backend, config))
            event("confirmation", "complete", key=claim["id"])
            confirmed = True
        for claim in candidates:
            relevant = [
                r
                for r in records
                if r["claim_id"] == claim["id"] and r["revision"] == claim["revision"]
            ]
            claim["evidence_ids"] = sorted({r["id"] for r in relevant})
            confirmation = [r for r in relevant if r["phase"] == "confirmation"]
            summary = summarize_confirmation(confirmation)
            if summary["passed"]:
                claim["status"] = "replicated_in_scope"
        _step(base / "evidence.json", records, lambda: records)
        check_time()
        analysis = call_role(
            "analyst",
            {
                "candidates": candidates,
                "evidence": _evidence_brief(records),
                "rejections": rejections,
            },
            key="evidence",
            round_index=round_index,
        )
        experience_prepared = False
        if "experience" in started:
            check_time()
            empirical_payload = _consolidation_payload(started["experience"], episodes, config)
            proposed = call_role("experience_curator", empirical_payload,
                                 key="experience-consolidate", round_index=round_index)
            empirical_ops, empirical_rejections = _experience_operations(
                proposed, empirical_payload, started["experience"], episodes)
            experience_prepared = True

        # Curator sees bounded summaries. Paths and GT remain research evidence,
        # never a shell capability or an instruction to execute arbitrary code.
        check_time()
        decisions = call_role(
            "curator",
            {
                "candidates": candidates,
                "analysis": analysis,
                "existing": [
                    {"id": c["id"], "status": c["status"], "text": c["text"]}
                    for c in started["kb"]["claims"]
                    if c["id"] in {p.get("revises") for p in candidates}
                    or c["status"] != "legacy_unverified"
                ][:12],
            },
            key="patch",
            round_index=round_index,
        )
        by_id = {c["id"]: c for c in candidates}
        operations = []
        seen = set()
        if isinstance(decisions.get("decisions"), list):
            for decision in decisions["decisions"]:
                if (
                    not isinstance(decision, dict)
                    or not isinstance(decision.get("id"), str)
                    or decision["id"] in seen
                    or not isinstance(decision.get("reason"), str)
                    or not decision["reason"].strip()
                ):
                    continue
                identifier = decision.get("id")
                seen.add(identifier)
                if decision.get("action") == "upsert" and identifier in by_id:
                    claim = copy.deepcopy(by_id[identifier])
                    claim["enabled"] = bool(
                        decision.get("enabled") is True
                        and claim["status"] == "replicated_in_scope"
                    )
                    operations.append(
                        {
                            "op": "upsert",
                            "claim": claim,
                            "reason": decision.get("reason", "evidence review"),
                        }
                    )
                elif decision.get("action") == "retire" and identifier in {
                    c["id"] for c in started["kb"]["claims"]
                }:
                    operations.append(
                        {
                            "op": "retire",
                            "id": identifier,
                            "reason": decision.get("reason", "retired"),
                        }
                    )
        patch = {"parent_version": started["kb"]["version"], "operations": operations}
        _step(base / "patch.json", patch, lambda: patch)
        check_time()
        store = KBStore(out / "kb")
        # Store publication is idempotent by parent/patch identity (including a
        # crash between CURRENT update and coordinator's final result write).
        event("publish", "ready")
        published = store.apply_patch(patch, records)
        result = {
            "round": round_index,
            "status": "complete",
            "answers": answers,
            "candidates": candidates,
            "rejections": rejections,
            "confirmation_attempted": confirmed,
            "evidence_count": len(records),
            "analysis": analysis,
            "patch": patch,
            "kb_before": started["kb"]["version"],
            "kb_after": published["version"],
            "usage": caller.usage(round_index),
        }
        if paired:
            result["learning_traces"] = learning_traces
        if experience_prepared:
            empirical = ExperienceStore(out / "experience").publish(
                started["experience"]["version"], episodes, empirical_ops)
            # A saved pair trace can replay without re-entering its role callbacks.
            # Restore every earlier injection from durable receipts after such replay.
            for path in sorted((base / "retrievals").glob("*.json")):
                saved = read_receipt(path)["result"]
                retrievals[saved["identity"]] = saved["memory"]
            experience_result = {
                "before": started["experience"]["version"], "after": empirical["version"],
                "operations": empirical["operations"], "episode_ids": [e["id"] for e in episodes],
                "retrievals": retrievals, "rejections": empirical_rejections,
                "episode_provenance": {e["id"]: {"question_id": e["question"]["id"],
                    "round": e["round"], "source_refs": copy.deepcopy(e["source_refs"])}
                    for e in empirical["episodes"]},
                "after_snapshot": {k: empirical[k] for k in ("version", "parent_version", "scientific_status", "lessons")},
            }
            result["experience"] = experience_result
        _save(completed, _seal({"result": result}))
        event("publish", "complete")
        event("loop", "complete")
        return result


def status(out: Path) -> dict:
    out = Path(out)
    manifest = _verify(out)
    results = [
        read_receipt(p)["result"]
        for p in sorted((out / "rounds").glob("*/result.json"))
    ]
    snapshot = KBStore(out / "kb").current()
    return {
        "completed_rounds": len(results),
        "max_rounds": manifest["config"]["max_rounds"],
        "kb_version": snapshot["version"],
        "claims": len(snapshot["claims"]),
        "enabled": sum(bool(c["enabled"]) for c in snapshot["claims"]),
        "rounds": [
            {
                k: r[k]
                for k in ("round", "evidence_count", "confirmation_attempted", "usage")
            }
            for r in results
        ],
    }


def evaluate_run(
    out: Path, client, *, phase: str,
    stage_observer: Callable[[dict], None] | None = None,
    control_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Evaluate frozen arms with control only outside active model calls.

    A complete call event follows RoleCaller's durable complete receipt. Pending
    or uncertain calls retain their reservation and cannot be replayed as retries.
    As in run_round, pause callbacks should block in place until resumed.
    """
    out = Path(out)
    if phase not in ("development", "final"):
        raise ValueError("Unknown evaluation phase")
    with exclusive_lock(out / "workflow.lock"):
        manifest = _verify(out)
        config = manifest["config"]
        state = status(out)
        index = 1000 if phase == "final" else state["completed_rounds"]

        def event(call_state, *, safe=True, **details):
            value = {"node_id": "evaluate", "state": call_state, "phase": phase,
                     "round_index": index, "safe_boundary": safe, **details}
            if stage_observer is not None:
                stage_observer(copy.deepcopy(value))
            if safe and control_callback is not None:
                control_callback(copy.deepcopy(value))

        if not state["completed_rounds"]:
            raise RuntimeError("A round must finish before evaluation")
        if phase == "final":
            from .completion import require_learning_complete
            require_learning_complete(out, manifest, state["completed_rounds"])
        snapshot = KBStore(out / "kb").current()
        empirical_snapshot = (ExperienceStore(out / "experience").current()
                              if config.get("experience_mode", "off") != "off" else None)
        development_identity = snapshot["version"]
        if empirical_snapshot is not None:
            development_identity += "_" + empirical_snapshot["version"]
        base = (
            out
            / "evals"
            / phase
            / ("locked" if phase == "final" else development_identity)
        )
        binding = {
            "kb_version": snapshot["version"],
            "manifest": manifest,
            "phase": phase,
        }
        if config.get("experience_mode", "off") != "off":
            # Replay retains the frozen memory even if a later development round publishes.
            if (base / "start.json").exists():
                binding["experience"] = read_receipt(base / "start.json")["result"]["experience"]
            else:
                binding["experience"] = empirical_snapshot
        started = _step(base / "start.json", binding, lambda: binding)
        if (base / "result.json").exists():
            result = read_receipt(base / "result.json")["result"]
            event("complete", replayed=True)
            return result
        questions = [
            q for q in _read(out / "public_questions.json") if q["split"] == phase
        ]
        if not questions:
            raise ValueError(f"No {phase} questions in prepared run")
        caller = _caller(out, client, config, final=(phase == "final"))
        initial = read_receipt(out / "rounds" / "1" / "start.json")["result"]["kb"]
        arms = ["clean", "initial", "current"]
        if "experience" in started:
            arms.extend(["experience_examples", "experience_lessons", "experience_combined"])
        outputs = {arm: {} for arm in arms}
        retrievals = {}
        for arm in outputs:
            for q in questions:
                claims = (
                    []
                    if arm == "clean"
                    else (initial["claims"] if arm == "initial" else snapshot["claims"])
                )
                notes = _knowledge(q, claims, legacy=(arm == "initial"))
                key = f"eval-{phase}-{snapshot['version']}-{arm}-{q['id']}"
                details = {"key": key, "role": "solver", "arm": arm, "question_id": q["id"]}
                event("ready", **details)
                event("running", safe=False, **details)
                payload = {"question": q, "knowledge": notes}
                if arm.startswith("experience_"):
                    memory = _memory_payload(q, started["experience"], config, role="solver", payload=payload,
                                             mode=arm.removeprefix("experience_"))
                    payload["experience"] = memory
                    retrievals[f"{arm}:{q['id']}"] = memory
                response = caller.call(
                    "solver",
                    payload,
                    key=key,
                    round_index=index,
                )
                outputs[arm][q["id"]] = _answer(response, q, notes)
                if arm.startswith("experience_"):
                    output = outputs[arm][q["id"]]
                    output["formal_knowledge_count"] = len(notes)
                    output["experience_count"] = len(memory["examples"]) + len(memory["lessons"])
                    output["knowledge_count"] += output["experience_count"]
                # RoleCaller seals completion before control can pause this arm.
                event("complete", **details)
        # Labels are accessed for scoring only after every evaluation prediction
        # has a durable model receipt. Evaluation never changes the KB.
        from .evaluation import score_evaluation

        event("ready", operation="scoring")
        private = _read(out / "private_feedback.json")
        scores = score_evaluation(questions, outputs, private, pair_manifest=config.get("pair_manifest"))
        result = {
            "phase": phase,
            "binding": started,
            "scores": scores,
            "answers": outputs,
            "kb_unchanged": KBStore(out / "kb").current()["version"]
            == snapshot["version"],
        }
        if "experience" in started:
            result["retrievals"] = retrievals
            result["experience_unchanged"] = ExperienceStore(out / "experience").current()["version"] == started["experience"]["version"]
            result["usage"] = caller.usage(index)
        _save(base / "result.json", _seal({"result": result}))
        event("complete", operation="scoring")
        return result
