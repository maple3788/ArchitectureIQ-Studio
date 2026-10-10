import copy
import json

import pytest

from rag_fixtures import make_rag_case, experience_library


def prepare(case, inventory=None):
    from architecture_iq.studio.rag import prepare_rag
    return prepare_rag(case['catalog'], case['models'], inventory if inventory is not None else case['inventory'],
                       **case['selection'], allowed_roots=[case['state_root'].parent])


def test_preview_contains_only_public_exact_input_without_calls(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: pytest.fail('unexpected network'))
    config, preview = prepare(case)
    assert preview['sent'] is False and preview['can_answer'] is True
    assert preview['request']['payload'] == config['request']['payload']
    assert len(config['retrieval']['knowledge']) == 1
    assert not any(word in json.dumps(config) for word in ('correct_letter', 'feedback', 'episodes'))
    assert not case['jobs'].list()
    assert preview['preview_hash'] == prepare(case)[1]['preview_hash']


def test_empty_library_and_no_match_have_distinct_block_reasons(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    for inventory, reason in [({'items': []}, 'empty_library'),
        ({'items': [experience_library(tmp_path / 'other', text='Zebras dance.') ]}, 'no_match')]:
        config, preview = prepare(case, inventory)
        assert preview['blocked_reason'] == reason
        assert preview['can_answer'] is False and preview['request'] is None


def test_budget_omits_whole_records_and_rejects_zero_knowledge(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    item = case['inventory']['items'][0]
    from architecture_iq.kb.experience import ExperienceStore
    from pathlib import Path
    store = ExperienceStore(Path(item['source']).parents[1])
    snapshot = store.publish(item['version'], [], [{'op': 'add', 'text': 'ReLU ' * 350,
        'conditions': [], 'exceptions': [], 'source_episode_ids': [item['snapshot']['episodes'][0]['id']], 'reason': 'test'}])
    item.update(version=snapshot['version'], snapshot=snapshot,
                source=str(store.root / 'snapshots' / (snapshot['version'] + '.json')))
    profile = case['models'].get('glm')
    profile.pop('revision', None)
    case['models'].save({**profile, 'context_size': 5100})
    config, preview = prepare(case)
    assert config['retrieval']['omitted']['budget'] >= 1
    assert preview['reserved_tokens'] <= 5100
    assert len(config['retrieval']['knowledge']) == 1
    assert 'ReLU ' * 350 not in preview['request']['payload']['messages'][0]['content']
    case['models'].save({**profile, 'context_size': 1024})
    with pytest.raises(ValueError, match='预算|上下文'):
        prepare(case)


def executable(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    case['config'], case['preview'] = prepare(case)
    case['job'] = case['jobs'].create('rag', case['config'])
    return case


def execute(case, **options):
    from architecture_iq.studio.rag import execute_rag
    from rag_fixtures import rag_client
    return execute_rag(case['jobs'], case['job']['id'], case['config'], client_factory=rag_client(case, **options))


def test_wire_equals_preview_and_completed_call_replays_once(tmp_path, monkeypatch):
    case = executable(tmp_path, monkeypatch)
    monkeypatch.setattr('architecture_iq.kb.evaluation.score_evaluation', lambda *a, **k: pytest.fail('GT scoring forbidden'))
    result = execute(case)
    assert execute(case) == result and len(case['calls']) == 1
    record = case['jobs'].get(case['job']['id'])['records'][0]
    assert record['actual_request']['payload'] == case['preview']['request']['payload']
    assert result['answer']['ranking'] == ['A', 'B', 'C']
    assert not {'scores', 'feedback', 'correct'} & result.keys()
    serialized = json.dumps([result, record, case['jobs'].events(case['job']['id'])])
    assert 'correct_letter' not in serialized
    assert (case['jobs'].directory(case['job']['id']) / 'retrieval.json').exists()


def test_unknown_citations_are_flagged_not_resolved(tmp_path, monkeypatch):
    case = executable(tmp_path, monkeypatch)
    result = execute(case, citations=['unknown-id'])
    assert result['answer']['invalid_citations'] is True
    assert result['used_sources'] == [] and result['unknown_citations'] == ['unknown-id']


def test_invalid_ranking_preserves_raw_response_and_fails(tmp_path, monkeypatch):
    case = executable(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='ranking|回答'):
        execute(case, ranking=['A', 'A', 'C'])
    record = case['jobs'].get(case['job']['id'])['records'][0]
    assert record['status'] == 'invalid' and record['raw']['choices']
    with pytest.raises(ValueError): execute(case)
    assert len(case['calls']) == 1


def test_timeout_after_send_is_uncertain_and_never_retried(tmp_path, monkeypatch):
    case = executable(tmp_path, monkeypatch)
    with pytest.raises(TimeoutError): execute(case, error=TimeoutError('timed out'))
    assert case['jobs'].get(case['job']['id'])['records'][0]['status'] == 'uncertain'
    with pytest.raises(RuntimeError, match='never repeat'): execute(case)
    assert len(case['calls']) == 1


def test_api_alias_is_recorded_but_self_hosted_identity_is_strict(tmp_path, monkeypatch):
    case = executable(tmp_path / 'local', monkeypatch)
    with pytest.raises(RuntimeError, match='identity'): execute(case, response_model='alias')
    case = make_rag_case(tmp_path / 'api', monkeypatch)
    from test_studio_api_models import api_profile
    case['models'].save(api_profile(), api_key='private-key')
    case['selection']['model_id'] = 'cloud'
    case['config'], case['preview'] = prepare(case)
    case['job'] = case['jobs'].create('rag', case['config'])
    assert execute(case, response_model='alias')['response_model'] == 'alias'


def test_rag_worker_dispatch_preserves_matching_artifact(tmp_path, monkeypatch):
    case = executable(tmp_path, monkeypatch)
    from rag_fixtures import rag_client
    monkeypatch.setattr('architecture_iq.studio.execution.create_client', rag_client(case))
    from architecture_iq.studio.execution import worker
    worker(case['state_root'], case['job']['id'])
    job = case['jobs'].get(case['job']['id'])
    assert job['status'] == 'complete' and job['result']['retrieval'] == case['config']['retrieval']
    worker(case['state_root'], job['id'])
    assert len(case['calls']) == 1


def test_new_route_source_changes_job_fingerprint(tmp_path, monkeypatch):
    from architecture_iq.studio.jobs import source_fingerprint
    from pathlib import Path
    original = Path.read_bytes
    def read(path):
        data = original(path)
        return data + b'\n# changed' if path.name == '__init__.py' and path.parent.name == 'kb_workflow_api' else data
    before = source_fingerprint()
    monkeypatch.setattr(Path, 'read_bytes', read)
    assert source_fingerprint() != before


def test_split_reflected_api_secret_is_redacted_in_rag_stream_and_records(tmp_path, monkeypatch):
    import io
    from test_studio_api_models import api_profile
    from architecture_iq.studio.rag import execute_rag
    case = make_rag_case(tmp_path, monkeypatch)
    secret = 'split-private-key'
    case['models'].save(api_profile(), api_key=secret)
    case['selection']['model_id'] = 'cloud'
    config, _ = prepare(case)
    job = case['jobs'].create('rag', config)
    text = json.dumps({'ranking': ['A', 'B', 'C'], 'citations': [], 'rationale': secret})
    pieces = text.split('private')
    chunks = [pieces[0], 'private' + pieces[1]]
    frames = [{'model': 'alias', 'choices': [{'index': 0, 'delta': {'content': t}, 'finish_reason': None}]} for t in chunks]
    frames.append({'model': 'alias', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
    def opened(request, **kwargs):
        assert request.get_header('Authorization') == 'Bearer ' + secret
        case['calls'].append(request)
        return io.BytesIO((''.join('data: ' + json.dumps(f) + '\n\n' for f in frames) + 'data: [DONE]\n\n').encode())
    monkeypatch.setattr('urllib.request.urlopen', opened)
    result = execute_rag(case['jobs'], job['id'], config)
    assert result['answer']['rationale'] == '[redacted]'
    assert len(case['calls']) == 1
    for path in case['jobs'].directory(job['id']).rglob('*'):
        if path.is_file() and path.suffix in {'.json', '.jsonl'}:
            assert secret not in path.read_text()
