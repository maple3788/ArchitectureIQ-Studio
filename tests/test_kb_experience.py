import copy
import importlib.util
import json

import pytest

from architecture_iq.kb.roles import _seal
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from tests.test_kb_workflow_orchestrator import inputs, Client, Backend
from architecture_iq.kb.orchestrator import prepare_run, run_round, evaluate_run


def api():
    assert importlib.util.find_spec('architecture_iq.kb.experience'), 'Empirical store is missing'
    from architecture_iq.kb.experience import ExperienceStore, build_episode
    from architecture_iq.kb.retrieval import retrieve_experience
    return ExperienceStore, build_episode, retrieve_experience


def fixture_episode(tmp_path):
    Store, build, retrieve = api()
    config, questions, private, legacy = inputs()
    prepare_run(tmp_path, config, questions, private, legacy)
    q = json.loads((tmp_path / 'public_questions.json').read_text())[0]
    answer_path = tmp_path / f"rounds/1/answers/{canonical_hash(q['id'])}.json"
    feedback_path = tmp_path / f"rounds/1/revealed/{canonical_hash(q['id'])}.json"
    write_json_atomic(answer_path, _seal({'result': {'valid': True, 'ranking': list('BAC'), 'raw': {'private': 'large'}}}))
    write_json_atomic(feedback_path, _seal({'result': {'question_id': q['id'], 'feedback': private[q['id']]}}))
    episode = build(tmp_path, round_index=1, question=q, answer_path=answer_path, feedback_path=feedback_path)
    return Store(tmp_path / 'experience'), episode, retrieve


def add(episode, **extra):
    return {'op': 'add', 'text': 'Compare width under adequate training.', 'conditions': ['adequate training'],
            'exceptions': ['small budget'], 'source_episode_ids': [episode['id']], 'reason': 'observed discovery', **extra}


def test_store_versions_and_idempotent_publication(tmp_path):
    store, episode, _ = fixture_episode(tmp_path)
    first = store.initialize()
    snap = store.publish(first['version'], [episode], [add(episode)])
    assert snap['parent_version'] == first['version']
    assert snap == store.publish(first['version'], [episode], [add(episode)])
    lesson = snap['lessons'][0]
    revised = store.publish(snap['version'], [], [{'op': 'edit', 'id': lesson['id'], 'text': 'Revised conditional lesson.',
        'conditions': [], 'exceptions': ['narrow networks'], 'source_episode_ids': [episode['id']], 'reason': 'qualification'}])
    assert revised['lessons'][0]['revision'] == 2
    assert revised['lessons'][0]['parent_revision'] == 1
    assert store.current() == revised
    with pytest.raises(ValueError, match='parent'):
        store.publish(first['version'], [], [])


@pytest.mark.parametrize('mutation', ['held_out', 'unsealed', 'forged_source', 'private_payload'])
def test_admission_rejects_ineligible_or_forged_episode(tmp_path, mutation):
    store, episode, _ = fixture_episode(tmp_path)
    first = store.initialize()
    if mutation == 'held_out':
        episode['question']['split'] = 'final'
    elif mutation == 'unsealed':
        episode.pop('seal_hash')
    elif mutation == 'forged_source':
        episode['source_refs']['answer']['path'] = '../outside.json'
    else:
        episode['feedback']['private_test_answers'] = ['A']
    with pytest.raises(ValueError):
        store.publish(first['version'], [episode], [])


def test_episode_compactness_and_source_integrity(tmp_path):
    store, episode, _ = fixture_episode(tmp_path)
    assert 'raw' not in episode['answer']
    assert episode['feedback'] == {'correct_letter': 'B'}
    source = tmp_path / episode['source_refs']['answer']['path']
    source.write_text('{}')
    with pytest.raises(ValueError, match='integrity|source'):
        store.publish(store.initialize()['version'], [episode], [])


