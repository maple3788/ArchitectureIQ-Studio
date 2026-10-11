from copy import deepcopy
import pytest
from architecture_iq.studio.workflow import default_workflow,compile_workflow,validate_workflow
from architecture_iq.studio.drafts import DraftStore,DraftConflict
from rule_refinement_fixtures import limits
from test_studio_generation import config


def ready():
    from architecture_iq.studio.rule_refinement.workflow import default_rule_workflow
    spec=default_rule_workflow()
    spec['settings']['limits']=limits()
    spec['settings']['generation']=config()
    return spec


def test_rule_template_has_separate_protocol_and_no_solver():
    from architecture_iq.studio.rule_refinement.workflow import compile_rule_workflow
    compiled=compile_rule_workflow(ready())
    assert compiled['protocol']=='rule_refinement_v1'
    assert 'solver' not in compiled['model_nodes']
    assert compiled['method']['data_modes']==['single','pairs']
    assert compiled['method']['publication_policy']=='research_rules_only'
    assert compile_workflow(ready())==compiled
    assert default_workflow('rule_refinement')['schema_version']==2
    assert validate_workflow(ready())=={'valid':True,'errors':[]}


@pytest.mark.parametrize('change',['seal','accept','limits','private','extra_loop','condition','mapping','schema1','extra_node','role','invalid_group'])
def test_graph_cannot_bypass_sealing_acceptance_or_limits(change):
    spec=ready()
    if change in {'seal','accept'}:
        node='verify' if change=='seal' else 'accept'
        spec['nodes']=[n for n in spec['nodes'] if n['id']!=node]
    elif change=='limits': spec['settings']['limits'].pop('max_tokens')
    elif change=='private': spec['edges'][0].update(source='verify',source_handle='sealed_feedback')
    elif change=='extra_loop': spec['edges'].append({**spec['edges'][0],'id':'bad','source':'save','target':'input'})
    elif change=='condition': spec['edges'][0]['condition']='target_reached'
    elif change=='mapping': spec['edges'][0]['mapping']={'public_cases':'public_cases[0]'}
    elif change=='schema1': spec['schema_version']=1
    elif change=='extra_node': spec['nodes'].append({**spec['nodes'][0],'id':'solver'})
    elif change=='role': spec['nodes'][1]['config']['role']='solver'
    else: spec['nodes'].append({'id':'g','type':'group_cases','label':'','position':{'x':0,'y':0},'config':{'strategy':'answer'}})
    assert not validate_workflow(spec)['valid']
    with pytest.raises(ValueError): compile_workflow(spec)


def test_supported_grouping_routes_compile_in_edited_order():
    from architecture_iq.studio.rule_refinement.workflow import material_edge
    spec=ready()
    spec['edges']=[e for e in spec['edges'] if (e['source'],e['target'])!=('verify','revise')]
    for name,strategy in [('g1','family'),('g2','rule')]:
        spec['nodes'].append(dict(id=name,type='group_cases',label=strategy,position={'x':10,'y':10},config={'strategy':strategy}))
    spec['edges'] += [material_edge('verify','g1','sealed_feedback','needs_revision'),
                       material_edge('g1','g2','sealed_feedback'),material_edge('g2','revise','sealed_feedback')]
    assert compile_workflow(spec)['grouping']==['family','rule']
    assert compile_workflow(spec)['execution_order'][3:5]==['g1','g2']
    spec['nodes'][-1]['config']['strategy']='family'
    assert not validate_workflow(spec)['valid']


def test_presentation_and_prompt_have_different_execution_identity():
    spec=ready();before=compile_workflow(spec)
    spec['nodes'][0]['position']['x']+=30;spec['nodes'][0]['label']='Different label'
    moved=compile_workflow(spec)
    assert moved['execution_hash']==before['execution_hash'] and moved['workflow_hash']!=before['workflow_hash']
    next(n for n in spec['nodes'] if n['id']=='revise')['config']['prompt']='Check narrow conditions first'
    assert compile_workflow(spec)['execution_hash']!=before['execution_hash']


def test_v2_incomplete_drafts_save_with_existing_cas_and_backup(tmp_path):
    store=DraftStore(tmp_path);old=store.get()
    spec=ready();spec['edges']=[]
    saved=store.save(expected_revision=old['revision'],workflow=spec,advanced_backup=old['workflow'])
    assert store.get()['workflow']==spec and not validate_workflow(spec)['valid']
    with pytest.raises(DraftConflict): store.save(expected_revision=old['revision'],workflow=ready(),advanced_backup=None)
    backup=store.backup(workflow=ready(),source='conflict')
    assert backup['workflow']==ready()
    bad=deepcopy(spec);bad['settings']['method_id']='scientific'
    with pytest.raises(ValueError):store.save(expected_revision=saved['revision'],workflow=bad,advanced_backup=None)


@pytest.mark.parametrize('method,expected',[
    ('basic_learning',('18cdcc576e709f24f8ef52291f559af48acd87cf50ebadb3716b578010eddf08','32f32482ba81134ca888b7ae42be40d898396df17bba65ea9d9461663f47b10b','b2f81ff78c92e5fef9a6ad60a29522a7d3890180ccde457fa0c58550fe289476')),
    ('scientific',('4d457933b9af621c9f9f7c53ea535e48b5d977f7aacdd329bc3794459a05fc80','b6269f930520d80808a05d7dfafbc1bb44fabfc63240775a3d741fc30fc5ef9e','f02b08d409faaaddacc4f45751a2fc1454646cd997a492eaf6cf288d3db98b54')),
    ('paired_progressive',('bd9445f9c2fac429b9b2deb52ca2a0daf71ce5ffd356da045d1c2dc32c323407','f8724a4743d28e5ac05b342bb2da426804dacab58c5a7574cbaab794ec3c8c85','c59a07d106b2b6df2390822a540dd26c29bbd56beda83ed27303f0e94e0c457a')),
    ('expel',('fabbb6f5d24564b5ad043b5edd1e89385734e1c87a4b232ecb8a77f41d6a1eea','fc7a4c74bedb90ddfeca0fe18c38b83dd399b8dad7a1e16d5c2117295113ee5a','1bfc7255b99b61c99efaa5aefe714471940f2064073924d516c8a864aee5c3a6')),
    ('paired_expel',('5e5f910144c83515510d734cc700385be8cc2647d7cc838c783a821647280b5f','7b5a7ba0d39c922fd90394d656d088eaee23fcd80e11f2384b42eb8afdb4653e','e09d707c5bbb5a6de20f3ed362e6ae51ad11da3e48d369bb1641261ee757ea12')),
])
def test_legacy_recipe_and_draft_hashes_remain_identical(method,expected):
    c=compile_workflow(default_workflow(method))
    assert (c['method']['hash'],c['workflow_hash'],c['execution_hash'])==expected
