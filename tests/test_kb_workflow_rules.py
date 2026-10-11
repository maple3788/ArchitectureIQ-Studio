import copy

import pytest


def rule(**updates):
    value = {"scope": ["family", "eq", "xor_classification"],
             "same": ["width", "opt_key"], "differ": ["ln_all"],
             "predict": {"better": ["ln_all", "eq", True], "worse": ["ln_any", "eq", False]}}
    return {**value, **updates}


def views():
    common = {"family": "xor_classification", "width": 32, "opt_key": "adam"}
    return {**common, "ln_all": True, "ln_any": True}, {**common, "ln_all": False, "ln_any": False}


def test_compound_scope_and_equal_controls_select_exactly_one_candidate():
    from architecture_iq.kb.rules import match_rule
    a, b = views()
    value = rule(scope={"all": [["family", "eq", "xor_classification"],
                              {"any": [["width", "ge", 32], ["width", "eq", 16]]}]})
    assert match_rule(value, a, b) == 0
    assert match_rule(value, b, a) == 1
    assert match_rule(value, a, {**b, "width": 64}) is None


@pytest.mark.parametrize("missing", [None, "absent"])
def test_missing_under_not_does_not_match(missing):
    from architecture_iq.kb.rules import match_rule
    a, b = views()
    if missing is None:
        a["target_std"] = None
        b["target_std"] = None
    value = rule(scope={"not": ["target_std", "lt", 1.0]})
    assert match_rule(value, a, b) is None
    assert match_rule(rule(scope={"not": {"not": ["target_std", "gt", 0]}}), a, b) is None


def test_missing_equal_or_different_controls_never_match():
    from architecture_iq.kb.rules import match_rule
    a, b = views()
    assert match_rule(rule(same=["target_std"]), a, b) is None
    assert match_rule(rule(differ=["target_std"]), a, {**b, "target_std": 2}) is None


@pytest.mark.parametrize("field", ["dataset_id", "candidate_id", "lineage_id", "correct_letter", "mean_test_ce",
                                    "seed", "source_hashes", "path", "__class__", "arch_key"])
def test_nonpublic_selectors_are_rejected(field):
    from architecture_iq.kb.rules import validate_rule
    with pytest.raises(ValueError):
        validate_rule(rule(scope=[field, "eq", "secret"]))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), {"x": 1}, None])
def test_nonfinite_or_structured_literals_are_rejected(bad):
    from architecture_iq.kb.rules import validate_rule
    with pytest.raises(ValueError):
        validate_rule(rule(scope=["width", "eq", bad]))


def test_unsafe_nesting_and_unknown_rule_keys_are_rejected():
    from architecture_iq.kb.rules import validate_rule
    nested = ["width", "eq", 32]
    for _ in range(30):
        nested = {"not": nested}
    for value in [rule(scope=nested), rule(results=True), rule(scope={"all": [], "not": ["width", "eq", 1]}),
                  rule(same=["width"], differ=["width"]), rule(scope=["width", "exec", "x"])]:
        with pytest.raises(ValueError):
            validate_rule(value)


def test_ambiguous_prediction_abstains_and_multiple_prediction_modes_rejected():
    from architecture_iq.kb.rules import match_rule, validate_rule
    a, b = views()
    assert match_rule(rule(predict={"better": ["width", "eq", 32], "worse": ["width", "eq", 32]}), a, b) is None
    with pytest.raises(ValueError):
        validate_rule(rule(predict={"higher_better": "width", "lower_better": "depth"}))


def test_numeric_and_pareto_predictions_require_known_compatible_values():
    from architecture_iq.kb.rules import match_rule
    a, b = {"width": 32, "depth": 4}, {"width": 16, "depth": 2}
    value = {"predict": {"dominates": [["width", "higher", 2], ["depth", "higher"]]}}
    assert match_rule(value, a, b) == 0
    assert match_rule(value, {"width": 32}, b) is None
    assert match_rule({"predict": {"higher_better": "width", "min_ratio": 3}}, a, b) is None
    assert match_rule({"predict": {"higher_better": "width"}}, {"width": "32"}, b) is None


