"""The knowledge library distinguishes stored rules, sources and learning memory."""
import copy
import os

from fastapi.testclient import TestClient

from architecture_iq.kb.orchestrator import prepare_run, run_round
from architecture_iq.kb.store import KBStore, write_json_atomic
from architecture_iq.studio.jobs import JobStore
from architecture_iq.studio.workflow import default_workflow
from services.kb_workflow_api.app import create_app
from test_basic_learning import practice_inputs
from test_kb_experience import MemoryClient
from test_kb_workflow_orchestrator import Backend


def archive(tmp_path, name, claims):
    root = tmp_path / name
    write_json_atomic(root / 'manifest.json', {'name': name})
    snapshot = KBStore(root / 'kb').initialize(claims)
    return root, snapshot


def client(tmp_path):
    return TestClient(create_app(state_root=tmp_path / 'state', execution_enabled=False))


def claims():
    return [
        {'id': 'K1.clause-1', 'source_claim_id': 'K1', 'text': 'First historical rule'},
        {'id': 'K1.clause-2', 'source_claim_id': 'K1', 'text': 'First historical rule'},
        {'id': 'K2', 'source_claim_id': 'K2', 'text': 'Second historical rule'},
    ]


def test_identical_archives_and_run_are_one_snapshot_with_three_provenance_sources(tmp_path, monkeypatch):
    first, snapshot = archive(tmp_path, 'archive-a', claims())
    second, _ = archive(tmp_path, 'archive-b', claims())
    monkeypatch.setenv('STUDIO_ARCHIVES', os.pathsep.join(map(str, [first, second])))
    store = JobStore(tmp_path / 'state')
    run = store.create('workflow', {'name': 'Existing scientific run'})
    write_json_atomic(store.directory(run['id']) / 'result.json', {'kb': snapshot})
    result = client(tmp_path).get('/api/studio/kb').json()
    assert result['total'] == 1
    item = result['items'][0]
    assert item['kind'] == 'formal'
    assert item['source_count'] == 3
    assert {s['path'] for s in item['sources']} == {str(first), str(second), str(store.directory(run['id']) / 'result.json')}
    assert item['name'] == '历史导入知识'
    assert item['counts']['records'] == 3
    assert item['counts']['source_claims'] == 2
    assert item['counts']['split_records'] == 1
    assert item['counts']['legacy_unverified'] == 3
    assert item['counts']['verified_enabled'] == 0
    assert item['snapshot'] == snapshot


def test_equal_record_counts_do_not_collapse_different_knowledge(tmp_path, monkeypatch):
    first, _ = archive(tmp_path, 'archive-a', claims())
    different = copy.deepcopy(claims())
    different[0]['text'] = 'A different explanation'
    second, _ = archive(tmp_path, 'archive-b', different)
    monkeypatch.setenv('STUDIO_ARCHIVES', os.pathsep.join(map(str, [first, second])))
    result = client(tmp_path).get('/api/studio/kb').json()
    assert result['total'] == 2
    assert [x['counts']['records'] for x in result['items']] == [3, 3]
    assert all(x['source_count'] == 1 for x in result['items'])


def practice_job(tmp_path, *, rounds=2):
    config, questions, private, legacy = practice_inputs()
    questions[0]['split'] = 'discovery'
    store = JobStore(tmp_path / 'state')
    job = store.create('workflow', {'workflow': default_workflow(), 'name': '单题学习',
        'question_set': {'questions': questions, 'feedback': private}})
    out = store.directory(job['id']) / 'workflow'
    prepare_run(out, config, questions, private, legacy)
    model = MemoryClient()
    for index in range(1, rounds + 1):
        run_round(out, model, Backend(), round_index=index,
                  stage_observer=lambda event: store.event(job['id'], event))
    store.update(job['id'], status='waiting_round', progress={'round_index': rounds})
    return store, job, out


def test_waiting_manual_loop_exposes_latest_sealed_experience_without_final_job_result(tmp_path, monkeypatch):
    monkeypatch.delenv('STUDIO_ARCHIVES', raising=False)
    store, job, out = practice_job(tmp_path)
    assert not (store.directory(job['id']) / 'result.json').exists()
    response = client(tmp_path).get('/api/studio/kb')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['total'] == 1
    item = result['items'][0]
    assert item['kind'] == 'experience'
    assert item['name'] == '单题学习 · 学习经验'
    assert item['counts'] == {'lessons': 1, 'active_lessons': 1, 'retired_lessons': 0,
                              'episodes': 2, 'verified_enabled': 0}
    assert item['sources'][0]['id'] == job['id']
    assert item['sources'][0]['round_index'] == 2
    assert item['snapshot']['scientific_status'] == 'unverified'


def test_unsealed_or_tampered_experience_is_not_presented_as_saved_knowledge(tmp_path, monkeypatch):
    monkeypatch.delenv('STUDIO_ARCHIVES', raising=False)
    store, job, out = practice_job(tmp_path, rounds=1)
    import json
    pointer = json.loads((out / 'experience/CURRENT.json').read_text())
    path = out / 'experience/snapshots' / (pointer['version'] + '.json')
    value = json.loads(path.read_text())
    value['lessons'][0]['text'] = 'TAMPERED'
    write_json_atomic(path, value)
    response = client(tmp_path).get('/api/studio/kb')
    assert response.status_code == 200, response.text
    assert response.json()['items'] == []
    assert response.json()['warnings']
    assert 'TAMPERED' not in response.text


def test_first_round_empty_memory_is_not_reported_as_a_broken_snapshot(tmp_path, monkeypatch):
    monkeypatch.delenv('STUDIO_ARCHIVES', raising=False)
    practice_job(tmp_path, rounds=0)
    response = client(tmp_path).get('/api/studio/kb').json()
    assert response['items'] == []
    assert response['warnings'] == []


def test_corrupted_latest_round_keeps_last_valid_memory_but_reports_the_gap(tmp_path, monkeypatch):
    monkeypatch.delenv('STUDIO_ARCHIVES', raising=False)
    _, _, out = practice_job(tmp_path)
    import json
    pointer = json.loads((out / 'experience/CURRENT.json').read_text())
    path = out / 'experience/snapshots' / (pointer['version'] + '.json')
    value = json.loads(path.read_text())
    value['lessons'][0]['text'] = 'CORRUPTED_LATEST'
    write_json_atomic(path, value)
    response = client(tmp_path).get('/api/studio/kb').json()
    assert response['items'][0]['counts']['episodes'] == 1
    assert response['items'][0]['sources'][0]['round_index'] == 1
    assert response['warnings']
    assert 'CORRUPTED_LATEST' not in str(response)
