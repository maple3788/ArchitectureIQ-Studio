"""Explicit human reading of saved results, without an answer or evaluation.

This endpoint is separate from solver inputs and answer-commitment receipts.
It only reads existing artifacts through the same identity and result projection
used for human practice; it never runs experiments or writes an answer.
"""
from __future__ import annotations

from .human_practice import PracticeConflict, _choice_mapping, _observed_question, project_feedback
from .rag_inputs import validate_rag_question


def inspect_question(catalog, observer, body, *, evolution=None):
    if not isinstance(body, dict) or set(body) != {'source'} or not isinstance(body['source'], dict):
        raise ValueError('A saved question reference is required')
    source = body['source']
    if source.get('kind') == 'catalog':
        if set(source) != {'kind', 'key'} or not isinstance(source['key'], str) or not 1 <= len(source['key']) <= 512:
            raise ValueError('Invalid catalog question reference')
        key = source['key']
        frozen_evolution = key.startswith('evolution_')
        if frozen_evolution and evolution is None:
            raise KeyError('Saved evolution question is unavailable')
        public = (evolution if frozen_evolution else catalog).get_question(key, include_private=False)
    elif source.get('kind') == 'knowledge_evolution':
        public = _observed_question(observer, source)
        frozen_evolution = False
    else:
        raise ValueError('Unknown question source')
    by_id, by_letter = _choice_mapping(public['public'])

    if source['kind'] == 'knowledge_evolution':
        raw = observer.question_results(source['question_id'], expected_question_hash=source['expected_question_hash'])
    elif frozen_evolution:
        identity = public.get('provenance', {}).get('source_identity')
        expected = public.get('observation', {}).get('content_hash')
        if not identity or not expected or not observer.config or observer.config.identity != identity:
            raise PracticeConflict('知识演化来源或题目版本已变化，请重新打开题目。')
        raw = observer.question_results(public['public']['id'], expected_question_hash=expected)
    else:
        record = catalog.get_question(source['key'], include_private=True)
        if (validate_rag_question(public['public']) != validate_rag_question(record['public'])
                or public.get('metadata', {}).get('hash') != record.get('metadata', {}).get('hash')):
            raise PracticeConflict('保存的结果与当前题目版本不一致，请重新打开题目。')
        raw = record.get('feedback')
    feedback = project_feedback(public['public'], raw)
    correct = by_letter.get(feedback.get('correct_letter'))
    value = {'scope': 'human_inspection', 'correct_answer': correct, 'feedback': feedback}
    notices = []
    if not correct:
        notices.append('该题尚未保存可用的正确答案。')
    if not feedback['reveal']['curves']:
        notices.append('该题未保存带真实横轴的可用训练曲线。')
    elif len({curve['candidateId'] for curve in feedback['reveal']['curves']}) < len(by_id):
        notices.append('部分候选未保存带真实横轴的可用训练曲线，仅展示已有曲线。')
    if notices:
        value['notice'] = ''.join(notices)
    return value
