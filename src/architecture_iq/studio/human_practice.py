"""Reveal stored results only after a human commits a public answer option.

This service is deliberately separate from Task preview, solver requests, and
evaluation receipts. It never computes GT or promotes research into evaluation.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re


class PracticeConflict(ValueError):
    pass


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _choice_mapping(question):
    choices = question.get('choices', [])
    by_id, by_letter = {}, {}
    for choice in choices:
        cid, letter = choice.get('id'), choice.get('letter')
        if (not isinstance(cid, str) or not cid or not isinstance(letter, str) or not letter
                or cid in by_id or letter in by_letter):
            raise PracticeConflict('题目选项映射不完整，请重新打开题目')
        value = {'id': cid, 'letter': letter}
        by_id[cid], by_letter[letter] = value, value
    if not by_id:
        raise PracticeConflict('题目没有可提交的选项')
    return by_id, by_letter


def project_feedback(question, raw):
    """Allowlist saved human-visible metrics/curves; never return source files."""
    by_id, by_letter = _choice_mapping(question)
    raw = raw if isinstance(raw, dict) else {}
    reveal = raw.get('reveal') if isinstance(raw.get('reveal'), dict) else {}
    corrects = {value for value in (raw.get('correct_letter'), reveal.get('correctLetter'))
                if isinstance(value, str) and value}
    if len(corrects) > 1 or any(letter not in by_letter for letter in corrects):
        raise PracticeConflict('已保存答案与题目选项不一致，请检查来源记录')
    correct = next(iter(corrects), None)
    result = {'candidate_metrics': {}, 'reveal': {'curves': [], 'ranked': []}}
    if correct:
        result['correct_letter'] = result['reveal']['correctLetter'] = correct

    def binding(value, expected_id=None):
        identities = [value[key] for key in ('candidateId', 'candidate_id') if key in value]
        if expected_id is not None:
            identities.append(expected_id)
        letter = value.get('letter')
        if identities:
            if any(not isinstance(cid, str) or cid != identities[0] for cid in identities):
                return None
            choice = by_id.get(identities[0])
            return choice if choice and (letter is None or letter == choice['letter']) else None
        return by_letter.get(letter) if isinstance(letter, str) else None

    metrics = raw.get('candidate_metrics')
    if isinstance(metrics, dict):
        for cid, value in metrics.items():
            if cid not in by_id or not isinstance(value, dict) or not binding(value, cid):
                continue
            shown = {'letter': by_id[cid]['letter']}
            for key, entry in value.items():
                if key in ('selection_metric', 'metric') and isinstance(entry, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', entry):
                    shown[key] = entry
                elif (key in ('mean', 'std', 'n_seeds', 'failed_seeds') or
                      re.fullmatch(r'(mean|std)_(test|train)_[a-z0-9_]{1,48}', key)) and _number(entry):
                    shown[key] = entry
                elif key == 'excluded' and type(entry) is bool:
                    shown[key] = entry
            result['candidate_metrics'][cid] = shown

    ranked = reveal.get('ranked', [])
    for value in ranked if isinstance(ranked, list) else []:
        if not isinstance(value, dict) or not (choice := binding(value)):
            continue
        entry = {'candidateId': choice['id'], 'letter': choice['letter']}
        for key in ('mean', 'std'):
            if _number(value.get(key)):
                entry[key] = value[key]
        if isinstance(value.get('metric'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', value['metric']):
            entry['metric'] = value['metric']
        result['reveal']['ranked'].append(entry)
    curves = reveal.get('curves', raw.get('curves', []))
    for value in curves if isinstance(curves, list) else []:
        if not isinstance(value, dict) or not (choice := binding(value)):
            continue
        axis = next((key for key in ('samples', 'steps', 'x') if key in value), None)
        x, means = value.get(axis), value.get('mean')
        if (not isinstance(x, list) or not isinstance(means, list) or not 1 <= len(x) == len(means) <= 100000
                or not all(_number(number) for number in x + means)
                or any(b <= a for a, b in zip(x, x[1:]))):
            continue
        entry = {'candidateId': choice['id'], 'letter': choice['letter'], axis: deepcopy(x), 'mean': deepcopy(means)}
        std = value.get('std')
        if isinstance(std, list) and len(std) == len(x) and all(_number(v) and v >= 0 for v in std):
            entry['std'] = deepcopy(std)
        if isinstance(value.get('metric'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', value['metric']):
            entry['metric'] = value['metric']
        result['reveal']['curves'].append(entry)
    return result


def _observed_question(observer, source):
    if set(source) != {'kind', 'question_id', 'observation', 'expected_question_hash'}:
        raise ValueError('Invalid observed question reference')
    qid, token, expected = source['question_id'], source['observation'], source['expected_question_hash']
    if (not isinstance(qid, str) or not re.fullmatch(r'q_[A-Za-z0-9_-]{1,80}', qid)
            or not isinstance(token, dict) or set(token) != {'source_identity', 'sequence'}
            or not isinstance(token['source_identity'], str) or not re.fullmatch(r'[0-9a-f]{64}', token['source_identity'])
            or type(token['sequence']) is not int or not 1 <= token['sequence'] <= 2**63-1
            or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
        raise ValueError('Invalid observed question reference')
    try:
        capture = observer.capture(**token)
    except KeyError as exc:
        raise PracticeConflict('阅读记录或来源已变化，请重新打开题目') from exc
    if not capture:
        raise PracticeConflict('阅读记录暂时不可用，请重新打开题目')
    known = any(row.get('status') == 'ok' and row.get('question_id') == qid
        for detail in capture['round_details'].values() for row in detail.get('generation', {}).get('items', []))
    known = known or any(row.get('question_id') == qid for detail in capture['claim_details'].values()
        for row in [*detail.get('evidence', []), *detail.get('counterexamples', {}).get('items', [])])
    known = known or any(row.get('question_id') == qid
        for detail in capture['round_details'].values()
        for versions in detail.get('claim_details', {}).values() for saved in versions.values()
        for row in [*saved.get('evidence', []), *saved.get('counterexamples', {}).get('items', [])])
    if not known:
        raise PracticeConflict('这份阅读记录没有保存该题，请重新打开题目')
    record = observer.question(qid)
    if record['observation']['content_hash'] != expected:
        raise PracticeConflict('题目内容已变化，请重新打开后作答')
    return record


def review_question(catalog, observer, body):
    if not isinstance(body, dict) or set(body) != {'source', 'answer_id'}:
        raise ValueError('A source and committed answer are required')
    source, answer = body['source'], body['answer_id']
    if not isinstance(source, dict) or not isinstance(answer, str) or not 1 <= len(answer) <= 512:
        raise ValueError('Invalid answer')
    if source.get('kind') == 'catalog':
        if set(source) != {'kind', 'key'} or not isinstance(source['key'], str) or not 1 <= len(source['key']) <= 512:
            raise ValueError('Invalid catalog question reference')
        public = catalog.get_question(source['key'], include_private=False)
    elif source.get('kind') == 'knowledge_evolution':
        public = _observed_question(observer, source)
    else:
        raise ValueError('Unknown question source')
    by_id, by_letter = _choice_mapping(public['public'])
    if answer not in by_id:
        raise ValueError('Please submit an option from the displayed question')
    # This is the only boundary where a valid human option unlocks saved GT.
    if source['kind'] == 'catalog':
        record = catalog.get_question(source['key'], include_private=True)
        feedback = project_feedback(public['public'], record.get('feedback'))
    else:
        feedback = observer.question_results(source['question_id'], expected_question_hash=source['expected_question_hash'])
    correct = by_letter.get(feedback.get('correct_letter'))
    value = {'selected_answer': by_id[answer], 'correct_answer': correct,
             'correct': answer == correct['id'] if correct else None, 'feedback': feedback}
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
