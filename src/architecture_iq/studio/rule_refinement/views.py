"""Explicit public projections of research artifacts; no raw job/config copying."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from architecture_iq.kb.roles import read_receipt
from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.jobs import JobStore
from .acceptance import compare_candidate
from .artifacts import RuleArtifactStore
from .contracts import artifact_path
from .pool import PoolStore

EVENT_FIELDS={'time','type','event_type','event_id','sequence','protocol','node_id','state','stage_id','step_id','run_id',
              'round_id','round_index','attempt_id','attempt_index','generation_index','operation_key','item_id','phase',
              'kb_version','pool_version','fresh_passes','no_progress','refinement_event_id','artifact_refs','action','outcome','stop_reason'}
METRIC_FIELDS={'metric','higher_is_better','excluded','failed_seeds','seed_results','seed','failed',
               'mean_test_mse','mean_test_ce','mean_test_accuracy','std_test_mse','std_test_ce','std_test_accuracy',
               'final_test_mse','final_test_ce','final_test_accuracy'}


def _pick(value,keys):return {k:deepcopy(v) for k,v in value.items() if k in keys}


def accepted_rule_snapshot(jobs,identifier):
    definition=jobs.definition(identifier)
    if definition['kind']!='rule_refinement':raise ValueError('Not a rule refinement run')
    root=jobs.directory(identifier)/'refinement'
    manifest=read_receipt(root/'manifest.json')
    if manifest['definition_hash']!=definition['definition_hash']:raise ValueError('Run manifest mismatch')
    current=read_receipt(root/'checkpoint.json');previous=None
    artifacts=RuleArtifactStore(root)
    for index in range(1,current['revision']+1):
        cp=read_receipt(root/'checkpoints'/f'{index:08d}.json')
        if cp['revision']!=index:raise ValueError('Checkpoint sequence differs')
        artifacts.get(cp['kb_version'])
        if previous and cp['kb_version']!=previous['kb_version']:
            if previous['phase']!='accept':raise ValueError('KB change lacks acceptance gate')
            operation=previous['pending_operation']['key']
            decision=read_receipt(root/'decisions'/(operation+'.json'))
            before=_verified_score(root,previous['score_ref']);after=_verified_score(root,previous['candidate_score_ref'])
            expected=compare_candidate(before,after,protected_keys=previous['protected_keys'])
            if (not expected['accepted'] or any(decision.get(k)!=v for k,v in expected.items())
                    or cp['kb_version']!=after['kb_version'] or cp['score_ref']!=after['receipt_ref']):
                raise ValueError('Accepted pointer differs from sealed same-pool decision')
        previous=cp
    if previous!=current:raise ValueError('Checkpoint pointer differs from journal')
    snapshot=artifacts.get(current['kb_version'])
    score=_verified_score(root,current['score_ref']) if current.get('score_ref') else None
    return current,snapshot,score


def _verified_score(root,ref):
    score=read_receipt(artifact_path(root,ref,kind='scores'))
    prediction=read_receipt(artifact_path(root,score['prediction_receipt'],kind='predictions'))
    pool=PoolStore(root,None).get(score['pool_version'])
    if (prediction['pool_version']!=score['pool_version'] or prediction['kb']['version']!=score['kb_version']
            or prediction['predictor_version']!=score['predictor_version']
            or {p['question_ref']['key'] for p in prediction['predictions']}!={m['ref']['key'] for m in pool['members']}):
        raise ValueError('Score is not bound to complete sealed predictions')
    return score


def _metrics(value):
    if isinstance(value,dict):return {k:_metrics(v) for k,v in value.items() if k in METRIC_FIELDS}
    if isinstance(value,list):return [_metrics(v) for v in value]
    return value if type(value) in (int,float,bool,str,type(None)) else None


def public_score(score):
    result=_pick(score,{'receipt_ref','pool_version','kb_version','executable_hash','predictor_version','prediction_receipt',
                       'selected','scorable','unscorable','correct','answered','conflicts','wrong_assertions','all_pass','accuracy','answer_coverage','paired','per_rule','problems'})
    result['per_question']={}
    for key,row in score['per_question'].items():
        public=_pick(row,{'question_ref','case','prediction','scorable','correct','answered','assertions','issues'})
        if row.get('scorable') and 'feedback' in row:
            feedback=row['feedback']
            public['feedback']={k:deepcopy(feedback[k]) for k in ('correct_letter','higher_is_better') if k in feedback}
            public['feedback']['candidate_metrics']={cid:_metrics(metrics) for cid,metrics in feedback.get('candidate_metrics',{}).items()}
        result['per_question'][key]=public
    return result


def public_budget(budget):
    return _pick(budget,{'limits','started_at','deadline','remaining_seconds','exceeded','model_calls','tokens','candidate_seed_runs','new_questions','revision_attempts','generation_attempts'})


def public_batch(batch):
    return {**_pick(batch,{'batch_id','index','state','pool_version','base_pool_version','kb_version','requested','actual','eligible','novelty','batch_passed'}),
            'first_score':public_score(batch['first_score']),
            'generation':_pick(batch['generation'],{'child_id','outcome','requested_question_count','question_keys'})}


def artifact_index(jobs,identifier):
    job=jobs.definition(identifier);root=jobs.directory(identifier)/'refinement'
    if job['kind'] not in {'rule_refinement','rule_evaluation'}:return []
    items=[]
    def add(kind,ref,value,label):
        items.append({'id':canonical_hash({'kind':kind,'ref':ref})[:32],'kind':kind,'label':label,'ref':ref,'value':value})
    if job['kind']=='rule_refinement' and (root/'checkpoint.json').exists():
        cp,kb,score=accepted_rule_snapshot(jobs,identifier)
        add('kb','kb/'+kb['version']+'.json',kb,'当前接受的研究规则')
    for path in sorted((root/'scores').glob('*.json')):
        ref='scores/'+path.name;score=_verified_score(root,ref)
        add('score',ref,public_score(score),'题池评分 · '+str(score['correct'])+'/'+str(score['selected']))
    for path in sorted((root/'predictions').glob('*.json')):
        value=read_receipt(path)
        add('prediction','predictions/'+path.name,_pick(value,{'batch_id','pool_version','predictor_version','predictions','question_refs'}),'已封存的整批预测')
    for path in sorted((root/'decisions').glob('*.json')):
        add('decision','decisions/'+path.name,_pick(read_receipt(path),{'accepted','reason','before_score','after_score','protected_keys','newly_correct','regressed'}),'版本验收')
    for path in sorted((root/'proposals').glob('*.json')):
        saved=read_receipt(path);proposal=saved['proposal']
        value=_pick(proposal,{'outcome','seen_case_refs','remaining_count','candidate_version'})
        if proposal.get('candidate_version'):value['candidate']=RuleArtifactStore(root).get(proposal['candidate_version'])
        add('proposal','proposals/'+path.name,value,'候选规则提案')
    return items


def refinement_observations(job,directory):
    jobs=JobStore(Path(directory).parents[1])
    try:
        artifacts=artifact_index(jobs,job['id'])
    except (OSError,ValueError,KeyError,TypeError):return []
    return [dict(node_id={'kb':'save','score':'verify','prediction':'verify','decision':'accept','proposal':'revise'}[a['kind']],
                 round_index=0,key=a['id'],availability='available',output=a['value'],artifact_id=a['id'],label=a['label']) for a in artifacts]


def public_refinement_job(job,jobs=None):
    result=_pick(job,{'id','kind','status','created_at','updated_at'})
    kind=job['kind'];config=job.get('config',{});bound=kind=='generation'
    stream=bool(config.get('transport',{}).get('stream')) and kind=='rule_refinement'
    result['transport']=dict(stream=stream,legacy=False,stage_events='polling',text_events='sse' if stream else 'unavailable',
                             separate_cursors=True,stage_cursor='sequence',text_cursor='seq',
                             notice='模型增量在收据完成前属于部分输出' if stream else '程序节点无模型文本')
    result['error']='运行未完成，请查看已保存结果' if job.get('error') else None
    result['config']={'name':config.get('workflow',{}).get('name','规则评测' if kind=='rule_evaluation' else '新题挑战'),
                      'protocol':config.get('protocol'),'method':_pick(config.get('method',{}),{'id','version','name'}),
                      'transport':{'stream':stream}}
    events=[_pick(e,EVENT_FIELDS) for e in job.get('events',[]) if not bound]
    result['events']=events
    result['progress']=_pick(job.get('progress',{}),EVENT_FIELDS) if not bound else {}
    result['records']=[]
    result['sync']={'stage':{'transport':'polling','status':'snapshot','last_sequence':max((e.get('sequence',0) for e in events),default=0)},
                    'text':{'transport':'sse' if stream else 'unavailable','cursor':'seq','status':'subscription_available' if stream else 'unavailable'}}
    if jobs is None:return result
    root=jobs.directory(job['id'])/'refinement'
    if bound:
        from .challenges import read_parent_binding
        binding=read_parent_binding(jobs,job['id'])
        result['parent_id']=binding['parent_id'];result['feedback_released']=False
        # Child statistics can themselves encode GT. The parent first-test receipt is the public result.
        return result
    try:
        index=artifact_index(jobs,job['id'])
        result['artifacts']=[_pick(a,{'id','kind','label'}) for a in index]
        if kind=='rule_refinement' and (root/'checkpoint.json').exists():
            cp,kb,score=accepted_rule_snapshot(jobs,job['id'])
            result['refinement']={**_pick(cp,{'revision','phase','kb_version','pool_version','attempt_index','generation_index','no_progress','fresh_passes','stop_reason'}),
                                  'best_kb':kb,'score':public_score(score) if score else None,
                                  'fresh_batches':[public_batch(b) for b in PoolStore(root,None).batches()]}
        if (root/'result.json').exists():
            saved=read_receipt(root/'result.json')
            if kind=='rule_refinement':
                result['result']={**_pick(saved,{'outcome','stop_reason','pool','best_kb','unresolved'}),
                                  'score':public_score(_verified_score(root,saved['score']['receipt_ref'])) if saved['score'] else None,
                                  'fresh_batches':[public_batch(b) for b in saved['fresh_batches']], 'budget':public_budget(saved['budget'])}
            else:
                result['result']={**_pick(saved,{'kb_ref','dataset_binding','independence','usage_receipt'}),
                                  'score':public_score(_verified_score(root,saved['score']['receipt_ref']))}
    except (OSError,ValueError,KeyError,TypeError):
        result['artifact_error']='部分运行产物尚未完成或未通过完整性校验'
    return result
