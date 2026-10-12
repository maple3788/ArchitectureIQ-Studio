"""Read frozen Task answers; saved feedback is gated by persisted commitment."""
from __future__ import annotations

from copy import deepcopy

from architecture_iq.kb.store import canonical_hash
from .catalog import _spec, _CANDIDATE_KEYS, _DATASET_KEYS, _CODE_FILES
from .human_practice import PracticeConflict, _choice_mapping, project_feedback
from .rag_inputs import validate_rag_question


def freeze_question_record(record):
    """Keep the reader's public specifications, without source paths or feedback."""
    metadata = record.get('metadata', {})
    value = {'metadata': {key: deepcopy(metadata[key]) for key in
        ('id', 'key', 'hash', 'family', 'type', 'profile', 'metric', 'source_kind', 'round_index') if key in metadata},
        'public': validate_rag_question(record['public'])}
    detail = record.get('detail', {})
    if detail:
        dataset = detail.get('dataset', {})
        files = dataset.get('files', {})
        shown_dataset = {key: deepcopy(dataset[key]) for key in
                         ('datasetId', 'family', 'selectionMetric') if key in dataset}
        shown_files = {'synthesize.py': files['synthesize.py']} if isinstance(files.get('synthesize.py'), str) else {}
        if 'dataset_spec.json' in files:
            shown_files['dataset_spec.json'] = _spec(files['dataset_spec.json'], _DATASET_KEYS)
        if 'params' in dataset:
            shown_dataset.update(_spec({'params': dataset['params']}, _DATASET_KEYS))
        shown_dataset['files'] = shown_files
        choices = []
        for choice in detail.get('choices', []):
            files = choice.get('files', {})
            shown = {name: files[name] for name in _CODE_FILES if isinstance(files.get(name), str)}
            if 'candidate_spec.json' in files:
                shown['candidate_spec.json'] = _spec(files['candidate_spec.json'], _CANDIDATE_KEYS)
            choices.append({**{key: choice[key] for key in ('candidateId', 'letter') if key in choice}, 'files': shown})
        value['detail'] = {'dataset': shown_dataset, 'choices': choices}
        if isinstance(detail.get('prompt'), str):
            value['detail']['prompt'] = detail['prompt']
    # These non-secret identities bind evolution feedback to its original
    # source/public artifact, even if the observer later changes configuration.
    if metadata.get('source_kind') == 'knowledge_evolution':
        value['observation'] = {key: record.get('observation', {})[key] for key in
            ('content_hash',) if key in record.get('observation', {})}
        value['provenance'] = {key: record.get('provenance', {})[key] for key in
            ('source_identity',) if key in record.get('provenance', {})}
    return value


def _frozen_record(config):
    if 'question_record' in config:
        return freeze_question_record(config['question_record']), None
    if 'case' in config:
        case = config['case']
        specs = {spec['candidate_id']: spec for spec in case['candidate_specs']}
        record = {'metadata': dict(case['ref']), 'public': case['question'], 'detail': {
            'prompt': case['question'].get('prompt', ''),
            'dataset': {'files': {'dataset_spec.json': case['dataset_spec']}},
            'choices': [{'candidateId': choice['id'], 'letter': choice['letter'],
                         'files': {'candidate_spec.json': specs[choice['id']]}}
                        for choice in case['question']['choices']]}}
        return freeze_question_record(record), '旧作答仅保存了公开题面与结构化配置；未补入当前题目的代码文件。'
    return {'metadata': {'key': config['question_key']}, 'public': validate_rag_question(config['question'])}, \
        '旧作答仅保存了当时提供给模型的公开题面与候选特征；完整配置文件未保存在该作答中。'


