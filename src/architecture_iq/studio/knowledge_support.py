"""Read-only library evidence summaries, outside immutable solver snapshots."""
from copy import deepcopy

from architecture_iq.kb.store import canonical_hash
from .evolution_task_sources import _CLAIM_FIELDS
from .loop_source import question_support_counts

_NOTICE = '按已保存结果中的不同题目去重；同题重复和多组候选关系不重复计数，不代表独立验证。'
_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError)


def _unknown():
    return {'support_questions': None, 'refute_questions': None, 'unknown_questions': None,
            'complete': False, 'notice': '此版本尚无完整、可核验的逐题支持统计。'}


def _claim_ids(item):
    snapshot = item['snapshot']
    parts = snapshot.get('rules', []) if item['kind'] == 'research_rules' else snapshot.get('claims', snapshot.get('lessons', []))
    return {part.get('metadata', {}).get('claim_id') or part.get('source_claim_id')
            or part.get('rule_id') or part.get('id') for part in [*parts, *item.get('reading_claims', [])]}


def score_question_outcomes(snapshot, scores):
    """Use per-rule assertion verdicts, not full-answer success or edge totals."""
    rules = {(rule['rule_id'], rule['revision']): rule.get('metadata', {}).get('claim_id', rule['rule_id'])
             for rule in snapshot['rules']}
    result = {}
    for score in scores:
        if score.get('kb_version') != snapshot['version']:
            continue
        for row in score.get('per_question', {}).values():
            identity = row.get('question_ref', {}).get('hash') or row.get('question_ref', {}).get('key')
            if not isinstance(identity, str) or not identity:
                continue
            assertions = list(row.get('assertions', []))
            if row.get('scorable') is not True:
                # Scoring stops before assertions when saved feedback is unavailable.
                # The sealed public prediction still identifies exactly which rules
                # participated, but establishes neither support nor a counterexample.
                assertions.extend({'rule_ref': ref, 'verdict': 'unknown'}
                                  for edge in row.get('prediction', {}).get('edges', [])
                                  for ref in edge.get('rules', []))
            for assertion in assertions:
                ref = assertion.get('rule_ref', {})
                claim = rules.get((ref.get('rule_id'), ref.get('revision')))
                if claim is None:
                    continue
                outcome = {'correct': 'support', 'wrong': 'refute'}.get(assertion.get('verdict'), 'unknown') if row.get('scorable') is True else 'unknown'
                result.setdefault(claim, {}).setdefault(identity, set()).add(outcome)
    return result


def _counts(outcomes):
    return {**question_support_counts([{'question_id': qid, 'outcome': value}
                                      for qid, values in outcomes.items() for value in values]), 'notice': _NOTICE}


def _score_summaries(item, jobs):
    from .rule_refinement.views import accepted_rule_snapshot
    scores = []
    for source in item.get('sources', []):
        if source.get('kind') != 'run':
            continue
        try:
            _, snapshot, score = accepted_rule_snapshot(jobs, source['id'])
            if snapshot['version'] == item['version'] and score and score.get('kb_version') == item['version']:
                scores.append(score)
        except _ERRORS:
            continue
    if not scores:
        return {}
    outcomes = score_question_outcomes(item['snapshot'], scores)
    return {cid: _counts(outcomes.get(cid, {})) for cid in _claim_ids(item)}


def _evolution_summaries(item, capture):
    if not capture or capture['observation']['source_identity'] != item['provenance']['source_identity']:
        return {}
    saved = item['snapshot'].get('source_document', {}).get('source_claims', [])
    result = {}
    for claim in saved:
        cid, version = claim['id'], claim['version']
        detail = capture.get('claim_details', {}).get(cid, {})
        if detail.get('claim', {}).get('id') != cid or detail.get('claim', {}).get('version') != version:
            continue
        summary = detail.get('support_summary', {})
        if (summary.get('claim_id') == cid and summary.get('version') == version
                and summary.get('unit') == 'distinct_questions' and summary.get('complete') is True
                and all(type(summary.get(key)) is int and summary[key] >= 0
                        for key in ('support_questions', 'refute_questions', 'unknown_questions'))):
            result[cid] = {key: summary[key] for key in ('support_questions', 'refute_questions', 'unknown_questions', 'complete')}
            result[cid]['notice'] = _NOTICE
        # Legacy counters and truncated windows cannot establish distinct-question support.
    return result


def _same_captured_claims(item, capture):
    claims = [{key: deepcopy(claim[key]) for key in _CLAIM_FIELDS if key in claim}
              for claim in capture.get('claims', []) if isinstance(claim, dict)]
    claims.sort(key=lambda claim: str(claim.get('id', '')))
    return canonical_hash(claims) == item['snapshot'].get('source_document', {}).get('claims_hash')


def knowledge_library_inventory(inventory, *, jobs, evolution):
    """Augment only the human KB library; keep Task/RAG inventory unchanged."""
    result = deepcopy(inventory)
    warnings = result.setdefault('warnings', [])
    captures, current_refs = {}, set()
    try:
        current = evolution.inventory()['items']  # Existing public snapshot adapter; no model/GT work.
        current_refs = {(item['id'], item['version']) for item in current}
        latest = evolution.observer.capture()
        if latest:
            identity = latest['observation']['source_identity']
            for item in evolution.list_kb_snapshots():
                # Claim-only Task selections must not duplicate the whole-library entries.
                if item['id'] != 'evolution_kb_' + identity:
                    continue
                token = {key: item['provenance'][key] for key in ('source_identity', 'sequence')}
                reference = (item['id'], item['version'])
                try:
                    captures[reference] = (latest if reference in current_refs and _same_captured_claims(item, latest)
                                           else evolution.observer.capture(**token))
                except _ERRORS:
                    captures[reference] = None
                item['library'] = {'id': item['id'], 'name': '知识演化',
                                   'version_label': f"第 {item.get('round_index', 0)} 轮保存记录",
                                   'version_order': item['provenance']['sequence']}
                result['items'].append(item)
    except _ERRORS:
        warnings.append({'source_id': 'knowledge_evolution', 'message': '知识演化保存版本暂时无法核验。'})
    for item in result['items']:
        capture = captures.get((item['id'], item['version']))
        if capture and _same_captured_claims(item, capture):
            if hasattr(evolution.observer, 'audit_claims'):
                item['consistency_audits'] = evolution.observer.audit_claims(capture.get('claims', []))
            represented = _claim_ids(item)
            # Keep human-readable excluded claims outside the immutable Task snapshot.
            item['reading_claims'] = [{key: deepcopy(claim[key]) for key in _CLAIM_FIELDS if key in claim}
                                      for claim in capture.get('claims', []) if claim.get('id') not in represented]
        summaries = (_evolution_summaries(item, captures.get((item['id'], item['version'])))
                     if item.get('source_kind') == 'knowledge_evolution' else
                     _score_summaries(item, jobs) if item['kind'] == 'research_rules' else {})
        item['evidence_summary'] = {'scope': 'saved_question_results', 'unit': 'distinct_questions',
            'kb_ref': {key: item[key] for key in ('id', 'version')},
            'claims': {cid: summaries.get(cid, _unknown()) for cid in _claim_ids(item) if cid}}
        if capture:
            item['evidence_summary']['observation'] = {key: capture['observation'][key]
                                                     for key in ('source_identity', 'sequence')}
    result['total'] = len(result['items'])
    return result
