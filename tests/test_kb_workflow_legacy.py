"""Legacy compilations are hypotheses, with traceable clause-level identity."""
from copy import deepcopy

import pytest

from architecture_iq.kb.legacy import import_legacy_claims
from architecture_iq.kb.store import KBStore


RULE = {"same": ["opt_key", "budget"], "predict": {"lower_better": "width"}}
OTHER_RULE = {"same": ["opt_key", "budget"], "predict": {"higher_better": "depth"}}


def raw_claim(identifier="K0001", **fields):
    return {"id": identifier, "text": "Preserve this original claim text.", "credibility": .9,
            "support_count": 8, "failure_count": 2, "created_epoch": 4, **fields}


def document(*entries):
    return {"schema_version": "kb_claim_rules_v1", "kb_snapshot": "data/kb_0008.json",
            "compiled_by": "compiler provenance", "selection": "evidence-bearing claims",
            "claims": list(entries)}


def entry(identifier="K0001", rules=None, status="testable"):
    return {"id": identifier, "status": status, "note": "Only observable clauses compiled.",
            "rules": [deepcopy(RULE)] if rules is None else rules}


def test_single_clause_attaches_rule_and_preserves_source_metadata(tmp_path):
    original = raw_claim()
    compiled = document(entry())
    saved_original, saved_compiled = deepcopy(original), deepcopy(compiled)
    imported = import_legacy_claims([original], compiled)
    assert len(imported) == 1
    result = imported[0]
    assert result["id"] == result["source_claim_id"] == "K0001"
    assert result["source_clause_index"] == 1
    assert result["rule"] == RULE
    for field, value in original.items():
        assert result[field] == value
    assert result["legacy_compilation"]["document"]["compiled_by"] == "compiler provenance"
    assert result["legacy_compilation"]["claim"]["note"] == entry()["note"]
    stored = KBStore(tmp_path).initialize(imported)["claims"][0]
    assert stored["status"] == "legacy_unverified" and stored["enabled"] is False
    assert stored["evidence_ids"] == []
    result["rule"]["predict"]["lower_better"] = "depth"
    assert original == saved_original and compiled == saved_compiled


def test_multiple_clauses_split_deterministically_without_rewriting_text():
    compiled = document(entry(rules=[deepcopy(RULE), deepcopy(OTHER_RULE)], status="partial"))
    imported = import_legacy_claims([raw_claim()], compiled)
    assert [item["id"] for item in imported] == ["K0001.clause-1", "K0001.clause-2"]
    assert [item["source_clause_index"] for item in imported] == [1, 2]
    assert all(item["source_claim_id"] == "K0001" for item in imported)
    assert all(item["text"] == raw_claim()["text"] for item in imported)
    assert [item["rule"] for item in imported] == [RULE, OTHER_RULE]
    assert import_legacy_claims([raw_claim()], compiled) == imported


def test_uncompiled_and_untestable_claims_remain_disabled_agenda():
    raw = [raw_claim("K0001"), raw_claim("K0002"), raw_claim("K0003")]
    compiled = document(entry("K0002", rules=[], status="untestable"), entry("K0003", rules=[]))
    imported = import_legacy_claims(raw, compiled)
    assert [item["id"] for item in imported] == ["K0001", "K0002", "K0003"]
    assert all(item["rule"] is None and item["enabled"] is False for item in imported)
    assert all(item["status"] == "legacy_unverified" for item in imported)
    assert all("source_clause_index" not in item for item in imported)


def test_import_cannot_inherit_scientific_authority(tmp_path):
    raw = [raw_claim(status="replicated_in_scope", enabled=True, evidence_ids=["legacy-evidence"])]
    imported = import_legacy_claims(raw, document(entry()))
    assert imported[0]["enabled"] is False
    assert imported[0]["status"] == "legacy_unverified"
    stored = KBStore(tmp_path).initialize(imported)["claims"][0]
    assert stored["enabled"] is False and stored["evidence_ids"] == []
    assert stored["legacy_evidence_ids"] == ["legacy-evidence"]


def test_invalid_compilation_is_rejected_instead_of_silently_downgraded():
    invalid = entry(rules=[{"predict": {"higher_better": "final_test_mse"}}])
    with pytest.raises(ValueError, match="K0001.*clause|selector"):
        import_legacy_claims([raw_claim()], document(invalid))


@pytest.mark.parametrize("raw,compiled", [
    ([raw_claim(), raw_claim()], document()),
    ([raw_claim()], document(entry(), entry())),
    ([raw_claim()], document(entry("missing"))),
    ([raw_claim(), raw_claim("K0001.clause-1")], document(entry(rules=[RULE, OTHER_RULE]))),
    ([raw_claim()], document(entry(status="unknown"))),
    ([raw_claim()], document(entry(rules="not a clause list"))),
    ([raw_claim()], document(entry(rules=[RULE], status="untestable"))),
])
def test_ambiguous_or_malformed_legacy_sources_fail(raw, compiled):
    with pytest.raises(ValueError):
        import_legacy_claims(raw, compiled)