def test_public_view_omits_identities_results_and_rejects_executable_expression():
    from architecture_iq.kb.rules import public_views
    dataset = {"family": "xor_classification", "selection_metric": "test_ce", "dataset_id": "secret",
               "params": {"input_dim": 2}}
    candidate = {"candidate_id": "secret", "model": {"type": "mlp", "depth": 2, "width": 16, "layer_norm": [False]*2},
                 "optimizer": {"type": "Adam", "lr": .01}, "budget": {"training_steps": 4, "batch_size": 2, "total_samples_seen": 8},
                 "mean_test_ce": 0.01}
    result = public_views(dataset, [candidate])[0]
    assert result["width"] == 16
    assert not {"candidate_id", "dataset_id", "mean_test_ce"} & result.keys()
    bad = copy.deepcopy(dataset)
    bad["params"]["expression"] = "().__class__.__bases__"
    with pytest.raises(ValueError):
        public_views(bad, [candidate])


def test_oversized_numeric_literals_are_rejected_as_validation_errors():
    from architecture_iq.kb.rules import validate_rule
    with pytest.raises(ValueError):
        validate_rule(rule(scope=["width", "eq", 10 ** 10000]))


def test_null_predicate_inside_conjunction_is_rejected():
    from architecture_iq.kb.rules import validate_rule
    with pytest.raises(ValueError):
        validate_rule(rule(scope=[["width", "eq", 32], None]))


def test_loss_fingerprint_is_a_control_and_never_a_scope_selector():
    from architecture_iq.kb.rules import match_rule, public_views, validate_rule
    dataset = {"family": "xor_classification", "selection_metric": "test_ce", "params": {"input_dim": 2}}
    base = {"model": {"type": "mlp", "depth": 2, "width": 16, "layer_norm": [False] * 2},
            "optimizer": {"type": "Adam", "lr": .01},
            "budget": {"training_steps": 4, "batch_size": 2, "total_samples_seen": 8},
            "loss": {"loss_id": "cross_entropy"}}
    other = copy.deepcopy(base)
    other["model"]["width"] = 32
    a, b = public_views(dataset, [base, other])
    controlled = {"same": ["loss_key"], "predict": {"higher_better": "width"}}
    assert match_rule(controlled, a, b) == 1
    other["loss"] = {"loss_id": "cross_entropy", "label_smoothing": .1}
    changed = public_views(dataset, [other])[0]
    assert match_rule(controlled, a, changed) is None
    with pytest.raises(ValueError):
        validate_rule({"scope": ["loss_key", "eq", "x"], "predict": {"higher_better": "width"}})


def scoped_pair(factor="width"):
    import json
    envelope = {"family": "xor_classification", "model_type": "mlp", "profile_hash": "a" * 64,
                "budget_values": [8192], "optimizer_types": ["Adam"], "loss_types": ["cross_entropy"],
                "intervention": factor, "family_options": {"input_dim": 2},
                "pair_sampling": "uniform_applicable_pairs_from_factor_variants",
                "controls": {"equal": ["opt_key", "loss_key", "budget", "batch_size"],
                             "architecture_intervention": factor}}
    question = {"family": "xor_classification", "profile_hash": "a" * 64}
    claim = {"validated_scope": envelope}
    model = {"type": "mlp", "width": 16, "depth": 2, "activation": "relu", "residual": False,
             "layer_norm": [False, False]}
    view = {"family": "xor_classification", "model_type": "mlp", "input_dim": 2,
            "budget": 8192, "batch_size": 32, "opt": "Adam",
            "opt_key": json.dumps({"type": "Adam", "lr": .001}),
            "loss_key": json.dumps({"loss_id": "cross_entropy"}), "arch_key": json.dumps(model)}
    other = copy.deepcopy(view)
    model["width"] = 32
    other["arch_key"] = json.dumps(model)
    return question, claim, view, other


def replace_arch(view, **updates):
    import json
    return {**view, "arch_key": json.dumps({**json.loads(view["arch_key"]), **updates})}


def test_validated_scope_accepts_controlled_pair_without_running_authored_rule():
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    claim["rule"] = {"this is deliberately not": "a valid authored rule"}
    assert match_validated_scope(question, claim, a, b) is True
    assert match_validated_scope(question, claim, b, a) is True


@pytest.mark.parametrize("key,value", [("profile_hash", None), ("profile_hash", "b" * 64),
                                       ("family", "univariate_regression")])
def test_validated_scope_requires_exact_question_provenance(key, value):
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    question[key] = value
    assert match_validated_scope(question, claim, a, b) is False


