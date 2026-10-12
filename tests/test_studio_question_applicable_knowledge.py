"""Before-answer applicability only reads public inputs and rule content."""
from copy import deepcopy
import pytest

from test_studio_knowledge_questions import api_case
from test_studio_human_practice import evolution
from rule_refinement_fixtures import raw_case, rule_entry


def request(client, source, **extra):
    return client.post('/api/studio/questions/applicable-knowledge', json={'source': source, **extra})


def source_for(case, qid='q_match'):
    rows = case['app'].state.catalog.list_questions()['items']
    return {'kind': 'catalog', 'key': next(row['key'] for row in rows if row['id'] == qid)}


def test_public_applicability_has_rules_conditions_and_unordered_pairs_without_answers(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    catalog = case['app'].state.catalog
    original = catalog.get_question
    def public_only(key, *, include_private=False):
        assert include_private is False
        return original(key, include_private=False)
    monkeypatch.setattr(catalog, 'get_question', public_only)
    response = request(case['client'], source_for(case))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['scope'] == 'public_applicability' and result['feedback_released'] is False
    assert result['total'] == 1
    item = result['items'][0]
    assert item['kb']['id'] == 'kb' and item['kb']['verification'] == 'research_hypothesis'
    first = next(rule for rule in item['rules'] if rule['text'] == 'Prefer wider models in this scope')
    assert first['conditions'] and first['revision']
    assert first['matched_pairs'][0]['candidates'] == [{'id': 'c_A', 'letter': 'A'}, {'id': 'c_B', 'letter': 'B'}]
    assert first['matched_pairs'][0]['reasons']
    for prohibited in ('correct_letter', 'answer_id', 'winner', 'loser', 'support', 'refute',
                       'feedback_hash', 'seed_results', 'dev_evidence', '/private/'):
        assert prohibited not in response.text
    assert not case['app'].state.tasks.list() and not case['app'].state.jobs.list()


def test_nonmatching_public_scope_returns_empty_with_notice(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch, rules=[rule_entry((999,))['rule']])
    # Remove the separately matching sibling while retaining the real sealed snapshot.
    snapshot = case['store'].import_rules({'schema_version': 'kb_claim_rules_v1', 'claims': [
        {'id': 'C1', 'text': 'Outside scope', 'rules': [rule_entry((999,))['rule']]}]}, source_ref={'id': 'scope'})
    case['item'].update(snapshot=snapshot, version=snapshot['version'])
    result = request(case['client'], source_for(case)).json()
    assert result['items'] == [] and result['total'] == 0 and result['notice']


def test_latest_library_default_but_explicit_older_reference_is_honored(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    old = case['item']
    old['library'] = {'id': 'library', 'version_order': 1}
    new = {**deepcopy(old), 'id': 'new-kb', 'name': 'Newer', 'library': {'id': 'library', 'version_order': 2}}
    case['inventory']['items'] = [old, new]
    default = request(case['client'], source_for(case)).json()
    assert [item['kb']['id'] for item in default['items']] == ['new-kb']
    pinned = request(case['client'], source_for(case), knowledge_ref={'id': old['id'], 'version': old['version']}).json()
    assert [item['kb']['id'] for item in pinned['items']] == ['kb']


def test_evolution_applicability_uses_seen_snapshot_without_reading_results(evolution):
    client, observer, source, _, result_calls = evolution
    before = observer.capture(**source['observation'])
    response = request(client, source)
    assert response.status_code == 200, response.text
    items = [row for row in response.json()['items'] if row['kb'].get('source_kind') == 'knowledge_evolution']
    assert len(items) == 1 and items[0]['rules'][0]['text'] == 'Greater width wins in scope'
    assert items[0]['rules'][0]['source_status'] == 'candidate'
    assert result_calls == [] and observer.capture(**source['observation']) == before
    for forbidden in ('SECRET_GT', 'correct_letter', 'candidate_metrics', 'winner', 'support', 'refute', '/private/'):
        assert forbidden not in response.text
    assert client.get('/api/studio/tasks').json()['items'] == []


@pytest.mark.parametrize('change', ['source', 'sequence', 'hash'])
def test_evolution_reference_changes_are_conflicts(evolution, change):
    client, _, source, _, calls = evolution
    value = deepcopy(source)
    if change == 'source': value['observation']['source_identity'] = '0' * 64
    elif change == 'sequence': value['observation']['sequence'] = 999
    else: value['expected_question_hash'] = '0' * 64
    assert request(client, value).status_code == 409
    assert calls == []


def test_frozen_evolution_catalog_key_accepts_exact_selected_kb(evolution):
    client, observer, source, _, calls = evolution
    selected = client.post('/api/studio/tasks/evolution/selection', json={
        'observation': source['observation'], 'question_id': source['question_id'],
        'expected_question_hash': source['expected_question_hash']}).json()
    response = request(client, {'kind': 'catalog', 'key': selected['question_key']},
                       knowledge_ref=selected['kb_selection']['ref'])
    assert response.status_code == 200, response.text
    assert [item['kb']['version'] for item in response.json()['items']] == [selected['kb']['version']]
    assert calls == []


def test_unknown_key_or_kb_is_not_silently_replaced_and_answer_field_is_rejected(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    assert request(case['client'], {'kind': 'catalog', 'key': 'missing'}).status_code == 404
    assert request(case['client'], source_for(case), knowledge_ref={'id': 'missing', 'version': 'v'}).status_code == 404
    assert request(case['client'], source_for(case), answer_id='c_A').status_code == 422


def test_evolution_snapshot_stays_pinned_after_newer_claim_revision(evolution):
    client, observer, source, _, calls = evolution
    newer = observer.capture()
    newer['claims'][0].update(text='NEWER_CLAIM_TEXT', version=3)
    observer.reader = lambda _: newer
    assert observer.poll_once()
    result = request(client, source).json()
    observed = next(item for item in result['items'] if item['kb'].get('source_kind') == 'knowledge_evolution')
    assert observed['rules'][0]['text'] == 'Greater width wins in scope'
    assert calls == []


def test_only_public_rule_projection_is_returned_and_disabled_rules_are_excluded(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    snapshot = case['store'].import_rules({'schema_version': 'kb_claim_rules_v1', 'claims': [
        {'id': 'C1', 'text': 'Public hypothesis', 'rules': [rule_entry()['rule']],
         'dev_evidence': 'PRIVATE_OUTCOME', 'usage_note': 'PRIVATE_NOTE'},
        {'id': 'C2', 'text': 'DISABLED_RULE', 'rules': [rule_entry()['rule']], 'inject': False}]},
        source_ref={'id': 'source', 'path': '/private/source'})
    case['item'].update(snapshot=snapshot, version=snapshot['version'])
    response = request(case['client'], source_for(case))
    assert response.status_code == 200
    assert [row['text'] for row in response.json()['items'][0]['rules']] == ['Public hypothesis']
    for private in ('PRIVATE_', '/private/', 'dev_evidence', 'usage_note'):
        assert private not in response.text


def test_formal_applicability_keeps_canonical_validated_scope(tmp_path, monkeypatch):
    from rag_fixtures import formal_library
    raw = raw_case('q_formal')
    raw.update(family='xor_classification', profile_hash='a' * 64, metric='test_ce')
    raw['detail']['dataset']['files']['dataset_spec.json'].update(
        family='xor_classification', selection_metric='test_ce', params={'input_dim': 2})
    for choice in raw['detail']['choices']:
        choice['files']['candidate_spec.json'].update(family='xor_classification',
            optimizer={'type': 'Adam', 'lr': .001}, loss={'loss_id': 'cross_entropy'},
            budget={'total_samples_seen': 8192, 'batch_size': 32, 'training_steps': 256})
    missing = deepcopy(raw)
    missing['id'] = 'q_no_profile'
    missing.pop('profile_hash')
    case = api_case(tmp_path, monkeypatch, records=[raw, missing])
    _, formal = formal_library(tmp_path / 'formal', monkeypatch)
    case['inventory']['items'] = [formal]
    matched = request(case['client'], source_for(case, 'q_formal')).json()
    assert matched['items'][0]['kb']['verification'] == 'per_rule_scope'
    assert matched['items'][0]['rules'][0]['validity_status'] == 'replicated_in_scope'
    assert request(case['client'], source_for(case, 'q_no_profile')).json()['items'] == []


def test_corrupt_kb_does_not_silently_become_an_unverified_hypothesis(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    case['item']['snapshot']['rules'][0]['text'] = 'UNSEALED_EDIT'
    result = request(case['client'], source_for(case)).json()
    assert result['items'] == [] and result['notice']
