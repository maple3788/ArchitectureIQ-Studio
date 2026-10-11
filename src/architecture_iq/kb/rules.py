"""A bounded, public-spec-only rule language with three-valued predicates."""
from __future__ import annotations

import ast
from functools import lru_cache
import importlib.util
import json
import math
from pathlib import Path
import re
from typing import Any

# Structural keys may only compare two choices for equality. They cannot select
# a particular architecture/configuration by its serialized identity.
PUBLIC_FIELDS = frozenset("""family task metric input_dim rule_family n_active_features spiral_turns
vocab_size context_length train_size target_abs_mean target_std target_oscillatory
budget batch_size steps model_type params depth width residual activation smooth_activation
ln_count ln_any ln_all num_layers d_model d_ff num_heads layer_residual opt adaptive
sign_normalized lr weight_decay momentum beta1 beta2 eff_lr disp per_step""".split())
CONTROL_FIELDS = PUBLIC_FIELDS | {"arch_key", "opt_key", "loss_key"}
OPS = frozenset(("eq", "ne", "lt", "le", "gt", "ge", "in", "nin"))


@lru_cache(maxsize=None)
def _legacy_module(name: str):
    """Load the repository's existing helpers without changing the import path."""
    path = Path(__file__).resolve().parents[3] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_architecture_iq_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _literal(value: Any) -> bool:
    return type(value) is bool or (_number(value) if type(value) in (int, float) else
                                  type(value) is str and len(value) <= 256)


def _field(value: Any, *, control: bool = False) -> None:
    if not isinstance(value, str) or value not in (CONTROL_FIELDS if control else PUBLIC_FIELDS):
        raise ValueError(f"Field is not an allowed public selector: {value!r}")


def _predicate(value: Any, depth: int = 0, budget: list[int] | None = None) -> None:
    budget = budget if budget is not None else [128]
    budget[0] -= 1
    if depth > 12 or budget[0] < 0:
        raise ValueError("Predicate nesting/size limit exceeded")
    if value is None:
        return
    if isinstance(value, list):
        if not value:
            raise ValueError("Empty predicates are not allowed")
        if isinstance(value[0], str):
            if len(value) != 3:
                raise ValueError("A predicate leaf needs [field, operator, literal]")
            field, op, literal = value
            _field(field)
            if not isinstance(op, str) or op not in OPS:
                raise ValueError("Unknown predicate operator")
            if op in ("in", "nin"):
                if not isinstance(literal, list) or not 1 <= len(literal) <= 64 or not all(map(_literal, literal)):
                    raise ValueError("Membership requires a bounded list of finite scalar literals")
            elif not _literal(literal):
                raise ValueError("Predicate literals must be finite scalars")
            if op in ("lt", "le", "gt", "ge") and not _number(literal):
                raise ValueError("Ordered comparison requires a finite number")
        else:
            if len(value) > 64:
                raise ValueError("Too many predicates")
            for child in value:
                if child is None:
                    raise ValueError("Conjunction requires predicates")
                _predicate(child, depth + 1, budget)
    elif isinstance(value, dict) and len(value) == 1:
        op, children = next(iter(value.items()))
        if op == "not":
            if children is None:
                raise ValueError("not requires a predicate")
            _predicate(children, depth + 1, budget)
        elif op in ("all", "any") and isinstance(children, list) and 1 <= len(children) <= 64:
            for child in children:
                if child is None:
                    raise ValueError("Boolean groups require predicates")
                _predicate(child, depth + 1, budget)
        else:
            raise ValueError("Invalid compound predicate")
    else:
        raise ValueError("Invalid predicate")


