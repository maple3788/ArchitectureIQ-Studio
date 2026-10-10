"""Selected library KB is frozen, bounded, and separate from local practice memory."""
import copy
import json

import pytest

from architecture_iq.kb.experience import ExperienceStore
from architecture_iq.kb.orchestrator import prepare_run, run_round
from architecture_iq.kb.store import canonical_hash, KBStore
from architecture_iq.studio.execution import preview_evaluation
from architecture_iq.studio.knowledge import knowledge_inventory, resolve_initial_knowledge
from architecture_iq.studio.workflow import compile_workflow, default_workflow, validate_workflow
from test_basic_learning import practice_inputs
from test_kb_experience import MemoryClient
from test_kb_workflow_orchestrator import Backend
from test_studio_knowledge import practice_job


def initial_library(tmp_path):
    store, _, _ = practice_job(tmp_path / 'library', rounds=1)
    item = knowledge_inventory(store, [])['items'][0]
    return resolve_initial_knowledge({'id': item['id'], 'version': item['version']}, {'items': [item]})


def reference(initial):
    return {key: initial[key] for key in ('id', 'version')}


def body_with_initial(tmp_path, monkeypatch):
    from test_studio_api import task_preview_setup
    # Create the source before the preview fixture forbids prepare_run side effects.
    initial = initial_library(tmp_path)
    client, app, body, data, _ = task_preview_setup(tmp_path, monkeypatch, enabled=False, execute=True)
    monkeypatch.setattr('architecture_iq.studio.knowledge.knowledge_inventory', lambda *a: {'items': [initial]})
    body['workflow'] = default_workflow()
    body['workflow']['settings'].update(model_id='glm', question_set_id=data['id'], initial_kb=reference(initial))
    return client, app, body, initial


@pytest.mark.parametrize('value', [None, {}, {'id': 'entry', 'version': 'a' * 64}])
def test_selector_accepts_only_optional_catalog_references(value):
    import jsonschema
    from pathlib import Path
    workflow = default_workflow()
    workflow['settings']['initial_kb'] = value
    assert validate_workflow(workflow)['valid']
    assert 'initial_kb' not in compile_workflow(workflow)['config']
    schema = json.loads((Path(__file__).parents[1] / 'contracts/kb_workflow.schema.json').read_text())
    jsonschema.validate(workflow, schema)


@pytest.mark.parametrize('value', [False, '', ['x'], {'id': 'x'}, {'id': 'x', 'version': 'invalid'},
    {'id': 'x', 'version': 'a' * 64, 'snapshot': {}}, {'id': '', 'version': 'a' * 64}])
def test_selector_rejects_inline_content_and_malformed_identity(value):
    workflow = default_workflow()
    workflow['settings']['initial_kb'] = value
    assert not validate_workflow(workflow)['valid']


