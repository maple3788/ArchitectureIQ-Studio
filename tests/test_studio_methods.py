"""A paper method is frozen execution behavior, not just a display label."""
import copy
import json
from pathlib import Path

import pytest

from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.workflow import compile_workflow, default_workflow, validate_workflow


def recipe_spec(method='scientific'):
    spec = default_workflow("scientific")
    spec['settings'].update(method_id=method, method_version='1')
    if method in {'paired_progressive', 'paired_expel'}:
        spec['settings'].update(discovery_per_round=2, packet_size=2)
    return spec


def test_default_draft_uses_manual_loop_and_versioned_method():
    spec = default_workflow("scientific")
    assert spec['settings'].get('loop_mode') == 'manual'
    assert spec['settings'].get('method_id') == 'scientific'
    compiled = compile_workflow(spec)
    assert compiled['method']['id'] == 'scientific'
    assert compiled['config']['method'] == compiled['method']
    assert compiled['config'].get('stop_after_no_change_rounds') == 1


def test_registry_is_copy_safe_and_hashes_its_complete_descriptor():
    from architecture_iq.studio.methods import list_methods
    entries = list_methods()
    assert {m['id'] for m in entries} == {'basic_learning', 'scientific', 'paired_progressive', 'expel', 'paired_expel'}
    assert all(m['hash'] == canonical_hash({k:v for k,v in m.items() if k != 'hash'}) for m in entries)
    entries[0]['steps'][0]['label'] = 'mutated client copy'
    assert list_methods()[0]['steps'][0]['label'] != 'mutated client copy'


@pytest.mark.parametrize('method,protocol,memory', [
    ('scientific','single','off'),('expel','single','expel_inspired'),
    ('paired_progressive','paired_progressive','off'),
    ('paired_expel','paired_progressive','expel_inspired'),
])
def test_recipe_compiles_authoritative_execution_settings(method, protocol, memory):
    spec = recipe_spec(method)
    frozen = copy.deepcopy(spec)
    result = compile_workflow(spec)
    assert result['config']['learning_protocol'] == protocol
    assert result['config']['experience_mode'] == memory
    assert result['method']['version'] == '1'
    assert spec == frozen
    if memory != 'off':
        assert result['method']['paper_url'] == 'https://arxiv.org/abs/2308.10144'
        assert 'experience_consolidate' in {s['id'] for s in result['method']['steps']}


@pytest.mark.parametrize('settings', [
    {'method_id':'missing'}, {'method_id':{}}, {'method_id':'expel','method_version':'99'},
    {'method_version':'1'}, {'method_id':'expel','learning_protocol':'paired_progressive'},
    {'loop_mode':'endless'}, {'loop_mode':{}}, {'stop_after_no_change_rounds':0},
    {'stop_after_no_change_rounds':True}, {'stop_after_no_change_rounds':4},
])
def test_invalid_recipe_or_loop_is_rejected_before_execution(settings):
    spec = default_workflow("scientific")
    for key in ('method_id','method_version'):
        spec['settings'].pop(key, None)
    spec['settings'].update(settings)
    report = validate_workflow(spec)
    assert report['valid'] is False
    with pytest.raises(ValueError):
        compile_workflow(spec)


def test_paired_recipe_requires_even_complete_packet_without_explicit_protocol():
    spec = recipe_spec('paired_expel')
    spec['settings']['packet_size'] = 1
    assert not validate_workflow(spec)['valid']


def test_legacy_compilation_does_not_inject_new_method_or_loop_semantics():
    spec = default_workflow("scientific")
    for key in ('method_id','method_version','loop_mode','stop_after_no_change_rounds'):
        spec['settings'].pop(key, None)
    compiled = compile_workflow(spec)
    assert 'method' not in compiled
    assert 'method' not in compiled['config']
    assert 'experience_mode' not in compiled['config']
    assert 'loop_mode' not in compiled['config']
    semantic = {'schema_version':1,'config':compiled['config'],
                'routes':sorted((e['source'],e['target'],e.get('condition','always')) for e in spec['edges']),
                'evaluate_phase':None,'references':{}}
    assert compiled['execution_hash'] == canonical_hash(semantic)


def test_different_paper_method_changes_execution_identity():
    before = compile_workflow(recipe_spec('scientific'))
    after = compile_workflow(recipe_spec('expel'))
    assert before['execution_hash'] != after['execution_hash']


def test_method_settings_have_schema_parity():
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((Path(__file__).parents[1]/'contracts/kb_workflow.schema.json').read_text())
    for method in ('scientific','paired_progressive','expel','paired_expel'):
        spec = recipe_spec(method)
        spec['settings'].update(loop_mode='manual', stop_after_no_change_rounds=2)
        jsonschema.validate(spec, schema)
        assert validate_workflow(spec)['valid']