@pytest.mark.parametrize("patch", [{"family": "spiral_classification"}, {"model_type": "gru_lm"},
                                   {"input_dim": None}, {"input_dim": 4}, {"budget": 4096},
                                   {"batch_size": 64}, {"opt_key": None}, {"loss_key": None}])
def test_validated_scope_rejects_outside_distribution_or_unequal_controls(patch):
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    assert match_validated_scope(question, claim, a, {**b, **patch}) is False


def test_validated_scope_rejects_equal_but_out_of_pool_optimizer_and_loss():
    import json
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    for patch in ({"opt": "SGD", "opt_key": json.dumps({"type": "SGD", "lr": .001})},
                  {"loss_key": json.dumps({"loss_id": "mse"})}):
        assert match_validated_scope(question, claim, {**a, **patch}, {**b, **patch}) is False


def test_validated_scope_blocks_architecture_confound_and_unknown_structural_metadata():
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    assert match_validated_scope(question, claim, a, replace_arch(b, residual=True)) is False
    assert match_validated_scope(question, claim, a, replace_arch(b, type="gru_lm")) is False
    for value in (None, "{bad json", "null", "[]", '{"type":"mlp"}', '{"type":"mlp","depth":NaN}'):
        assert match_validated_scope(question, claim, a, {**b, "arch_key": value}) is False


def test_validated_scope_depth_allows_only_same_uniform_layernorm_mode():
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, _ = scoped_pair("depth")
    b = replace_arch(a, depth=4, layer_norm=[False] * 4)
    assert match_validated_scope(question, claim, a, b) is True
    assert match_validated_scope(question, claim, a, replace_arch(b, layer_norm=[True] * 4)) is False
    assert match_validated_scope(question, claim, a, replace_arch(b, layer_norm=[False, True] * 2)) is False
    assert match_validated_scope(question, claim, a, replace_arch(b, layer_norm=[False] * 3)) is False


def test_validated_scope_activation_allows_conditional_leaky_slope_only():
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, _ = scoped_pair("activation")
    b = replace_arch(a, activation="leaky_relu", leaky_relu_slope=.01)
    assert match_validated_scope(question, claim, a, b) is True
    assert match_validated_scope(question, claim, a, replace_arch(b, width=32)) is False


@pytest.mark.parametrize("factor,changes", [("layernorm", {"layer_norm": [True, True]}),
                                           ("residual", {"residual": True})])
def test_validated_scope_accepts_only_registered_factor_changes(factor, changes):
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, _ = scoped_pair(factor)
    b = replace_arch(a, **changes)
    assert match_validated_scope(question, claim, a, b) is True
    assert match_validated_scope(question, claim, a, replace_arch(b, width=32)) is False


def test_validated_scope_layernorm_rejects_unstudied_partial_layernorm_change():
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, _ = scoped_pair("layernorm")
    assert match_validated_scope(question, claim, a, replace_arch(a, layer_norm=[False, True])) is False


def test_validated_scope_abstains_without_verified_envelope_or_without_intervention():
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    assert match_validated_scope(question, {}, a, b) is False
    assert match_validated_scope(question, claim, a, a) is False
    claim["validated_scope"]["intervention"] = "unknown"
    assert match_validated_scope(question, claim, a, b) is False


@pytest.mark.parametrize("strategy", [None, "first_applicable_pair", "best_gt_gap"])
def test_validated_scope_rejects_unverified_pair_selection_strategy(strategy):
    from architecture_iq.kb.rules import match_validated_scope
    question, claim, a, b = scoped_pair()
    claim["validated_scope"]["pair_sampling"] = strategy
    assert match_validated_scope(question, claim, a, b) is False


def r6_rule():
    return {"scope": [["model_type", "eq", "mlp"], ["residual", "eq", True]],
            "same": ["opt_key"], "differ": ["depth", "width"], "max_param_ratio": 2.0,
            "predict": {"dominates": [["depth", "higher"], ["width", "lower"]]}}


def r6_views():
    common = {"model_type": "mlp", "residual": True, "opt_key": "adam"}
    return ({**common, "depth": 4, "width": 16, "params": 200},
            {**common, "depth": 2, "width": 32, "params": 100})


