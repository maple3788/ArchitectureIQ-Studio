"""Import historical prose and compiled clauses as unverified research claims.

Compilation supplies executable hypotheses for an explicitly historical
baseline and the research agenda. It never certifies the historical evidence.
"""
from __future__ import annotations

from copy import deepcopy

from .rules import validate_rule
from .store import canonical_hash


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def import_legacy_claims(raw_claims: list[dict], compiled_rules_document: dict) -> list[dict]:
    """Join raw claims to version-1 compilations without importing authority.

    Input claim order and clause order are stable. A single clause retains the
    historical claim ID; multiple clauses become ``<id>.clause-1``, etc.
    ``source_clause_index`` is one-based, matching those suffixes. Claims with
    no observable compilation keep their original ID and ``rule=None``.

    Raw metadata/text are copied unchanged except the executable ``rule`` and
    usage/validity state. Compilation document metadata and the complete source
    entry are retained under ``legacy_compilation``. Historical evidence IDs
    remain available for ``KBStore.initialize`` to archive and clear. The
    result itself is already disabled and explicitly legacy_unverified.

    Invalid DSL, ambiguous IDs, orphaned compilation entries and conflicting
    split IDs fail explicitly; malformed rules are never silently accepted.
    """
    if not isinstance(raw_claims, list):
        raise ValueError("raw_claims must be a list of historical claim objects")
    if (not isinstance(compiled_rules_document, dict)
            or compiled_rules_document.get("schema_version") != "kb_claim_rules_v1"
            or not isinstance(compiled_rules_document.get("claims"), list)):
        raise ValueError("compiled rules require a kb_claim_rules_v1 document with a claims list")
    canonical_hash(compiled_rules_document)
    originals: dict[str, dict] = {}
    for original in raw_claims:
        if not isinstance(original, dict):
            raise ValueError("historical claim must be an object")
        identifier = _identifier(original.get("id"), "historical claim ID")
        _identifier(original.get("text"), f"historical claim {identifier} text")
        if identifier in originals:
            raise ValueError(f"duplicate historical claim ID: {identifier}")
        canonical_hash(original)
        originals[identifier] = original
    compiled: dict[str, dict] = {}
    for source in compiled_rules_document["claims"]:
        if not isinstance(source, dict):
            raise ValueError("compiled claim must be an object")
        identifier = _identifier(source.get("id"), "compiled claim ID")
        if identifier in compiled:
            raise ValueError(f"duplicate compiled claim ID: {identifier}")
        if identifier not in originals:
            raise ValueError(f"compiled claim has no historical source: {identifier}")
        if source.get("status") not in ("testable", "partial", "untestable"):
            raise ValueError(f"unknown compilation status for {identifier}")
        clauses = source.get("rules", [])
        if not isinstance(clauses, list):
            raise ValueError(f"compiled rules for {identifier} must be a list")
        if source["status"] == "untestable" and clauses:
            raise ValueError(f"untestable claim {identifier} cannot contain executable clauses")
        for index, clause in enumerate(clauses, 1):
            try:
                validate_rule(clause)
            except ValueError as exc:
                raise ValueError(f"invalid compiled rule for {identifier}, clause {index}: {exc}") from exc
        compiled[identifier] = source
    document_metadata = {key: value for key, value in compiled_rules_document.items() if key != "claims"}
    result = []
    output_ids: set[str] = set()
    for identifier, original in originals.items():
        source = compiled.get(identifier)
        clauses = source.get("rules", []) if source is not None else []
        for index, clause in enumerate(clauses or [None], 1):
            claim = deepcopy(original)
            output_id = f"{identifier}.clause-{index}" if len(clauses) > 1 else identifier
            if output_id in output_ids or (output_id != identifier and output_id in originals):
                raise ValueError(f"split claim ID collides with another historical claim: {output_id}")
            output_ids.add(output_id)
            if "rule" in original:
                claim["legacy_original_rule"] = deepcopy(original["rule"])
            claim.update(id=output_id, source_claim_id=identifier, rule=deepcopy(clause),
                         status="legacy_unverified", enabled=False)
            claim.setdefault("revision", 1)
            claim.setdefault("evidence_ids", [])
            claim.pop("source_clause_index", None)
            if clause is not None:
                claim["source_clause_index"] = index
            claim["legacy_compilation"] = {"document": deepcopy(document_metadata), "claim": deepcopy(source)}
            result.append(claim)
    return result