def test_api_freezes_exact_library_snapshot_and_previews_actual_memory(tmp_path, monkeypatch):
    client, app, body, initial = body_with_initial(tmp_path, monkeypatch)
    response = client.post('/api/studio/runs/preview', json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['initial_kb'] == {k: initial[k] for k in ('id', 'name', 'kind', 'version', 'counts')}
    memory = preview['requests'][0]['initial_experience']
    assert len(memory['lessons']) == 1
    assert memory['examples'] == []
    assert memory['source_policy'] == 'selected_initial_lessons_only'
    assert memory['independent_evaluation'] is False
    assert 'correct_letter' not in response.text and 'GT_SECRET' not in response.text
    assert not app.state.jobs.list()
    response = client.post('/api/studio/runs', json={**body, 'expected_config_hash': preview['config_hash']})
    assert response.status_code == 200, response.text
    frozen = app.state.jobs.get(response.json()['id'])['config']['initial_kb']
    assert frozen == initial
    initial['snapshot']['lessons'][0]['text'] = 'changed after submission'
    assert app.state.jobs.get(response.json()['id'])['config']['initial_kb'] == frozen


@pytest.mark.parametrize('change', ['missing', 'version', 'tampered', 'no_active'])
def test_api_rejects_stale_or_invalid_library_before_run(tmp_path, monkeypatch, change):
    client, app, body, initial = body_with_initial(tmp_path, monkeypatch)
    if change == 'missing':
        body['workflow']['settings']['initial_kb']['id'] = 'missing'
    elif change == 'version':
        body['workflow']['settings']['initial_kb']['version'] = '0' * 64
    elif change == 'tampered':
        initial['snapshot']['lessons'][0]['text'] = 'tampered'
    else:
        initial['snapshot']['lessons'][0]['status'] = 'retired'
        initial['version'] = initial['snapshot']['version'] = canonical_hash({k: v for k, v in initial['snapshot'].items() if k != 'version'})
        body['workflow']['settings']['initial_kb'] = reference(initial)
    response = client.post('/api/studio/runs/preview', json=body)
    assert response.status_code == 422, response.text
    assert not app.state.jobs.list()


def test_start_rechecks_selection_version_after_preview(tmp_path, monkeypatch):
    client, app, body, initial = body_with_initial(tmp_path, monkeypatch)
    preview = client.post('/api/studio/runs/preview', json=body).json()
    initial['version'] = 'f' * 64
    result = client.post('/api/studio/runs', json={**body, 'expected_config_hash': preview['config_hash']})
    assert result.status_code == 422
    assert not app.state.jobs.list()


@pytest.mark.parametrize('previous', [True, False])
@pytest.mark.parametrize('same_question', [True, False])
def test_initial_lessons_reach_every_solver_separate_from_current_loop(tmp_path, previous, same_question):
    initial = initial_library(tmp_path)
    config, questions, private, legacy = practice_inputs(use_previous_experience=previous, initial_kb=initial)
    if not same_question:
        questions[0].update(id='new-q', dataset_id='new-d', lineage_id='new-l')
        private = {'new-q': private['q1']}
    target = tmp_path / 'target'
    prepare_run(target, config, questions, private, legacy)
    before = ExperienceStore(target / 'experience').current()
    assert before['lessons'] == before['episodes'] == []
    model = MemoryClient()
    run_round(target, model, Backend(), round_index=1)
    run_round(target, model, Backend(), round_index=2)
    for i in (0, 2):
        payload = json.loads(model.prompts[i].split('DATA:\n')[1])
        assert payload['initial_experience']['lessons'] == initial['snapshot']['lessons']
        assert payload['initial_experience']['examples'] == []
        assert payload['initial_experience']['prior_related_feedback'] == same_question
        assert ('experience' in payload) == previous
    first = json.loads(model.prompts[0].split('DATA:\n')[1])
    if previous:
        assert first['experience']['lessons'] == []
        assert len(json.loads(model.prompts[2].split('DATA:\n')[1])['experience']['lessons']) == 1
    assert 'correct_letter' not in model.prompts[0] and 'GT_SECRET' not in model.prompts[0]
    # External IDs and receipts never become entries owned by the new local store.
    own = ExperienceStore(target / 'experience').current()
    assert len(own['episodes']) == 2
    assert all(e['question']['id'] == questions[0]['id'] for e in own['episodes'])
    assert KBStore(target / 'kb').current()['claims'] == []


def test_initial_library_family_filter_and_budget_are_visible(tmp_path):
    from architecture_iq.kb.orchestrator import _initial_experience_payload
    initial = initial_library(tmp_path)
    config, questions, *_ = practice_inputs(initial_kb=initial)
    base = {'question': questions[0], 'knowledge': []}
    normal = _initial_experience_payload(base, config)['initial_experience']
    assert normal['lessons']
    clipped = _initial_experience_payload(base, {**config, 'experience_byte_budget': 1})['initial_experience']
    assert clipped['lessons'] == [] and clipped['omitted']['lessons'] == 1
    other = {**base, 'question': {**questions[0], 'family': 'another_family'}}
    filtered = _initial_experience_payload(other, config)['initial_experience']
    assert filtered['lessons'] == [] and filtered['excluded']['lessons_with_excluded_sources'] == 1


@pytest.mark.parametrize('previous', [True, False])
def test_initial_library_first_preview_equals_wire_prompt(tmp_path, previous):
    from test_studio_execution import fixture_config
    initial = initial_library(tmp_path)
    config = fixture_config()
    config['workflow'] = default_workflow()
    config['workflow']['settings'].update(initial_kb=reference(initial), use_previous_experience=previous)
    compiled = compile_workflow(config['workflow'])
    config.update(method=compiled['method'], initial_kb=initial, prompt='')
    config['question_set']['questions'][0]['split'] = 'discovery'
    expected = preview_evaluation(config)['requests'][0]['payload']['messages'][0]['content']
    native = compiled['config']
    native.update(model={'name': 'glm', 'max_tokens': 64, 'temperature': 0.0, 'top_p': 1.0, 'extra': {}},
                  runtime_fingerprint='test', initial_kb=initial)
    out = tmp_path / 'target'
    prepare_run(out, native, config['question_set']['questions'], config['question_set']['feedback'], [])
    model = MemoryClient()
    run_round(out, model, Backend(), round_index=1)
    assert model.prompts[0] == expected


def test_legacy_records_cannot_be_silently_enabled_by_selection(tmp_path):
    snapshot = KBStore(tmp_path / 'legacy').initialize([{'id': 'old', 'text': 'Imported heuristic'}])
    item = {'id': 'historical', 'name': '历史导入', 'kind': 'formal', 'version': snapshot['version'],
            'source': str(tmp_path / 'legacy'), 'sources': [], 'counts': {}, 'snapshot': snapshot}
    with pytest.raises(ValueError, match='没有已验证且启用'):
        resolve_initial_knowledge(reference(item), {'items': [item]})
    assert KBStore(tmp_path / 'legacy').current()['claims'][0]['enabled'] is False


def test_verified_formal_rules_keep_evidence_and_scope_gates_without_importing_authority(tmp_path, monkeypatch):
    from test_kb_workflow_store import claim, patch, confirmed_envelope
    from test_kb_workflow_evidence import record
    from architecture_iq.kb.orchestrator import _knowledge
    import architecture_iq.kb.store as store_module
    scope = confirmed_envelope()
    # Only the source-file verifier is mocked; real publication thresholds and
    # claim-evidence binding are exercised before library selection.
    monkeypatch.setattr(store_module, 'verify_evidence_sources', lambda *a, **k: {'sampling_envelope': scope})
    evidence = [record(i, plan_hash='1' * 64) for i in range(48)]
    store = KBStore(tmp_path / 'formal')
    proposed = claim(rule={'predict': {'lower_better': 'width'}}, status='replicated_in_scope',
                     enabled=True, evidence_ids=[e['id'] for e in evidence])
    snapshot = store.apply_patch(patch(store.initialize([]), {'op': 'upsert', 'claim': proposed, 'reason': 'confirmed'}), evidence)
    item = {'id': 'verified', 'kind': 'formal', 'name': '已验证宽度规律', 'snapshot': snapshot,
            'version': snapshot['version'], 'source': str(tmp_path / 'formal'), 'sources': [], 'counts': {'verified_enabled': 1}}
    initial = resolve_initial_knowledge(reference(item), {'items': [item]})
    config, questions, private, legacy = practice_inputs(initial_kb=initial, use_previous_experience=False)
    question = questions[0]
    question['profile_hash'] = scope['profile_hash']
    for i, choice in enumerate(question['choices']):
        model = {'type': 'mlp', 'width': 16 * (i + 1), 'depth': 2, 'activation': 'relu',
                 'residual': False, 'layer_norm': [False, False]}
        choice['view'].update(model_type='mlp', width=model['width'], budget=1024, batch_size=32,
            opt='adam', opt_key=json.dumps({'type': 'adam', 'lr': .001}),
            loss_key=json.dumps({'loss_id': 'mse'}), arch_key=json.dumps(model))
    assert len(_knowledge(question, initial['snapshot']['claims'])) == 1
    from test_studio_execution import fixture_config
    preview_config = fixture_config()
    preview_config['workflow'] = default_workflow()
    preview_config['workflow']['settings'].update(initial_kb=reference(initial), use_previous_experience=False)
    preview_config.update(method=compile_workflow(preview_config['workflow'])['method'], initial_kb=initial, prompt='')
    preview_config['question_set'].update(questions=questions, feedback=private)
    preview_config['question_set']['questions'][0]['split'] = 'discovery'
    expected = preview_evaluation(preview_config)['requests'][0]['payload']['messages'][0]['content']
    out = tmp_path / 'target'
    prepare_run(out, config, questions, private, legacy)
    model = MemoryClient()
    result = run_round(out, model, Backend(), round_index=1)
    wire = json.loads(model.prompts[0].split('DATA:\n')[1])
    assert model.prompts[0] == expected
    assert wire['knowledge'][0]['id'] == proposed['id']
    assert wire['knowledge'][0]['status'] == 'replicated_in_scope'
    assert result['answers']['q1']['knowledge_count'] == 1
    assert KBStore(out / 'kb').current()['claims'] == []
    assert store.current() == snapshot
    question['profile_hash'] = 'out-of-scope'
    assert _knowledge(question, initial['snapshot']['claims']) == []
    forged = copy.deepcopy(item)
    forged['snapshot']['evidence'] = []
    forged['version'] = forged['snapshot']['version'] = canonical_hash({k: v for k, v in forged['snapshot'].items() if k != 'version'})
    with pytest.raises(ValueError, match='evidence'):
        resolve_initial_knowledge(reference(forged), {'items': [forged]})


def test_initial_and_loop_memory_share_one_content_budget(tmp_path):
    initial = initial_library(tmp_path)
    config, questions, private, legacy = practice_inputs(initial_kb=initial, experience_byte_budget=600)
    target = tmp_path / 'target'
    prepare_run(target, config, questions, private, legacy)
    model = MemoryClient()
    run_round(target, model, Backend(), round_index=1)
    run_round(target, model, Backend(), round_index=2)
    payload = json.loads(model.prompts[2].split('DATA:\n')[1])
    memory = payload['initial_experience']
    own = payload['experience']
    assert memory['content_bytes'] + own['content_bytes'] <= 600
    assert own['byte_budget'] <= 600 - memory['content_bytes']
    assert own['omitted']['lessons'] >= 1
    assert len(model.prompts[2].encode()) + config['model']['max_tokens'] + 256 <= config['context_size']