@pytest.mark.parametrize("params,expected", [(100, 0), (200, 0), (200.00001, None), (50, 0), (49.99999, None)])
def test_max_param_ratio_accepts_equal_boundary_and_abstains_outside(params, expected):
    from architecture_iq.kb.rules import match_rule
    a, b = r6_views()
    a["params"] = params
    assert match_rule(r6_rule(), a, b) == expected
    assert match_rule(r6_rule(), b, a) == (1 if expected == 0 else None)


@pytest.mark.parametrize("params", [None, 0, -1, True, "200", float("inf"), float("nan")])
def test_max_param_ratio_abstains_on_unknown_or_invalid_public_parameter_counts(params):
    from architecture_iq.kb.rules import match_rule
    a, b = r6_views()
    assert match_rule(r6_rule(), {**a, "params": params}, b) is None
    assert match_rule(r6_rule(), a, {**b, "params": params}) is None
    a.pop("params")
    assert match_rule(r6_rule(), a, b) is None


@pytest.mark.parametrize("limit", [None, 0, .99, -2, True, "2", {}, float("inf"), float("nan")])
def test_max_param_ratio_rejects_nonfinite_nonnumeric_or_subunit_limit(limit):
    from architecture_iq.kb.rules import validate_rule
    with pytest.raises(ValueError, match="max_param_ratio"):
        validate_rule({**r6_rule(), "max_param_ratio": limit})


def reported_rule(rule=None, **metadata):
    return {"rule_id": "rule_r6", "revision": "a" * 64, "state": "active",
            "rule": rule or r6_rule(), "metadata": {
                "claim_id": "R6", "clause_index": 1, "validity_status": "replicated_in_scope",
                "validation_origin": "source_reported", **metadata}}


def test_injection_same_relaxes_only_context_matching_and_never_mutates_strict_rule():
    from architecture_iq.kb.rules import match_rule, match_rule_for_injection
    a, b = r6_views()
    b["opt_key"] = "sgd"
    entry = reported_rule(inject_same=[])
    before = copy.deepcopy(entry)
    assert match_rule(entry["rule"], a, b) is None
    assert match_rule_for_injection(entry, a, b) == 0
    assert entry == before
    assert match_rule(entry["rule"], a, b) is None


@pytest.mark.parametrize("patch", [{"params": 401}, {"depth": 4}, {"width": 16},
                                   {"residual": False}, {"model_type": "transformer"},
                                   {"depth": 8, "width": 32}])
def test_injection_same_preserves_parameter_scope_differ_and_prediction_conditions(patch):
    from architecture_iq.kb.rules import match_rule_for_injection
    a, b = r6_views()
    entry = reported_rule(inject_same=[])
    assert match_rule_for_injection(entry, a, {**b, **patch}) is None


def test_injection_without_override_keeps_equal_controls():
    from architecture_iq.kb.rules import match_rule_for_injection
    a, b = r6_views()
    assert match_rule_for_injection(reported_rule(), a, b) == 0
    assert match_rule_for_injection(reported_rule(), a, {**b, "opt_key": "sgd"}) is None


@pytest.mark.parametrize("metadata", [{"inject": False}, {"validity_status": "proposed"},
                                      {"validity_status": "refuted"}, {"validity_status": "inconclusive"},
                                      {"validity_status": None}, {"validation_origin": "modified_in_studio"},
                                      {"validation_origin": None}])
def test_context_injection_requires_source_reported_replication_and_permission(metadata):
    from architecture_iq.kb.rules import match_rule, match_rule_for_injection
    a, b = r6_views()
    entry = reported_rule(**metadata)
    assert match_rule(entry["rule"], a, b) == 0
    assert match_rule_for_injection(entry, a, b) is None


def test_context_injection_excludes_retired_and_unmarked_legacy_rules():
    from architecture_iq.kb.rules import match_rule_for_injection
    a, b = r6_views()
    entry = reported_rule()
    entry["state"] = "retired"
    assert match_rule_for_injection(entry, a, b) is None
    entry["state"] = "active"
    entry.pop("metadata")
    assert match_rule_for_injection(entry, a, b) is None


@pytest.mark.parametrize("role", ["exploratory", "descriptive"])
def test_nonconfirmatory_protocol_roles_are_never_injected_even_when_source_reports_replication(role):
    from architecture_iq.kb.rules import match_rule, match_rule_for_injection
    a, b = r6_views()
    entry = reported_rule(role=role)
    assert match_rule(entry["rule"], a, b) == 0
    assert match_rule_for_injection(entry, a, b) is None
