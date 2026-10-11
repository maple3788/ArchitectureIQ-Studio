"""Mock providers and stored Catalog fixtures; never real LLM/GT execution."""
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from architecture_iq.kb.roles import read_receipt, _seal
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.datasets import DatasetStore
from architecture_iq.studio.jobs import JobStore
from architecture_iq.studio.models import api_identity
from architecture_iq.studio.rule_refinement.workflow import compile_rule_workflow,default_rule_workflow
from rule_refinement_fixtures import raw_case,rule_entry,limits
from test_studio_catalog import bakefile
from test_studio_generation import config as generation_config


class SequenceProvider:
    max_retries=0
    def __init__(self,invalid=False):
        self.count=multiprocessing.get_context('fork').Value('i',0)
        self.invalid=invalid
    def complete(self,prompt,model):
        with self.count.get_lock():
            self.count.value+=1;index=self.count.value
        data=json.loads(prompt.split('\n\nDATA:\n')[1]);kb=data['kb']
        operations=([dict(op='retire',rule_id=r['rule_id'],revision=r['revision']) for r in kb['rules'] if r['state']=='active']
                    +[dict(op='add',entry=rule_entry((8,16,32)))]) if index==1 else [dict(op='add',entry=rule_entry((64,128,256),lower=True))]
        reply={} if self.invalid else dict(base_version=kb['version'],operations=operations,rationale='fixture',
                                          case_refs=[p['case_ref'] for p in data.get('index_page',[])])
        return SimpleNamespace(raw={'model':model.name,'choices':[{'message':{'content':json.dumps(reply)}}]},
                               usage={'prompt_tokens':40,'completion_tokens':60},finish_reason='stop')


def distinct_case(qid,index,*,widths=(32,16,8),correct='A'):
    raw=raw_case(qid,'data_'+qid,widths=widths,correct=correct)
    raw['detail']['dataset']['files']['dataset_spec.json']['params']['instance_seed']=index
    return raw


def setup_run(tmp_path,monkeypatch,*,invalid=False,initial_empty=False,initial_model=False,limit_changes=None,batch_widths=None):
    from architecture_iq.studio.rule_refinement import runner
    state=tmp_path/'state';catalog=Catalog(state);jobs=JobStore(state)
    raw=distinct_case('initial',1)
    report=catalog.import_source(bakefile(tmp_path/'initial.json',[raw]));key=report['entries'][0]['key']
    collection=DatasetStore(catalog).create(name='Research',keys=[key],operation_id='research')
    binding=dict(collection_id=collection['collection_id'],revision=collection['revision'],selection={},keys=[key],
                 hashes=[catalog.get_question(key)['metadata']['hash']],pair_keys=[])
    spec=default_rule_workflow();spec['settings']['limits']=limits(questions_per_batch=1,max_new_questions=3,**(limit_changes or {}))
    spec['settings']['generation']=generation_config()
    profile=dict(id='fake',revision='revision',connection_type='api',base_url='http://example.invalid/v1',model='mock-rules',
                 parameters={'max_tokens':1000,'temperature':0},context_size=100000)
    profile['service_identity']=api_identity(profile);profile['runtime_fingerprint']=canonical_hash(profile['service_identity'])
    for node in spec['nodes']:
        if node['id']=='input': node['config']['dataset_binding']=binding
        if node['id'] in {'initialize','revise'}:node['config']['model_id']='fake'
        if node['id']=='initialize' and initial_model:node['config']['mode']='model'
    compiled=compile_rule_workflow(spec)
    frozen={**compiled,'dataset_binding':binding,'initial_rules':{'rules':[] if initial_empty or initial_model else [rule_entry(lower=True)]},
            'initial_source_ref':{'kind':'fixture'},'models':{'initialize':profile,'revise':profile},'transport':{'stream':False}}
    job=jobs.create('rule_refinement',frozen)
    provider=SequenceProvider(invalid)
    counts={'generation':0}; batches=[]
    for index,widths in enumerate(batch_widths or [(64,128,256),(32,16,8),(64,128,256)],1):
        item=distinct_case(f'fresh_{index}',index+1,widths=widths)
        imported=catalog.import_source(bakefile(tmp_path/f'fresh_{index}.json',[item]))
        batches.append(imported['entries'][0]['key'])
    def challenge(jobs,*,parent_id,attempt_index,frozen_config,ledger):
        path=ledger.root/'challenges'/f'challenge-{attempt_index}-result.json'
        if path.exists():return read_receipt(path)
        counts['generation']+=1
        op=f'challenge-{attempt_index}'
        ledger.reserve(op,dict(generation_attempts=1,new_questions=1,candidate_seed_runs=3),inputs_hash=canonical_hash(frozen_config))
        result=_seal(dict(child_id=f'fake_{attempt_index}',requested_question_count=1,question_keys=[batches[attempt_index-1]],pairs=[],
                          outcome='complete',receipt_ref=f'challenges/challenge-{attempt_index}-result.json'))
        write_json_atomic(path,result)
        ledger.settle(op,actual={'new_questions':1},receipt_ref=result['receipt_ref'],outcome='complete')
        return result
    monkeypatch.setattr(runner,'run_challenge',challenge)
    def client_factory(profile,observer,**kwargs):
        assert 0<kwargs['timeout_s']<=900
        return provider
    return jobs,catalog,job,provider,client_factory,counts