def test_lesson_sources_required_and_cannot_become_scientific_claim(tmp_path):
    store, episode, _ = fixture_episode(tmp_path)
    first = store.initialize()
    with pytest.raises(ValueError, match='source'):
        store.publish(first['version'], [episode], [add(episode, source_episode_ids=['invented'])])
    snap = store.publish(first['version'], [episode], [add(episode, enabled=True, verified=True, scientific_status='replicated_in_scope')])
    lesson = snap['lessons'][0]
    assert snap['scientific_status'] == lesson['scientific_status'] == 'unverified'
    assert 'enabled' not in lesson and 'verified' not in lesson
    from architecture_iq.kb.orchestrator import _knowledge
    assert _knowledge(episode['question'], [lesson]) == []


@pytest.mark.parametrize('field', ['id', 'dataset_id', 'lineage_id', 'pair_id'])
def test_retrieval_filters_related_examples_and_lessons(tmp_path, field):
    store, episode, retrieve = fixture_episode(tmp_path)
    episode['question']['pair_id'] = 'pair-one'
    # Rebuild against frozen source rather than permitting caller modifications.
    public = json.loads((tmp_path / 'public_questions.json').read_text())
    public[0]['pair_id'] = 'pair-one'
    write_json_atomic(tmp_path / 'public_questions.json', public)
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['inputs']['public_questions.json'] = canonical_hash(public)
    write_json_atomic(tmp_path / 'manifest.json', manifest)
    _, build, _ = api()
    episode = build(tmp_path, round_index=1, question=public[0],
        answer_path=tmp_path / episode['source_refs']['answer']['path'], feedback_path=tmp_path / episode['source_refs']['feedback']['path'])
    snap = store.publish(store.initialize()['version'], [episode], [add(episode)])
    q = {'id': 'new', 'dataset_id': 'new-data', 'lineage_id': 'new-lineage', 'pair_id': 'new-pair', 'family': public[0]['family']}
    q[field] = episode['question'][field]
    result = retrieve(q, snap, mode='combined', byte_budget=10000)
    assert result['examples'] == result['lessons'] == []


def test_deterministic_clipping_and_modes(tmp_path):
    store, episode, retrieve = fixture_episode(tmp_path)
    snap = store.publish(store.initialize()['version'], [episode], [add(episode)])
    q = {'id': 'new', 'dataset_id': 'new-data', 'lineage_id': 'new-lineage', 'family': episode['question']['family']}
    for mode in ('examples', 'lessons', 'combined'):
        result = retrieve(q, snap, mode=mode, byte_budget=10000)
        assert result == retrieve(q, snap, mode=mode, byte_budget=10000)
        assert result['content_bytes'] <= result['byte_budget']
    result = retrieve(q, snap, mode='combined', byte_budget=1)
    assert result['examples'] == result['lessons'] == []
    assert result['omitted'] == {'examples': 1, 'lessons': 1}


class MemoryClient(Client):
    def complete(self, prompt, model):
        if 'You are the experience_curator in' not in prompt:
            return super().complete(prompt, model)
        from types import SimpleNamespace
        self.prompts.append(prompt)
        packet = json.loads(prompt.split('DATA:\n')[1])
        assert len(packet['episodes']) == 1
        ep = packet['episodes'][0]
        operation = add(ep)
        if packet['lessons']:
            operation.update(op='edit', id=packet['lessons'][0]['id'], text='Later revision.')
        return SimpleNamespace(raw={'model': model.name, 'choices': [{'message': {'content': json.dumps({'operations': [operation]})}}]},
                               usage={'prompt_tokens': 100, 'completion_tokens': 100}, finish_reason='stop')