def validate_rule(rule: dict) -> None:
    """Reject hidden selectors, unknown keys, ambiguous modes and unsafe shapes."""
    if not isinstance(rule, dict) or not set(rule) <= {"scope", "same", "differ", "predict", "max_param_ratio"} or "predict" not in rule:
        raise ValueError("Rule requires predict and only scope/same/differ/predict/max_param_ratio keys")
    if "max_param_ratio" in rule and (not _number(rule["max_param_ratio"]) or rule["max_param_ratio"] < 1):
        raise ValueError("max_param_ratio must be finite and at least one")
    budget = [128]
    _predicate(rule.get("scope"), budget=budget)
    for key in ("same", "differ"):
        fields = rule.get(key, [])
        if not isinstance(fields, list) or len(fields) > 64:
            raise ValueError(f"{key} must be a bounded list")
        for field in fields:
            _field(field, control=True)
        if len(set(fields)) != len(fields):
            raise ValueError(f"Duplicate {key} field")
    if set(rule.get("same", [])) & set(rule.get("differ", [])):
        raise ValueError("A field cannot be both same and different")
    pred = rule["predict"]
    if not isinstance(pred, dict):
        raise ValueError("Prediction must be an object")
    if set(pred) == {"better", "worse"}:
        if pred["better"] is None or pred["worse"] is None:
            raise ValueError("better and worse require predicates")
        for key in ("better", "worse"):
            _predicate(pred[key], budget=budget)
    elif "dominates" in pred and set(pred) <= {"dominates", "winner", "loser"}:
        axes = pred["dominates"]
        if not isinstance(axes, list) or not 1 <= len(axes) <= 16:
            raise ValueError("dominates requires bounded axes")
        seen = set()
        for axis in axes:
            if not isinstance(axis, list) or len(axis) not in (2, 3):
                raise ValueError("Invalid dominance axis")
            _field(axis[0])
            if axis[0] in seen or axis[1] not in ("higher", "lower"):
                raise ValueError("Invalid/duplicate dominance direction")
            seen.add(axis[0])
            if len(axis) == 3 and (not _number(axis[2]) or axis[2] < 1):
                raise ValueError("min_ratio must be finite and at least one")
        for key in ("winner", "loser"):
            _predicate(pred.get(key), budget=budget)
    else:
        modes = set(pred) & {"higher_better", "lower_better"}
        if len(modes) != 1 or not set(pred) <= modes | {"min_ratio"}:
            raise ValueError("Prediction needs exactly one supported mode")
        _field(pred[next(iter(modes))])
        ratio = pred.get("min_ratio", 1)
        if not _number(ratio) or ratio < 1:
            raise ValueError("min_ratio must be finite and at least one")


def _all(values: list[bool | None]) -> bool | None:
    return False if False in values else (None if None in values else True)


def _any(values: list[bool | None]) -> bool | None:
    return True if True in values else (None if None in values else False)


def _equal(a: Any, b: Any) -> bool:
    return a == b and (type(a) is type(b) or (_number(a) and _number(b)))


def _holds(pred: Any, view: dict) -> bool | None:
    if pred is None:
        return True
    if isinstance(pred, dict):
        op, child = next(iter(pred.items()))
        if op == "not":
            result = _holds(child, view)
            return None if result is None else not result
        return (_all if op == "all" else _any)([_holds(p, view) for p in child])
    if not isinstance(pred[0], str):
        return _all([_holds(p, view) for p in pred])
    field, op, value = pred
    actual = view.get(field)
    if actual is None or not _literal(actual):
        return None
    if op in ("eq", "ne"):
        result = _equal(actual, value)
        return result if op == "eq" else not result
    if op in ("in", "nin"):
        result = any(_equal(actual, v) for v in value)
        return result if op == "in" else not result
    if not _number(actual):
        return None
    if math.isclose(actual, value, rel_tol=1e-9):
        return op in ("le", "ge")
    return actual < value if op in ("lt", "le") else actual > value


def _dominates(pred: dict, winner: dict, loser: dict) -> bool:
    if _holds(pred.get("winner"), winner) is not True or _holds(pred.get("loser"), loser) is not True:
        return False
    strict = False
    for axis in pred["dominates"]:
        a, b = winner.get(axis[0]), loser.get(axis[0])
        if not _number(a) or not _number(b):
            return False
        better, worse = (a, b) if axis[1] == "higher" else (b, a)
        if better < worse:
            return False
        if len(axis) == 3 and (worse <= 0 or better / worse < axis[2]):
            return False
        strict |= better > worse
    return strict