def _committed_choice(receipt, shown, question, job=None):
    by_id, by_letter = _choice_mapping(question)
    if shown['status'] != 'complete':
        return None
    if receipt['mode'] == 'rules':
        prediction = receipt['result']['prediction']
        selected = by_id.get(prediction.get('answer_id'))
        return selected if (prediction.get('status') == 'answered' and selected
                            and selected['letter'] == prediction.get('answer_letter')) else None
    answer = (job.get('result') or {}).get('answer') or {}
    ranking = answer.get('ranking')
    if (answer.get('valid') is not True or answer.get('abstain') is True
            or isinstance(answer.get('raw'), dict) and answer['raw'].get('abstain') is True
            or not isinstance(ranking, list) or not all(isinstance(letter, str) for letter in ranking)
            or len(ranking) != len(by_letter) or set(ranking) != set(by_letter)):
        return None
    config = receipt['config']
    operation = f"rag:{config['question_key']}:{config['models'][0]['id']}"
    committed = any(record.get('key') == operation and record.get('status') == 'complete'
        and record.get('input_hash') == canonical_hash(config['request'])
        and record.get('answer') == answer for record in job.get('records', []))
    return by_letter[ranking[0]] if committed else None


def _same_question(frozen, loaded, config):
    if validate_rag_question(frozen['public']) != validate_rag_question(loaded['public']):
        raise PracticeConflict('保存的结果与本次作答的题面不一致，未展示正确答案。')
    expected = frozen.get('metadata', {}).get('hash') or config.get('case', {}).get('ref', {}).get('hash')
    if expected and loaded.get('metadata', {}).get('hash') != expected:
        raise PracticeConflict('题目版本与本次作答不一致，未展示正确答案。')


def _feedback(receipt, frozen, catalog, evolution, observer):
    config = receipt['config']
    key = config['question_key']
    if key.startswith('evolution_'):
        saved = evolution.get_question(key, include_private=False)
        _same_question(frozen, saved, config)
        source = saved.get('provenance', {}).get('source_identity')
        expected = saved.get('observation', {}).get('content_hash')
        frozen_source = frozen.get('provenance', {}).get('source_identity', source)
        frozen_hash = frozen.get('observation', {}).get('content_hash', expected)
        if (not source or not expected or source != frozen_source or expected != frozen_hash
                or not observer.config or observer.config.identity != source):
            raise PracticeConflict('知识演化来源或题目版本已变化，未展示新来源的结果。')
        return project_feedback(frozen['public'], observer.question_results(
            saved['public']['id'], expected_question_hash=expected))
    public = catalog.get_question(key, include_private=False)
    _same_question(frozen, public, config)
    private = catalog.get_question(key, include_private=True)
    _same_question(frozen, private, config)
    return project_feedback(frozen['public'], private.get('feedback'))


def task_run_detail(receipt, *, jobs, catalog, evolution, observer):
    from .task_answers import public_task_run
    job = None
    if receipt['mode'] == 'llm':
        job = jobs.get(receipt['job_id'])
        if job.get('kind') != 'rag' or job['config'] != receipt['config']:
            raise ValueError('Task job differs from its frozen answer receipt')
        # Use one observation of persisted state for both the rendered answer
        # and commitment gate, including during a worker's final state update.
        class FrozenJob:
            def get(self, identifier):
                return job
        shown = public_task_run(receipt, FrozenJob())
    else:
        shown = public_task_run(receipt, jobs)
    frozen, notice = _frozen_record(receipt['config'])
    shown['question_record'] = frozen
    if notice:
        shown['question_notice'] = notice
    selected = _committed_choice(receipt, shown, frozen['public'], job)
    review = {'status': 'not_committed', 'feedback_released': False,
              'notice': '本次作答尚未提交有效答案；未读取正确答案或训练结果。'}
    if selected:
        review['selected_answer'] = selected
        try:
            feedback = _feedback(receipt, frozen, catalog, evolution, observer)
            _, by_letter = _choice_mapping(frozen['public'])
            correct = by_letter.get(feedback.get('correct_letter'))
            review.update(status='revealed', feedback_released=True, correct_answer=correct,
                          correct=selected['id'] == correct['id'] if correct else None, feedback=feedback,
                          notice='仅对照本次已提交答案与来源保存的训练结果，不计作独立评测。' if correct else
                                 '来源尚未保存可确认的正确答案，未推断答案。')
        except (PracticeConflict, ValueError, TypeError):
            review.update(status='identity_conflict', notice='保存的题目或结果未通过身份校验；保留原作答，未展示正确答案。')
        except (KeyError, OSError, RuntimeError):
            review.update(status='unavailable', notice='该题保存的训练结果暂不可用；保留原作答，未推断正确答案。')
    shown['review'] = review
    return shown