def test_enabled_rounds_freeze_prior_memory_and_replay_consolidation(tmp_path):
    config, questions, private, legacy = inputs()
    config.update(max_rounds=2, experience_mode='expel_inspired')
    second = copy.deepcopy(questions[0]); second.update(id='q2', dataset_id='d2', lineage_id='l2')
    questions.append(second); private['q2'] = copy.deepcopy(private['q1'])
    prepare_run(tmp_path, config, questions, private, legacy)
    client = MemoryClient(); events = []
    first = run_round(tmp_path, client, Backend(), round_index=1, stage_observer=events.append)
    second_result = run_round(tmp_path, client, Backend(), round_index=2)
    solver_packets = [json.loads(p.split('DATA:\n')[1]) for p in client.prompts if 'You are the solver in' in p]
    assert solver_packets[0]['experience']['examples'] == []
    assert solver_packets[1]['experience']['example_ids'] == first['experience']['episode_ids']
    assert solver_packets[1]['experience']['version'] == first['experience']['after']
    assert second_result['experience']['before'] == first['experience']['after']
    provenance = first['experience']['episode_provenance'][first['experience']['episode_ids'][0]]
    assert provenance['question_id'] == 'q1' and provenance['round'] == 1
    assert set(provenance['source_refs']) == {'answer', 'feedback'}
    assert any(e.get('step_id') == 'experience_consolidate' and e['node_id'] == 'discoverer' for e in events)
    consolidated = next(i for i,e in enumerate(events) if e.get('step_id') == 'experience_consolidate' and e['state'] == 'complete')
    curated = next(i for i,e in enumerate(events) if e['node_id'] == 'curator' and e['state'] == 'ready')
    published = next(i for i,e in enumerate(events) if e['node_id'] == 'publish' and e['state'] == 'ready')
    assert consolidated < curated < published
    calls = len(client.prompts)
    assert run_round(tmp_path, client, Backend(), round_index=2) == second_result
    assert len(client.prompts) == calls
    Store, _, _ = api()
    assert Store(tmp_path / 'experience').current()['lessons'][0]['revision'] == 2


def test_off_mode_leaves_payloads_and_arms_unchanged(tmp_path):
    config, questions, private, legacy = inputs()
    final = copy.deepcopy(questions[0]); final.update(id='final', dataset_id='df', lineage_id='lf', split='final')
    questions.append(final); private['final'] = copy.deepcopy(private['q1'])
    config['experience_mode'] = 'off'
    prepare_run(tmp_path, config, questions, private, legacy)
    client = Client(); result = run_round(tmp_path, client, Backend(), round_index=1)
    evaluated = evaluate_run(tmp_path, client, phase='final')
    assert 'experience' not in result and not (tmp_path / 'experience').exists()
    assert set(evaluated['answers']) == {'clean', 'initial', 'current'}
    assert all('"experience"' not in prompt for prompt in client.prompts)


def test_enabled_evaluation_adds_frozen_explicit_arms_without_learning(tmp_path):
    config, questions, private, legacy = inputs()
    final = copy.deepcopy(questions[0]); final.update(id='final', dataset_id='df', lineage_id='lf', split='final')
    questions.append(final); private['final'] = copy.deepcopy(private['q1'])
    config['experience_mode'] = 'expel_inspired'
    prepare_run(tmp_path, config, questions, private, legacy)
    client = MemoryClient(); learned = run_round(tmp_path, client, Backend(), round_index=1)
    evaluated = evaluate_run(tmp_path, client, phase='final')
    assert set(evaluated['answers']) == {'clean','initial','current','experience_examples','experience_lessons','experience_combined'}
    assert evaluated['binding']['experience']['version'] == learned['experience']['after']
    assert evaluated['experience_unchanged'] is True
    assert evaluated['usage']['calls'] == 6


def test_reinforce_and_retire_are_revisions_not_verification(tmp_path):
    store, episode, retrieve = fixture_episode(tmp_path)
    snap = store.publish(store.initialize()['version'], [episode], [add(episode)])
    lesson_id = snap['lessons'][0]['id']
    snap = store.publish(snap['version'], [], [{'op': 'reinforce', 'id': lesson_id,
        'source_episode_ids': [episode['id']], 'reason': 'same qualified observation', 'verified': True}])
    assert snap['lessons'][0]['revision'] == 2 and snap['lessons'][0]['scientific_status'] == 'unverified'
    snap = store.publish(snap['version'], [], [{'op': 'retire', 'id': lesson_id,
        'source_episode_ids': [episode['id']], 'reason': 'too narrow'}])
    assert snap['lessons'][0]['status'] == 'retired'
    q = {'id':'new', 'dataset_id':'new-data', 'lineage_id':'new-lineage', 'family':episode['question']['family']}
    assert retrieve(q, snap, mode='lessons', byte_budget=5000)['lessons'] == []