def match_rule(rule: dict, a: dict, b: dict) -> int | None:
    """Return the predicted choice index, or abstain on missing/ambiguous data."""
    validate_rule(rule)
    if _holds(rule.get("scope"), a) is not True or _holds(rule.get("scope"), b) is not True:
        return None
    if "max_param_ratio" in rule:
        params_a, params_b = a.get("params"), b.get("params")
        if not _number(params_a) or not _number(params_b) or params_a <= 0 or params_b <= 0:
            return None
        if max(params_a, params_b) / min(params_a, params_b) > rule["max_param_ratio"]:
            return None
    for key in ("same", "differ"):
        for field in rule.get(key, []):
            va, vb = a.get(field), b.get(field)
            if va is None or vb is None or (type(va) in (int, float) and not _number(va)) or (type(vb) in (int, float) and not _number(vb)):
                return None
            if _equal(va, vb) != (key == "same"):
                return None
    pred = rule["predict"]
    if "better" in pred or "dominates" in pred:
        if "better" in pred:
            ab = _holds(pred["better"], a) is True and _holds(pred["worse"], b) is True
            ba = _holds(pred["better"], b) is True and _holds(pred["worse"], a) is True
        else:
            ab, ba = _dominates(pred, a, b), _dominates(pred, b, a)
        return None if ab == ba else (0 if ab else 1)
    key = "higher_better" if "higher_better" in pred else "lower_better"
    va, vb = a.get(pred[key]), b.get(pred[key])
    if not _number(va) or not _number(vb) or va == vb:
        return None
    ratio = pred.get("min_ratio", 1)
    if ratio > 1 and (min(va, vb) <= 0 or max(va, vb) / min(va, vb) < ratio):
        return None
    return 0 if (va > vb) == (key == "higher_better") else 1


def match_rule_for_injection(rule_record: dict, a_view: dict, b_view: dict) -> int | None:
    """Match eligible source-reported knowledge for model context, never execution.

    Source ``inject_same`` changes only the context applicability gate. It does
    not loosen the authored rule used by deterministic research evaluation, nor
    turn a source-reported status into a Studio confirmation receipt.
    """
    metadata = rule_record.get("metadata")
    if (rule_record.get("state") != "active" or not isinstance(metadata, dict)
            or metadata.get("validation_origin") != "source_reported"
            or metadata.get("validity_status") != "replicated_in_scope"
            or metadata.get("role") in {"exploratory", "descriptive"}
            or ("inject" in metadata and metadata["inject"] is not True)):
        return None
    rule = rule_record["rule"]
    validate_rule(rule)
    if "inject_same" in metadata:
        rule = {**rule, "same": metadata["inject_same"]}
    return match_rule(rule, a_view, b_view)


def _validate_expression(expression: str) -> None:
    """The legacy feature helper evaluates expressions; permit arithmetic only."""
    if not isinstance(expression, str) or len(expression) > 4096:
        raise ValueError("Invalid public target expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Invalid public target expression") from exc
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
               ast.Pow, ast.USub, ast.UAdd, ast.Load, ast.Call, ast.Name, ast.Constant)
    functions = {"sin", "cos", "tanh", "exp", "log", "sqrt", "abs"}
    nodes = list(ast.walk(tree))
    if len(nodes) > 256:
        raise ValueError("Target expression is too large")
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError("Unsafe target expression")
        if isinstance(node, ast.Name) and node.id not in functions | {"pi"} and not re.fullmatch(r"x\d*", node.id):
            raise ValueError("Unsafe target expression name")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in functions or len(node.args) != 1 or node.keywords):
            raise ValueError("Unsafe target expression call")
        if isinstance(node, ast.Constant) and not _number(node.value):
            raise ValueError("Invalid target expression literal")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if not isinstance(exponent, ast.Constant) or not _number(exponent.value) or abs(exponent.value) > 10:
                raise ValueError("Unsafe target expression exponent")


def public_views(dataset_spec: dict, candidate_specs: list[dict]) -> list[dict]:
    """Derive features using the existing spec-only helper, never GT artifacts."""
    expression = dataset_spec.get("params", {}).get("expression")
    if expression:
        _validate_expression(expression)
    legacy = _legacy_module("kb_claim_pairwise_eval")
    dataset = legacy.dataset_view(dataset_spec)
    views = []
    for spec in candidate_specs:
        view = {k: v for k, v in legacy.candidate_view(spec, dataset).items() if k in CONTROL_FIELDS}
        view["loss_key"] = (json.dumps(spec["loss"], sort_keys=True, separators=(",", ":"), allow_nan=False)
                            if isinstance(spec.get("loss"), dict) else None)
        views.append(view)
    return views


def _structural_object(value: Any) -> dict | None:
    """Read a bounded semantic fingerprint, rejecting malformed/nonfinite JSON."""
    if not isinstance(value, str) or not value or len(value) > 65536:
        return None
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            return None
        json.dumps(result, allow_nan=False)
        return result
    except (ValueError, TypeError, RecursionError, OverflowError):
        return None


