"""Durable rule research controller. Every external operation has one frozen identity."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time

from architecture_iq.kb.roles import RoleCaller, _seal, exclusive_lock, read_receipt, role_prompt
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.execution import create_client, _tools
from architecture_iq.studio.jobs import JobStore, read, source_fingerprint, process_stamp
from architecture_iq.studio.models import api_identity, model_config
from .acceptance import advance_protection, compare_candidate
from .artifacts import RuleArtifactStore, validate_snapshot
from .budget import BudgetLedger, BudgetExceeded, UncertainOperation
from .challenges import prepare_challenge, run_challenge, recover_challenge, RefinementStopped
from .contracts import PROTOCOL, artifact_path, validate_pool
from .pool import PoolStore
from .prediction import predict_batch
from .revision import build_initial_payload, build_revision_payload, propose_patch
from .scoring import seal_predictions, score_sealed_batch
from .workflow import compile_rule_workflow

PHASE_NODES={'baseline':'verify','ready':'verify','initialize':'initialize','revise':'revise',
             'candidate_check':'verify','accept':'accept','challenge':'challenge','first_test':'verify',
             'promote':'input','finish':'save'}


def _validate_config(jobs,identifier,config):
    definition=jobs.definition(identifier)
    if definition['kind']!='rule_refinement' or config!=definition['config'] or config.get('protocol')!=PROTOCOL:
        raise ValueError('Frozen refinement definition differs')
    if definition['source_fingerprint']!=source_fingerprint():
        raise ValueError('Source fingerprint differs; old runs cannot resume under new code')
    compiled=compile_rule_workflow(config['workflow'])
    if any(config.get(k)!=v for k,v in compiled.items()):
        raise ValueError('Frozen rule workflow compilation differs')
    if config['dataset_binding']!=compiled['dataset_input']['dataset_binding']:
        raise ValueError('Dataset binding differs from frozen graph')
    for node,profile in config['models'].items():
        if node not in {'initialize','revise'} or profile['id']!=compiled['model_nodes'][node]['model_id']:
            raise ValueError('Frozen model differs from node selection')
        if profile.get('connection_type')=='api':
            identity=api_identity(profile)
            if profile.get('service_identity')!=identity or profile.get('runtime_fingerprint')!=canonical_hash(identity):
                raise ValueError('API configuration identity differs')
    return definition


def _checkpoint(root,previous,changes):
    """One CAS commit contains accepted KB, score, pool, protection and loop counters."""
    with exclusive_lock(root/'checkpoint.lock'):
        path=root/'checkpoint.json'
        old=read_receipt(path) if path.exists() else None
        if old!=previous:
            raise ValueError('Refinement checkpoint changed concurrently')
        revision=(old['revision'] if old else 0)+1
        value={**(old or {}),**deepcopy(changes),'revision':revision}
        value.pop('receipt_hash',None)
        value=_seal(value)
        journal=root/'checkpoints'/f'{revision:08d}.json'
        if journal.exists() and read_receipt(journal)!=value:
            raise ValueError('Checkpoint journal integrity differs')
        write_json_atomic(journal,value)
        write_json_atomic(path,value)
        return value


def _sync_events(jobs,identifier,root):
    with exclusive_lock(root/'events.lock'):
        committed=read_receipt(root/'checkpoint.json')['revision']
        seen={e.get('refinement_event_id') for e in jobs.events(identifier)}
        for path in sorted((root/'checkpoints').glob('*.json')):
            cp=read_receipt(path);key='checkpoint-'+str(cp['revision'])
            if cp['revision']>committed or key in seen:continue
            phase=cp['phase'];node=PHASE_NODES[phase];op=cp.get('pending_operation') or {}
            event=dict(type='stage',state='complete' if phase=='finish' else 'running',protocol=PROTOCOL,
                       node_id=node,stage_id='kb' if phase=='finish' else 'harness',step_id='rule_'+phase,
                       refinement_event_id=key,phase=phase,attempt_id=op.get('key'),operation_key=op.get('key'),
                       attempt_index=cp['attempt_index'],generation_index=cp['generation_index'],round_index=0,
                       kb_version=cp['kb_version'],pool_version=cp['pool_version'],
                       fresh_passes=cp['fresh_passes'],no_progress=cp['no_progress'],
                       artifact_refs=cp.get('artifact_refs',[]))
            jobs.event(identifier,event)
            jobs.update(identifier,progress=event)


def _boundary(jobs,identifier,ledger):
    root=ledger.root;announced=False
    while True:
        ledger.check_time()
        control=read(root/'control.json') if (root/'control.json').exists() else {}
        if control.get('action')=='stop':raise RefinementStopped('User requested stop')
        if control.get('action')!='pause':break
        if not announced:
            jobs.update(identifier,status='paused');announced=True
        time.sleep(.1)
    if announced:jobs.update(identifier,status='running')


def _score(root,pools,pool,kb,catalog,identity):
    cases=pools.public_cases(pool['version'])
    receipt=seal_predictions(root,batch_id=identity,pool=pool,kb=kb,predictions=predict_batch(cases,kb))
    def feedback(ref):
        record=catalog.get_question(ref['key'],include_private=True)
        if record['metadata']['hash']!=ref['hash'] or not record['metadata']['evaluation_ready']:
            raise ValueError('Frozen feedback material unavailable')
        return record['feedback']
    return score_sealed_batch(root,prediction_receipt=receipt['receipt_ref'],pool=pool,feedback_loader=feedback)


def _read_score(root,ref):
    return read_receipt(artifact_path(root,ref,kind='scores'))


def _save_decision(root,operation,decision):
    path=root/'decisions'/(operation+'.json');value=_seal(decision)
    if path.exists() and read_receipt(path)!=value:raise ValueError('Decision is immutable')
    write_json_atomic(path,value)
    return value


def _caller(jobs,identifier,config,cp,ledger,client_factory):
    node='initialize' if cp['phase']=='initialize' else 'revise'
    role='rule_initializer' if node=='initialize' else 'rule_reviser'
    profile=config['models'][node];op=cp['pending_operation']['key'];wire=op+'-wire'
    metadata=dict(node_id=node,role=role,round_index=0,operation_key=op,attempt_id=op,
                  stage_id='harness',step_id='rule_'+node,model_id=profile['id'])
    def observer(request):
        jobs.reserve(identifier,wire,metadata)
        jobs.update_record(identifier,wire,{'actual_request':request})
    def stream(frame):jobs.append_stream(identifier,wire,metadata,frame)
    client=client_factory(profile,observer,stream=config.get('transport',{}).get('stream',False),chunk_observer=stream,
                          credential_root=jobs.state_root/'credentials',timeout_s=min(900,ledger.snapshot()['remaining_seconds']))
    _,ModelConfig,_=_tools()
    caller=RoleCaller(ledger.root/'roles',client,ModelConfig(**model_config(profile)),fingerprint=profile['runtime_fingerprint'],
                      max_calls=ledger.limits['max_model_calls'],max_tokens=ledger.limits['max_tokens'],
                      max_context=profile['context_size'],instructions={role:config['model_nodes'][node]['prompt']},
                      allow_model_alias=profile.get('connection_type')=='api')
    overhead=len(role_prompt(role,{},instruction=caller.instructions.get(role)).encode())
    return caller,role,caller.max_context-caller.model.max_tokens-256-overhead


def _finish(jobs,identifier,root,cp,ledger,pools):
    path=root/'result.json'
    if path.exists():return read_receipt(path)
    score=_read_score(root,cp['score_ref']) if cp.get('score_ref') else None
    kb=RuleArtifactStore(root).get(cp['kb_version'])
    pool=pools.get(cp['pool_version'])
    result=_seal(dict(outcome='target_reached' if cp['stop_reason']=='target_reached' else 'stopped',
                      stop_reason=cp['stop_reason'],best_kb=kb,pool={'version':pool['version'],'question_count':len(pool['members']),'pair_count':len(pool['pairs'])},
                      score=score,fresh_batches=pools.batches(),unresolved=score['problems'] if score else [],budget=ledger.snapshot()))
    write_json_atomic(path,result)
    write_json_atomic(jobs.directory(identifier)/'result.json',result)
    status={'uncertain':'uncertain','execution_failure':'failed'}.get(cp['stop_reason'],'complete')
    jobs.update(identifier,status=status,error=cp.get('failure_type'))
    return result


def execute_refinement(jobs,identifier,config,*,catalog,client_factory=create_client,clock=time.time):
    definition=_validate_config(jobs,identifier,config)
    root=jobs.directory(identifier)/'refinement'
    with exclusive_lock(root/'runner.lock'):
        ledger=BudgetLedger(root,config['limits'],clock=clock)
        manifest=_seal({'definition_hash':definition['definition_hash'],'source_fingerprint':definition['source_fingerprint'],
                        'config_hash':canonical_hash(config)})
        if (root/'manifest.json').exists() and read_receipt(root/'manifest.json')!=manifest:
            raise ValueError('Run manifest differs')
        write_json_atomic(root/'manifest.json',manifest)
        pools=PoolStore(root,catalog);artifacts=RuleArtifactStore(root)
        if (root/'checkpoint.json').exists():
            cp=read_receipt(root/'checkpoint.json')
        else:
            pool=pools.initialize(config['dataset_binding'])
            initial={'rules':[]} if config['initialization']['mode']=='model' else config['initial_rules']
            kb=artifacts.import_rules(initial,source_ref=config['initial_source_ref'])
            cp=_checkpoint(root,None,dict(phase='baseline',kb_version=kb['version'],pool_version=pool['version'],score_ref=None,
                protected_keys=[],attempt_index=0,generation_index=0,no_progress=0,fresh_passes=0,pending_operation=None,
                artifact_refs=[],seen_case_refs=[],needs_initialization=config['initialization']['mode']=='model',
                pending_batch=None,stop_reason=None))
        while True:
            _sync_events(jobs,identifier,root)
            if cp['phase']=='finish':return _finish(jobs,identifier,root,cp,ledger,pools)
            try:
                kb=artifacts.get(cp['kb_version']);pool=pools.get(cp['pool_version']);phase=cp['phase']
                if phase=='baseline':
                    score=_score(root,pools,pool,kb,catalog,'baseline-'+canonical_hash([pool['version'],kb['version']])[:40])
                    streak=cp['fresh_passes']
                    if cp['pending_batch']:
                        batch=read_receipt(root/'batches'/(cp['pending_batch']+'.json'))
                        streak=streak+1 if batch['batch_passed'] and score['all_pass'] else 0
                    cp=_checkpoint(root,cp,dict(phase='ready',score_ref=score['receipt_ref'],
                        protected_keys=advance_protection(cp['protected_keys'],score),fresh_passes=streak,pending_batch=None,
                        artifact_refs=[score['receipt_ref']]))
                elif phase=='ready':
                    score=_read_score(root,cp['score_ref']);usage=ledger.snapshot();limits=ledger.limits
                    # A proved target takes precedence over an exhausted budget after its final batch.
                    if score['all_pass'] and cp['fresh_passes']>=limits['required_fresh_passes']:
                        cp=_checkpoint(root,cp,dict(phase='finish',stop_reason='target_reached'));continue
                    if score['unscorable']:raise ValueError('Research materials are unscorable')
                    _boundary(jobs,identifier,ledger)
                    if score['all_pass']:
                        if usage['generation_attempts']>=limits['max_generation_attempts']:
                            cp=_checkpoint(root,cp,dict(phase='finish',stop_reason='generation_limit'));continue
                        index=cp['generation_index']+1
                        cp=_checkpoint(root,cp,dict(phase='challenge',generation_index=index,
                            pending_operation={'kind':'challenge','key':f'challenge-{index}'},artifact_refs=[]))
                    else:
                        if cp['no_progress']>=limits['max_no_progress']:
                            cp=_checkpoint(root,cp,dict(phase='finish',stop_reason='no_progress'));continue
                        if usage['revision_attempts']>=limits['max_revision_attempts']:
                            cp=_checkpoint(root,cp,dict(phase='finish',stop_reason='revision_limit'));continue
                        index=cp['attempt_index']+1;kind='initialize' if cp['needs_initialization'] else 'revise'
                        cp=_checkpoint(root,cp,dict(phase=kind,attempt_index=index,
                            pending_operation={'kind':kind,'key':f'{kind}-{index}'},artifact_refs=[]))
                elif phase in {'initialize','revise'}:
                    op=cp['pending_operation']['key']
                    # Completed proposals are read without reconstructing a provider after the deadline.
                    proposal_path=root/'proposals'/(op+'.json')
                    if proposal_path.exists():
                        proposal=read_receipt(proposal_path)['proposal']
                    else:
                        _boundary(jobs,identifier,ledger)
                        caller,role,max_input=_caller(jobs,identifier,config,cp,ledger,client_factory)
                        if phase=='initialize':
                            payload=build_initial_payload(kb,pools.public_cases(pool['version']),max_input_bytes=max_input)
                        else:
                            payload=build_revision_payload(kb,_read_score(root,cp['score_ref']),seen_case_refs=cp['seen_case_refs'],
                                                           max_input_bytes=max_input,grouping=config['grouping'])
                        proposal=propose_patch(caller,ledger,attempt_id=op,kb=kb,payload=payload,initialize=phase=='initialize')
                    wire=jobs.record_path(identifier,op+'-wire')
                    if wire.exists():jobs.finish(identifier,op+'-wire',{'status':'invalid' if proposal['outcome']=='invalid' else 'complete','call_ref':proposal['call_ref']})
                    changes={'seen_case_refs':sorted(set(cp['seen_case_refs'])|set(proposal['seen_case_refs'])),
                             'needs_initialization':False,'artifact_refs':['proposals/'+op+'.json']}
                    if proposal['outcome']=='invalid':
                        _save_decision(root,op,dict(accepted=False,reason='invalid_patch',before_score=cp['score_ref'],after_score=None))
                        if phase=='initialize':_charge_initial_failure(ledger,op)
                        changes.update(phase='ready',no_progress=cp['no_progress']+1,pending_operation=None)
                    else:
                        changes.update(phase='candidate_check',candidate_version=proposal['candidate_version'])
                    cp=_checkpoint(root,cp,changes)
                elif phase=='candidate_check':
                    candidate=artifacts.get(cp['candidate_version']);op=cp['pending_operation']['key']
                    score=_score(root,pools,pool,candidate,catalog,'candidate-'+op)
                    cp=_checkpoint(root,cp,dict(phase='accept',candidate_score_ref=score['receipt_ref'],artifact_refs=[score['receipt_ref']]))
                elif phase=='accept':
                    before=_read_score(root,cp['score_ref']);after=_read_score(root,cp['candidate_score_ref']);op=cp['pending_operation']['key']
                    decision=_save_decision(root,op,compare_candidate(before,after,protected_keys=cp['protected_keys']))
                    changes=dict(phase='ready',pending_operation=None,candidate_version=None,candidate_score_ref=None,
                                 artifact_refs=['decisions/'+op+'.json'])
                    if decision['accepted']:
                        changes.update(kb_version=cp['candidate_version'],score_ref=cp['candidate_score_ref'],
                                       protected_keys=decision['protected_keys'],no_progress=0,fresh_passes=0)
                    else:
                        changes.update(no_progress=cp['no_progress']+1)
                        if cp['pending_operation']['kind']=='initialize':_charge_initial_failure(ledger,op)
                    cp=_checkpoint(root,cp,changes)
                elif phase=='challenge':
                    index=cp['generation_index']
                    frozen=prepare_challenge(config['generation'],attempt_index=index,questions_per_batch=ledger.limits['questions_per_batch'])
                    result=run_challenge(jobs,parent_id=identifier,attempt_index=index,frozen_config=frozen,ledger=ledger)
                    cp=_checkpoint(root,cp,dict(phase='first_test',generation=result,artifact_refs=[result['receipt_ref']]))
                elif phase=='first_test':
                    generation=cp['generation'];batch_id=f'batch-{cp["generation_index"]}'
                    incoming=pools.freeze_members(generation['question_keys'],pairs=generation['pairs'])
                    score=_score(root,pools,incoming,kb,catalog,'first-'+batch_id)
                    batch=pools.record_first_test(batch_id,pool=incoming,score=score,generation=generation)
                    cp=_checkpoint(root,cp,dict(phase='promote',pending_batch=batch_id,artifact_refs=[score['receipt_ref'],'batches/'+batch_id+'.json']))
                elif phase=='promote':
                    promoted=pools.promote(cp['pending_batch'],expected_pool_version=cp['pool_version'])
                    cp=_checkpoint(root,cp,dict(phase='baseline',pool_version=promoted['version'],score_ref=None,pending_operation=None,
                                               generation=None,artifact_refs=['pools/'+promoted['version']+'.json']))
                else:
                    raise ValueError('Unknown persisted phase')
            except (BudgetExceeded,RefinementStopped,UncertainOperation) as exc:
                reason='resource_limit' if isinstance(exc,BudgetExceeded) else 'user_stop' if isinstance(exc,RefinementStopped) else 'uncertain'
                cp=_checkpoint(root,cp,dict(phase='finish',stop_reason=reason,failure_type=type(exc).__name__))
            except (ValueError,TypeError,KeyError,OSError,RuntimeError) as exc:
                # Error text from external sources can contain credentials. Keep typed diagnostics only.
                reason='resource_limit' if isinstance(exc,ValueError) and 'context budget' in str(exc) else 'execution_failure'
                cp=_checkpoint(root,cp,dict(phase='finish',stop_reason=reason,failure_type=type(exc).__name__))


def _charge_initial_failure(ledger,operation):
    key=operation+'-failed'
    ledger.reserve(key,{'revision_attempts':1},inputs_hash=canonical_hash(operation))
    ledger.settle(key,actual={},receipt_ref='proposals/'+operation+'.json',outcome='invalid')


def request_refinement_control(jobs,identifier,action):
    definition=jobs.definition(identifier)
    if definition['kind']!='rule_refinement' or action not in {'pause','resume','stop'}:
        raise ValueError('Unsupported refinement control')
    root=jobs.directory(identifier)/'refinement';path=root/'control.json'
    with exclusive_lock(root/'control.lock'):
        old=read(path) if path.exists() else None
        if old and old['action']==action:return old
        state=jobs.get(identifier,full=False)
        if state['status'] in {'complete','failed','uncertain','interrupted'}:
            if action=='stop':return old or {'action':'stop'}
            raise ValueError('Ended runs require explicit safe recovery, not resume')
        value={'action':action,'time':time.time()}
        write_json_atomic(path,value)
        jobs.event(identifier,{'type':'control','protocol':PROTOCOL,**value})
        return value


def _validate_saved(root):
    for path in root.rglob('*.json'):
        value=read(path)
        if 'receipt_hash' in value:read_receipt(path)
        elif path.parent.name=='kb':validate_snapshot(value)
        elif path.parent.name=='pools':validate_pool(value)
        elif path.name!='control.json':raise ValueError('Unknown unsealed refinement artifact')


def recover_refinement(jobs,identifier):
    root=jobs.directory(identifier)/'refinement'
    with exclusive_lock(root/'recovery.lock'):
        definition=jobs.definition(identifier);config=definition['config']
        _validate_config(jobs,identifier,config)
        _validate_saved(root)
        cp=read_receipt(root/'checkpoint.json')
        state=read(jobs.directory(identifier)/'state.json')
        if cp['phase']=='finish' or state['status'] in {'starting','running','paused'} and (not state.get('pid') or process_stamp(state['pid'])==state.get('process_stamp')):
            return jobs.get(identifier)
        pools=PoolStore(root,Catalog(jobs.state_root));pools.public_cases(cp['pool_version'])
        ledger=BudgetLedger(root,config['limits'],clock=time.time)
        uncertain=False
        for path in (root/'roles'/'calls').glob('*.json'):
            if read_receipt(path)['status']!='complete':uncertain=True
        for key,operation in ledger.snapshot()['operations'].items():
            if operation['outcome']=='uncertain':uncertain=True
            if operation['outcome']=='pending' and key.startswith(('revise-','initialize-')):
                receipts=[read_receipt(p) for p in (root/'roles'/'calls').glob('*.json')]
                if not any(r['key']==key and r['status']=='complete' for r in receipts):uncertain=True
        if uncertain:
            cp=_checkpoint(root,cp,dict(phase='finish',stop_reason='uncertain',failure_type='UncertainOperation'))
            _sync_events(jobs,identifier,root);_finish(jobs,identifier,root,cp,ledger,pools)
            return jobs.get(identifier)
        # The existing worker owns .worker.lock and runner.lock; source hashes are never rewritten.
        jobs.update(identifier,status='queued',error=None)
        jobs.launch(identifier)
        return jobs.get(identifier)


def validate_rule_evaluation_config(jobs,identifier,config,*,catalog):
    """The sole local worker exception accepts only this finite stored-result protocol."""
    from .contracts import fields,validate_pool
    from .inputs import research_exposure
    from architecture_iq.studio.dataset_inputs import DatasetInputs
    from architecture_iq.studio.datasets import DatasetStore
    required={'protocol','kb_ref','kb_snapshot','dataset_binding','phase','pool','independence','research_runs','research_exposure_hash','research_source','selection_health','usage_version','transport'}
    fields(config,required|{'request_hash'},required)
    definition=jobs.definition(identifier)
    if (definition['kind']!='rule_evaluation' or definition['config']!=config or config['protocol']!='rule_evaluation_v1'
            or config['transport']!={'stream':False} or config['phase'] not in {'development','final'}):
        raise ValueError('Invalid stored rule evaluation definition')
    validate_snapshot(config['kb_snapshot']);validate_pool(config['pool'])
    ref={k:config['dataset_binding'][k] for k in ('collection_id','revision')}
    selected=DatasetInputs(catalog,DatasetStore(catalog)).preview(ref,config['dataset_binding']['selection'],purpose='evaluation',method_id='rule_refinement',phase=config['phase'])
    if not selected['can_apply'] or selected['binding']!=config['dataset_binding'] or selected['preview_hash']!=config['selection_health']:
        raise ValueError('Evaluation materials changed after preview')
    prior,_,runs=research_exposure(jobs,config['research_source'])
    if canonical_hash(prior)!=config['research_exposure_hash'] or runs!=config['research_runs']:
        raise ValueError('Research exposure changed after evaluation preflight')
    receipt_path=jobs.state_root/'rule_evaluations'/'usage'/(identifier+'.json')
    receipt=read_receipt(receipt_path)
    if receipt['definition_hash']!=definition['definition_hash'] or receipt['members']!=[
            {'ref':m['ref'],'identity':m['identity']} for m in config['pool']['members']]:
        raise ValueError('Evaluation requires its own frozen usage reservation')
    return receipt


def execute_rule_evaluation(jobs,identifier,config,*,catalog):
    receipt=validate_rule_evaluation_config(jobs,identifier,config,catalog=catalog)
    if jobs.definition(identifier)['source_fingerprint']!=source_fingerprint():raise ValueError('Evaluation source fingerprint differs')
    root=jobs.directory(identifier)/'refinement'
    with exclusive_lock(root/'evaluation.lock'):
        if (root/'result.json').exists():return read_receipt(root/'result.json')
        pools=PoolStore(root,catalog)
        pool=pools.freeze_members(config['dataset_binding']['keys'],purpose='evaluation',source_bindings=[config['dataset_binding']])
        if pool!=config['pool']:raise ValueError('Frozen evaluation pool differs')
        kb=RuleArtifactStore(root).import_rules(config['kb_snapshot'],source_ref=config['kb_ref'])
        jobs.event(identifier,{'type':'stage','node_id':'verify','stage_id':'task','step_id':'rule_evaluate','state':'running'})
        score=_score(root,pools,pool,kb,catalog,'evaluation-all')
        result=_seal({'score':score,'kb_ref':config['kb_ref'],'dataset_binding':config['dataset_binding'],
                      'usage_receipt':receipt['receipt_hash'],'independence':config['independence']})
        write_json_atomic(root/'result.json',result)
        jobs.event(identifier,{'type':'stage','node_id':'verify','stage_id':'task','step_id':'rule_evaluate','state':'complete',
                               'artifact_refs':[score['receipt_ref']]})
        return result