def test_pair_budget_reserves_consolidation_call(tmp_path):
    from tests.test_kb_pair_learning import pair_inputs
    from architecture_iq.kb.pair_learning import pair_call_budget
    config, questions, private, legacy = pair_inputs()
    old = pair_call_budget(config)
    config.update(experience_mode='expel_inspired', max_calls_per_round=old)
    assert pair_call_budget(config) == old + 1
    with pytest.raises(ValueError, match='call'):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_enabled_pair_preserves_stage_boundaries_and_prior_round_only(tmp_path):
    from tests.test_kb_pair_learning import pair_inputs, PairClient
    config, questions, private, legacy = pair_inputs()
    config['experience_mode'] = 'expel_inspired'
    prepare_run(tmp_path, config, questions, private, legacy)
    class MemoryPairClient(PairClient):
        def complete(self, prompt, model):
            if 'You are the experience_curator in' in prompt:
                from types import SimpleNamespace
                packet = json.loads(prompt.split('DATA:\n')[1]); self.packets.append(('experience_curator', packet))
                assert len(packet['episodes']) == 2
                assert {e['relationship']['member_role'] for e in packet['episodes']} == {'original','counterfactual'}
                assert all(e['relationship']['type'] == 'normal_counterfactual_pair' for e in packet['episodes'])
                return SimpleNamespace(raw={'model':model.name,'choices':[{'message':{'content':'{"operations":[]}'}}]},
                                       usage={'prompt_tokens':10,'completion_tokens':10},finish_reason='stop')
            return super().complete(prompt, model)
    client = MemoryPairClient(tmp_path); events = []
    result = run_round(tmp_path, client, lambda *a:[], round_index=1, stage_observer=events.append)
    for role, packet in client.packets:
        if role in {'solver', 'pair_researcher'}:
            assert packet['experience']['examples'] == packet['experience']['lessons'] == []
    steps = {event.get('step_id') for event in events}
    assert {'pair_induction','pair_transfer','pair_revision','experience_consolidate'} <= steps
    assert result['experience']['after_snapshot']['scientific_status'] == 'unverified'


def test_crash_after_experience_publication_never_repeats_curator_call(tmp_path, monkeypatch):
    import architecture_iq.kb.orchestrator as workflow
    config, questions, private, legacy = inputs(); config['experience_mode'] = 'expel_inspired'
    prepare_run(tmp_path, config, questions, private, legacy)
    client = MemoryClient(); saved = workflow._save
    def fail_result(path, value):
        if path.name == 'result.json':
            raise OSError('disk full after publication')
        return saved(path, value)
    monkeypatch.setattr(workflow, '_save', fail_result)
    with pytest.raises(OSError):
        run_round(tmp_path, client, Backend(), round_index=1)
    calls = len(client.prompts)
    monkeypatch.setattr(workflow, '_save', saved)
    result = run_round(tmp_path, client, Backend(), round_index=1)
    assert len(client.prompts) == calls and result['experience']['after_snapshot']['lessons']


def test_other_question_receipt_cannot_be_used_as_episode_answer(tmp_path):
    store, episode, _ = fixture_episode(tmp_path)
    answer_ref = copy.deepcopy(episode['source_refs']['answer'])
    other = tmp_path / 'rounds/1/answers/another-question.json'
    other.write_bytes((tmp_path / answer_ref['path']).read_bytes())
    episode['source_refs']['answer']['path'] = str(other.relative_to(tmp_path))
    episode['seal_hash'] = canonical_hash({k:v for k,v in episode.items() if k != 'seal_hash'})
    with pytest.raises(ValueError, match='source|answer'):
        store.publish(store.initialize()['version'], [episode], [])