def execute(args):
    from architecture_iq.studio.rule_refinement.runner import execute_refinement
    jobs,catalog,job,provider,factory,counts=args
    return execute_refinement(jobs,job['id'],job['config'],catalog=catalog,client_factory=factory)


def test_complete_loop_repairs_expands_and_preserves_first_tests(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch)
    result=execute(args)
    jobs,_,job,provider,_,counts=args
    assert result['outcome']=='target_reached',result
    assert provider.count.value==2 and counts['generation']==3
    assert len(result['fresh_batches'])==3 and not result['fresh_batches'][0]['first_score']['all_pass']
    assert result['score']['selected']==4 and result['score']['all_pass']
    root=jobs.directory(job['id'])/'refinement'
    cp=read_receipt(root/'checkpoint.json')
    assert cp['fresh_passes']==2 and len(cp['protected_keys'])==4
    assert all(batch==read_receipt(root/'batches'/(batch['batch_id']+'.json')) for batch in result['fresh_batches'])
    before=deepcopy(result)
    assert execute(args)==before and counts['generation']==3 and provider.count.value==2


def test_stops_after_three_invalid_or_nonimproving_proposals(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch,invalid=True)
    result=execute(args)
    assert result['outcome']=='stopped' and result['stop_reason']=='no_progress'
    assert result['budget']['revision_attempts']==3 and args[3].count.value==3
    assert result['best_kb']['rules'][0]['rule']['predict']=={'lower_better':'width'}
    assert args[-1]['generation']==0


def test_empty_initialization_cannot_pass(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch,invalid=True,initial_empty=True,initial_model=True)
    result=execute(args)
    assert result['outcome']=='stopped' and result['stop_reason']=='no_progress'
    assert result['score']['correct']==0 and not result['score']['all_pass']
    assert result['budget']['revision_attempts']==3


@pytest.mark.parametrize('changes,reason', [({'max_revision_attempts':1},'revision_limit'),
                                          ({'max_model_calls':1},'resource_limit'),
                                          ({'max_tokens':1},'resource_limit')])
def test_all_limit_reasons_keep_best_kb(tmp_path,monkeypatch,changes,reason):
    args=setup_run(tmp_path,monkeypatch,invalid=True,limit_changes=changes)
    result=execute(args)
    assert result['stop_reason']==reason and result['best_kb']['version']
    assert result['score']['selected']==1


