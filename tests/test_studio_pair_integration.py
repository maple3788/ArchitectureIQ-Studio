import copy

import pytest


def test_workflow_pair_modes_are_typed_and_private_manifest_not_editable():
    from architecture_iq.studio.workflow import default_workflow, compile_workflow, validate_workflow
    spec = default_workflow("scientific")
    # Legacy drafts choose a protocol directly rather than a versioned recipe.
    spec['settings'].pop('method_id')
    spec['settings'].pop('method_version')
    for protocol in ('single', 'paired_contrastive', 'paired_progressive'):
        spec['settings'].update(learning_protocol=protocol, discovery_per_round=2, packet_size=2)
        assert compile_workflow(spec)['config']['learning_protocol'] == protocol
    spec['settings']['learning_protocol'] = 'magic'
    assert not validate_workflow(spec)['valid']
    spec['settings']['learning_protocol'] = 'single'
    spec['settings']['pair_manifest'] = []
    assert not validate_workflow(spec)['valid']


def test_pair_composition_excludes_replaced_or_disabled_task_pairs():
    from architecture_iq.studio.task_inputs import workflow_pairs
    def q(key, split): return {'id': key, 'split': split}
    def p(key, split): return {'pair_key': key, 'members': [{'key': key+'a'}, {'key': key+'b'}], 'split': split}
    data = {'questions': [q('da','discovery'),q('db','discovery'),q('olda','final'),q('oldb','final')],
            'pairs': [p('d','discovery'), p('old','final')]}
    task = {'questions': [q('newa','final'),q('newb','final')], 'pairs':[p('new','final')]}
    before = copy.deepcopy((data,task))
    assert [p['pair_key'] for p in workflow_pairs(data,task,phase='final')] == ['d','new']
    assert [p['pair_key'] for p in workflow_pairs(data,task,phase=None)] == ['d','old']
    assert (data,task) == before


def test_question_pair_endpoints_are_public_and_atomic(tmp_path):
    from test_studio_api import make_client
    from test_studio_pairs import import_pair
    client, source = make_client(tmp_path)
    catalog = client.app.state.catalog
    import_pair(tmp_path)
    response = client.get('/api/studio/question-pairs?split=discovery')
    assert response.status_code == 200
    pair = response.json()['items'][0]
    assert 'correct_letter' not in response.text and 'PRIVATE_WINNER' not in response.text
    key = pair['pair_key']
    assert client.get('/api/studio/question-pairs/'+key).status_code == 200
    saved = client.post('/api/studio/question-sets',json={'name':'pairs','pair_keys':[key]})
    assert saved.status_code == 200, saved.text
    assert saved.json()['pair_count'] == 1 and len(saved.json()['keys']) == 2
    assert client.post('/api/studio/question-sets',json={'pair_keys':[key],'keys':[]}).status_code == 422


def test_paired_discoverer_guidance_reaches_actual_pair_researcher():
    from architecture_iq.studio.workflow import default_workflow, compile_workflow
    spec=default_workflow("scientific")
    spec['settings'].update(method_id='paired_progressive',learning_protocol='paired_progressive',discovery_per_round=2,packet_size=2)
    next(n for n in spec['nodes'] if n['id']=='discoverer')['config']['prompt']='Explicit conditional explanations'
    assert compile_workflow(spec)['role_instructions']['pair_researcher']=='Explicit conditional explanations'


def test_evaluation_pair_manifest_is_validated_before_transport():
    from architecture_iq.studio.execution import preview_evaluation
    from test_kb_pair_learning import pair_inputs
    config, questions, _, _ = pair_inputs()
    pair = config["pair_manifest"][0]
    pair['candidate_mapping'][0]['original_letter']='INVALID'
    with pytest.raises(ValueError,match='mapping'):
        preview_evaluation({'question_set':{'questions':questions,'pairs':[pair]},'models':[{}]})