def _mlp_structure(model: dict | None) -> bool:
    if not isinstance(model, dict) or model.get("type") != "mlp":
        return False
    if any(type(model.get(key)) is not int or model[key] <= 0 for key in ("width", "depth")):
        return False
    if not isinstance(model.get("activation"), str) or not model["activation"] or type(model.get("residual")) is not bool:
        return False
    norms = model.get("layer_norm")
    return (isinstance(norms, list) and len(norms) == model["depth"]
            and all(type(norm) is bool for norm in norms))


def _same_intervention_controls(a: dict, b: dict, factor: str) -> bool:
    if not _mlp_structure(a) or not _mlp_structure(b):
        return False
    removed = {"layernorm": {"layer_norm"}, "activation": {"activation", "leaky_relu_slope"},
               "residual": {"residual"}, "width": {"width"}, "depth": {"depth", "layer_norm"}}
    if factor not in removed:
        return False
    changed_key = "layer_norm" if factor == "layernorm" else factor
    if a[changed_key] == b[changed_key]:
        return False
    if factor in ("depth", "layernorm"):
        # factor_variants tests only uniform LayerNorm. Depth keeps its on/off
        # mode fixed while changing the required list length.
        modes = []
        for model in (a, b):
            norms = model["layer_norm"]
            if any(norm != norms[0] for norm in norms):
                return False
            modes.append(norms[0])
        if factor == "depth" and modes[0] != modes[1]:
            return False
    projections = [{key: value for key, value in model.items() if key not in removed[factor]} for model in (a, b)]
    return json.dumps(projections[0], sort_keys=True) == json.dumps(projections[1], sort_keys=True)


def match_validated_scope(question: dict, claim: dict, a_view: dict, b_view: dict) -> bool:
    """Gate a confirmed rule by its verified sampling distribution and controls.

    This deliberately does not evaluate the authored rule or special-case legacy
    status. The coordinator combines this gate with ``match_rule`` and owns any
    explicitly unverified legacy comparison arm. Missing metadata abstains.
    """
    if any(not isinstance(value, dict) for value in (question, claim, a_view, b_view)):
        return False
    envelope = claim.get("validated_scope")
    if not isinstance(envelope, dict) or envelope.get("pair_sampling") != "uniform_applicable_pairs_from_factor_variants":
        return False
    family, profile_hash = envelope.get("family"), envelope.get("profile_hash")
    if (not isinstance(family, str) or not family or not isinstance(profile_hash, str) or not profile_hash
            or question.get("family") != family or question.get("profile_hash") != profile_hash
            or envelope.get("model_type") != "mlp"):
        return False
    factor = envelope.get("intervention")
    if not isinstance(factor, str) or factor not in {"layernorm", "activation", "residual", "depth", "width"}:
        return False
    required_controls = ["opt_key", "loss_key", "budget", "batch_size"]
    if envelope.get("controls") != {"equal": required_controls, "architecture_intervention": factor}:
        return False
    options = envelope.get("family_options")
    budgets, optimizers, losses = (envelope.get(key) for key in ("budget_values", "optimizer_types", "loss_types"))
    if (not isinstance(options, dict) or any(key not in PUBLIC_FIELDS for key in options)
            or not isinstance(budgets, list) or not isinstance(optimizers, list) or not isinstance(losses, list)):
        return False
    for view in (a_view, b_view):
        if view.get("family") != family or view.get("model_type") != "mlp":
            return False
        if any(view.get(key) is None or expected is None or not _equal(view[key], expected) for key, expected in options.items()):
            return False
        if (not _number(view.get("budget")) or view["budget"] <= 0
                or not any(_equal(view["budget"], budget) for budget in budgets)
                or not _number(view.get("batch_size")) or view["batch_size"] <= 0):
            return False
    for field in required_controls:
        if a_view.get(field) is None or b_view.get(field) is None or not _equal(a_view[field], b_view[field]):
            return False
    optimizer, loss = _structural_object(a_view["opt_key"]), _structural_object(a_view["loss_key"])
    if optimizer is None or loss is None:
        return False
    optimizer_type, loss_type = optimizer.get("type"), loss.get("loss_id", loss.get("type"))
    if (not isinstance(optimizer_type, str) or optimizer_type not in optimizers
            or not isinstance(loss_type, str) or loss_type not in losses):
        return False
    if any(view.get("opt") is not None and view["opt"] != optimizer_type for view in (a_view, b_view)):
        return False
    a_model, b_model = (_structural_object(view.get("arch_key")) for view in (a_view, b_view))
    if a_model is None or b_model is None:
        return False
    return _same_intervention_controls(a_model, b_model, factor)