def test_generation_limit_and_failed_first_test_reset_streak(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch,batch_widths=[(64,128,256)]*3)
    from architecture_iq.studio.rule_refinement import runner
    original=runner.run_challenge
    def short(*a,**kw):
        value=original(*a,**kw);value={**value,'outcome':'partial'}
        return _seal(value)
    monkeypatch.setattr(runner,'run_challenge',short)
    result=execute(args)
    assert result['stop_reason']=='generation_limit' and result['score']['all_pass']
    assert not any(b['batch_passed'] for b in result['fresh_batches'])


def test_accepted_change_resets_streak(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch,batch_widths=[(32,16,8),(64,128,256),(64,128,256)])
    result=execute(args)
    assert result['stop_reason']=='generation_limit'
    cp=read_receipt(args[0].directory(args[2]['id'])/'refinement'/'checkpoint.json')
    assert cp['fresh_passes']==1


def test_pause_across_deadline_and_explicit_stop(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import runner
    args=setup_run(tmp_path,monkeypatch)
    jobs,_,job,provider,_,_=args
    runner.request_refinement_control(jobs,job['id'],'stop')
    result=execute(args)
    assert result['stop_reason']=='user_stop' and provider.count.value==0
    assert runner.request_refinement_control(jobs,job['id'],'stop')['action']=='stop'


def test_source_change_and_config_change_are_not_resumed(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import runner
    args=setup_run(tmp_path,monkeypatch)
    jobs,catalog,job,_,factory,_=args
    with pytest.raises(ValueError):runner.execute_refinement(jobs,job['id'],{**job['config'],'protocol':'changed'},catalog=catalog,client_factory=factory)
    monkeypatch.setattr(runner,'source_fingerprint',lambda:'changed')
    with pytest.raises(ValueError):execute(args)


def test_pause_time_counts_against_fixed_deadline(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import runner
    args=setup_run(tmp_path,monkeypatch,limit_changes={'wall_time_seconds':10})
    jobs,catalog,job,provider,factory,_=args
    runner.request_refinement_control(jobs,job['id'],'pause')
    clock=[100.0]
    monkeypatch.setattr(runner.time,'sleep',lambda _:clock.__setitem__(0,clock[0]+11))
    result=runner.execute_refinement(jobs,job['id'],job['config'],catalog=catalog,client_factory=factory,clock=lambda:clock[0])
    assert result['stop_reason']=='resource_limit' and result['budget']['deadline']==110
    assert provider.count.value==0


def test_failed_expanded_baseline_does_not_show_old_pool_score_as_current(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import runner
    args=setup_run(tmp_path,monkeypatch)
    original=runner._score
    def damaged(root,pools,pool,kb,catalog,identity):
        if len(pool['members'])>1:raise ValueError('source damaged after admission')
        return original(root,pools,pool,kb,catalog,identity)
    monkeypatch.setattr(runner,'_score',damaged)
    result=execute(args)
    assert result['stop_reason']=='execution_failure'
    assert result['pool']['question_count']==2
    assert result['score'] is None or result['score']['pool_version']==result['pool']['version']


def test_provider_stream_uses_actual_operation_and_zero_round_bucket(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch)
    jobs,catalog,job,provider,factory,counts=args
    original=provider.complete
    def streaming(prompt,model):
        provider.observer({'payload':{'model':model.name},'body_sha256':'mock-wire'})
        provider.chunk({'kind':'chunk','chunk':{'choices':[{'index':0,'delta':{'content':'fixture provider text'}}]}})
        return original(prompt,model)
    monkeypatch.setattr(provider,'complete',streaming)
    def streamed_factory(profile,observer,**kwargs):
        provider.observer=observer;provider.chunk=kwargs['chunk_observer']
        return factory(profile,observer,**kwargs)
    from architecture_iq.studio.rule_refinement.runner import execute_refinement
    result=execute_refinement(jobs,job['id'],job['config'],catalog=catalog,client_factory=streamed_factory)
    frames=jobs.stream_events(job['id'])
    assert result['outcome']=='target_reached' and len(frames)==2
    assert [f['operation_key'] for f in frames]==['revise-1','revise-2']
    assert all(f['round_index']==0 and f['node_id']=='revise' for f in frames)
