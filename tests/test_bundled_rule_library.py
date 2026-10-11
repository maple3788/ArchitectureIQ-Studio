"""Packaged proposals remain self-contained, versioned research material."""
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from architecture_iq.studio.rule_refinement.artifacts import validate_snapshot
from services.kb_workflow_api.app import create_app


def test_kb_inventory_exposes_versioned_v9_v10_without_external_checkout(tmp_path):
    client = TestClient(create_app(state_root=tmp_path, execution_enabled=False))
    result = client.get('/api/studio/kb')
    assert result.status_code == 200
    items = {item['id']: item for item in result.json()['items']}
    assert {'builtin:kb-v9', 'builtin:kb-v10'} <= items.keys()
    v9, v10 = (items[key] for key in ('builtin:kb-v9', 'builtin:kb-v10'))
    for item in (v9, v10):
        validate_snapshot(item['snapshot'])
        assert item['kind'] == 'research_rules'
        assert item['counts']['verified_enabled'] == 0
        assert item['sources'][0]['kind'] == 'bundled'
        assert not Path(item['source']).is_absolute()
        assert item['snapshot']['confirmation_protocol']['kind'] == 'pre-registration'
    assert v10['snapshot']['parent_version'] == v9['version']
    assert len(v9['snapshot']['rules']) == 4
    assert len(v10['snapshot']['rules']) == 12
    r2 = next(rule for rule in v10['snapshot']['rules'] if rule['metadata']['claim_id'] == 'R2')
    assert r2['metadata']['inject'] is False
    assert r2['metadata']['validity_status'] == 'replicated_in_scope'
    assert r2['parents']
    r6 = [rule for rule in v10['snapshot']['rules'] if rule['metadata']['claim_id'] == 'R6']
    assert len(r6) == 2 and all(rule['rule']['max_param_ratio'] == 2 for rule in r6)
    assert all(rule['metadata']['validity_status'] == 'proposed' for rule in r6)
    assert client.get('/api/studio/kb').json() == result.json()


def test_manifest_and_preregistration_content_are_verified(tmp_path):
    from architecture_iq.studio.rule_library import bundled_rule_inventory, LIBRARY_ROOT
    from shutil import copytree
    root = tmp_path / 'rules'
    copytree(LIBRARY_ROOT, root)
    assert len(bundled_rule_inventory(root)['items']) == 2
    path = root / 'kb_v10_revision.json'
    proposal = json.loads(path.read_text())
    proposal['claims'][0]['text'] = 'changed after registration'
    path.write_text(json.dumps(proposal))
    failed = bundled_rule_inventory(root)
    assert not failed['items']
    assert failed['warnings']
    assert 'changed after registration' not in str(failed)


def test_library_grouping_keeps_version_selection_and_frozen_snapshots_unchanged(tmp_path):
    from architecture_iq.studio.rule_library import bundled_rule_inventory, LIBRARY_ROOT
    from shutil import copytree
    root = tmp_path / 'rules'
    copytree(LIBRARY_ROOT, root)
    items = bundled_rule_inventory(root)['items']
    assert len({item['library']['id'] for item in items}) == 1
    assert [item['library']['version_label'] for item in items] == ['v9', 'v10']
    assert [item['library']['version_order'] for item in items] == [9, 10]
    assert items[0]['library']['name'] == '架构与优化器规则'
    manifest_path = root / 'library_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest['versions']:
        entry.pop('library')
    manifest_path.write_text(json.dumps(manifest))
    ungrouped = bundled_rule_inventory(root)['items']
    assert [(item['id'], item['version'], item['snapshot']) for item in items] == [
        (item['id'], item['version'], item['snapshot']) for item in ungrouped]


def test_context_preview_is_separate_from_program_answer_and_reads_no_feedback(tmp_path, monkeypatch):
    from test_rule_refinement_api import api_fixture
    client, app, _, body, _ = api_fixture(tmp_path, monkeypatch)
    item = next(i for i in client.get('/api/studio/kb').json()['items'] if i['id'] == 'builtin:kb-v10')
    original = app.state.catalog.get_question
    def public_only(key, **kwargs):
        assert not kwargs.get('include_private')
        return original(key, **kwargs)
    monkeypatch.setattr(app.state.catalog, 'get_question', public_only)
    request = {k: deepcopy(body[k]) for k in ('dataset_ref', 'selection')}
    request['kb_ref'] = {k: item[k] for k in ('id', 'version')}
    response = client.post('/api/studio/rule-refinement/match', json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['items'] and result['context_matches']
    assert result['items'][0]['question_ref'] == result['context_matches'][0]['question_ref']
    assert result['context_matches'][0]['claim_ids'] == []  # only width differs: R2 is not injected
    assert result['items'][0]['status'] == 'answered'  # R2 remains testable under its strict conditions
    assert result['feedback_released'] is False
    assert 'correct_letter' not in response.text


def test_harness_freezes_metadata_and_protocol_with_selected_version(tmp_path, monkeypatch):
    from test_rule_refinement_api import api_fixture
    from architecture_iq.studio.rule_refinement.inputs import prepare_refinement
    client, app, _, body, _ = api_fixture(tmp_path, monkeypatch)
    inventory = client.get('/api/studio/kb').json()
    item = next(i for i in inventory['items'] if i['id'] == 'builtin:kb-v10')
    body['initial_kb_ref'] = {k: item[k] for k in ('id', 'version')}
    frozen, preview = prepare_refinement(app.state.catalog, app.state.datasets, app.state.models, inventory, body)
    assert preview['can_run'], preview
    assert frozen['initial_rules'] == item['snapshot']
    assert frozen['initial_rules']['parent_version']
    assert frozen['initial_rules']['confirmation_protocol']['decision_rule']['confirmatory'] == ['O1', 'O2', 'O3', 'O4', 'M1', 'R6']