def test_third_round_receives_revised_lesson(tmp_path):
    config, questions, private, legacy = inputs()
    config.update(max_rounds=3, experience_mode='expel_inspired')
    for index in (2, 3):
        q = copy.deepcopy(questions[0]); q.update(id=f'q{index}',dataset_id=f'd{index}',lineage_id=f'l{index}')
        questions.append(q); private[q['id']] = copy.deepcopy(private['q1'])
    prepare_run(tmp_path, config, questions, private, legacy)
    client = MemoryClient()
    for index in (1, 2, 3):
        result = run_round(tmp_path, client, Backend(), round_index=index)
    packets = [json.loads(p.split('DATA:\n')[1]) for p in client.prompts if 'You are the solver in' in p]
    assert packets[2]['experience']['lessons'][0]['revision'] == 2
    assert packets[2]['experience']['lessons'][0]['text'] == 'Later revision.'
    assert result['experience']['after_snapshot']['lessons'][0]['revision'] == 3


def test_early_final_evaluation_uses_sealed_completion_and_blocks_learning(tmp_path):
    from architecture_iq.kb.completion import seal_learning_complete
    config, questions, private, legacy = inputs()
    config.update(max_rounds=2, experience_mode='expel_inspired')
    for identifier, split in [('q2','discovery'), ('final','final')]:
        q=copy.deepcopy(questions[0]); q.update(id=identifier,dataset_id='d-'+identifier,lineage_id='l-'+identifier,split=split)
        questions.append(q); private[identifier]=copy.deepcopy(private['q1'])
    manifest=prepare_run(tmp_path, config, questions, private, legacy)
    client=MemoryClient(); first=run_round(tmp_path,client,Backend(),round_index=1)
    seal_learning_complete(tmp_path,manifest,1,reason='finish')
    evaluated=evaluate_run(tmp_path,client,phase='final')
    assert evaluated['binding']['experience']['version'] == first['experience']['after']
    with pytest.raises(RuntimeError,match='complete'):
        run_round(tmp_path,client,Backend(),round_index=2)
    assert run_round(tmp_path,client,Backend(),round_index=1) == first


def test_development_evaluations_do_not_reuse_an_older_memory_version(tmp_path):
    config, questions, private, legacy=inputs();config.update(max_rounds=2,experience_mode='expel_inspired')
    for identifier,split in [('q2','discovery'),('dev','development')]:
        q=copy.deepcopy(questions[0]);q.update(id=identifier,dataset_id='d-'+identifier,lineage_id='l-'+identifier,split=split)
        questions.append(q);private[identifier]=copy.deepcopy(private['q1'])
    prepare_run(tmp_path,config,questions,private,legacy)
    client=MemoryClient();run_round(tmp_path,client,Backend(),round_index=1)
    first=evaluate_run(tmp_path,client,phase='development')
    learned=run_round(tmp_path,client,Backend(),round_index=2)
    second=evaluate_run(tmp_path,client,phase='development')
    assert second['binding']['experience']['version'] == learned['experience']['after']
    assert second['binding']['experience']['version'] != first['binding']['experience']['version']


def test_paired_replay_retains_research_retrieval_provenance(tmp_path, monkeypatch):
    from tests.test_kb_pair_learning import pair_inputs, PairClient
    import architecture_iq.kb.orchestrator as workflow
    from types import SimpleNamespace
    config,questions,private,legacy=pair_inputs();config['experience_mode']='expel_inspired'
    prepare_run(tmp_path,config,questions,private,legacy)
    class NoopCurator(PairClient):
        def complete(self,prompt,model):
            if 'You are the experience_curator in' in prompt:
                return SimpleNamespace(raw={'model':model.name,'choices':[{'message':{'content':'{"operations":[]}'}}]},
                                       finish_reason='stop',usage={'prompt_tokens':10,'completion_tokens':10})
            return super().complete(prompt,model)
    client=NoopCurator(tmp_path);saved=workflow._save
    def fail_result(path,value):
        if path.name == 'result.json':raise OSError('disk full')
        return saved(path,value)
    monkeypatch.setattr(workflow,'_save',fail_result)
    with pytest.raises(OSError):run_round(tmp_path,client,lambda *a:[],round_index=1)
    monkeypatch.setattr(workflow,'_save',saved)
    result=run_round(tmp_path,client,lambda *a:[],round_index=1)
    assert len(result['experience']['retrievals']) == 5
    assert sum(key.startswith('pair_researcher:') for key in result['experience']['retrievals']) == 2
