"""Reference-only preflights, frozen model identities and held-out usage provenance."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from architecture_iq.kb.roles import _seal, read_receipt, exclusive_lock
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.studio.dataset_inputs import DatasetInputs
from architecture_iq.studio.datasets import DatasetStore
from architecture_iq.studio.jobs import JobStore, source_fingerprint
from architecture_iq.studio.rag import freeze_rag_model
from .artifacts import RuleArtifactStore, validate_snapshot
from .contracts import PROTOCOL, fields, text
from .pool import PoolStore, _case, check_independence
from .prediction import predict_batch, match_question_for_injection
from .workflow import compile_rule_workflow
from .challenges import prepare_challenge


def _rule_copy(catalog,source,reference):
    with TemporaryDirectory(prefix='.rule-preview-',dir=catalog.root) as directory:
        return RuleArtifactStore(Path(directory)).import_rules(source,source_ref=reference)


def resolve_rule_knowledge(catalog,inventory,reference):
    fields(reference,{'id','version'},{'id','version'})
    text(reference['id']);text(reference['version'])
    item=next((i for i in inventory['items'] if i['id']==reference['id'] and i['version']==reference['version']),None)
    if item is None or item['kind'] not in {'research_rules','formal'}:
        raise ValueError('所选规则 KB 不可用或版本已变化')
    source={'kind':item['kind'],**reference,'run_ids':[s['id'] for s in item.get('sources',[]) if s.get('kind')=='run']}
    if item['kind']=='research_rules':validate_snapshot(item['snapshot'])
    return _rule_copy(catalog,item['snapshot'],source),source,item


def match_rules(catalog,datasets,inventory,body,*,offset=0,limit=25):
    fields(body,{'dataset_ref','selection','kb_ref'},{'dataset_ref','selection','kb_ref'})
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Invalid match pagination')
    selection=DatasetInputs(catalog,datasets).preview(body['dataset_ref'],body['selection'],purpose='public',method_id='rule_refinement')
    if not selection['can_apply']:raise ValueError('所选公开题目资料不可用')
    kb,_,_=resolve_rule_knowledge(catalog,inventory,body['kb_ref'])
    keys=selection['binding']['keys'];cases=[_case(catalog.get_question(k)) for k in keys[offset:offset+limit]]
    predictions=predict_batch(cases,kb)
    context_matches=[match_question_for_injection(case,kb) for case in cases]
    return dict(items=predictions,context_matches=context_matches,cases=cases,total=len(keys),offset=offset,limit=limit,matched_count=len(predictions),
                counts={status:sum(p['status']==status for p in predictions) for status in ('answered','conflict','uncovered','invalid')},
                kb_version=kb['version'],scope='requested_page',model_required=False,feedback_released=False)


def prepare_refinement(catalog,datasets,models,inventory,body):
    fields(body,{'workflow','dataset_ref','selection','initial_kb_ref'},{'workflow','dataset_ref','selection'})
    blockers=[];selected=None;compiled=None;frozen=None
    try:
        selected=DatasetInputs(catalog,datasets).preview(body['dataset_ref'],body['selection'],purpose='research',method_id='rule_refinement')
        blockers.extend(selected['blockers'])
    except (ValueError,KeyError,OSError):
        blockers.append({'code':'dataset_unavailable','message':'请选择可用的 Dataset 固定修订和完整题目'})
    try:
        workflow=deepcopy(body['workflow'])
        node=next(n for n in workflow['nodes'] if n['id']=='input')
        if selected:
            if node['config'].get('dataset_binding') not in (None,selected['binding']):
                blockers.append({'code':'dataset_binding_changed','message':'画布与选择面板的 Dataset 修订不同'})
            node['config']['dataset_binding']=selected['binding']
        initialization=next(n for n in workflow['nodes'] if n['id']=='initialize')['config']
        chosen=body.get('initial_kb_ref')
        if chosen:
            if initialization.get('source') not in (None,chosen):
                raise ValueError('画布与初始 KB 选择不同')
            initialization['source']=chosen
        compiled=compile_rule_workflow(workflow)
    except (ValueError,KeyError,TypeError,StopIteration) as exc:
        blockers.append({'code':'workflow_invalid','message':'请完成流程连接、生成配置和全部正数预算：'+str(exc)})
    if compiled:
        initial=None;source=None;profiles={}
        try:
            if compiled['initialization']['mode']=='model':
                initial=_rule_copy(catalog,{'rules':[]},{'kind':'empty'});source={'kind':'empty'}
            elif compiled['initialization']['source']=={'kind':'empty'}:
                initial=_rule_copy(catalog,{'rules':[]},{'kind':'empty'});source={'kind':'empty'}
            else:
                initial,source,_=resolve_rule_knowledge(catalog,inventory,compiled['initialization']['source'])
        except (ValueError,KeyError,TypeError,OSError):
            blockers.append({'code':'initial_kb_unavailable','message':'请选择初始 KB，或明确从空规则开始'})
        for node in ('initialize','revise'):
            if node=='initialize' and compiled['initialization']['mode']!='model':continue
            try:
                model_id=compiled['model_nodes'][node]['model_id']
                profile=models.get(model_id)
                roots=[catalog.root]
                if profile.get('runtime_lock_path'):roots.append(Path(profile['runtime_lock_path']).expanduser().resolve().parent)
                profiles[node]=freeze_rag_model(models,model_id,allowed_roots=roots)
            except (ValueError,KeyError,OSError):
                blockers.append({'code':'model_unavailable','node_id':node,'message':'请选择可用模型并检查凭据或运行锁'})
        if not blockers:
            frozen={**compiled,'dataset_binding':selected['binding'],'initial_rules':initial,'initial_source_ref':source,
                    'models':profiles,'transport':{'stream':True}}
    counts={'questions':selected['count'] if selected else 0,'pairs':selected['pair_count'] if selected else 0}
    cost=({'questions_per_batch':compiled['limits']['questions_per_batch'],
           'candidate_seed_runs_per_batch':prepare_challenge(
               compiled['generation'],attempt_index=1,questions_per_batch=compiled['limits']['questions_per_batch'])['candidate_seed_runs'],
           'model_roles':list(profiles)} if compiled else {})
    identity=canonical_hash({'config':frozen,'body':body,'selection_hash':selected['preview_hash'] if selected else None,
                             'blockers':blockers,'source_fingerprint':source_fingerprint()})
    return frozen,dict(preview_hash=identity,can_run=not blockers,blockers=blockers,counts=counts,cost=cost,
                       limits=compiled['limits'] if compiled else {},protocol=PROTOCOL,models=[
                           {k:p[k] for k in ('id','revision','model','context_size')} for p in profiles.values()] if compiled else [])


def research_exposure(jobs,item):
    """Follow all accepted-run sources and their frozen initial KB ancestry."""
    pending=[s['id'] for s in item.get('sources',[]) if s.get('kind')=='run']
    seen=set();members=[];known=item['kind']=='research_rules' and bool(pending)
    while pending:
        run_id=pending.pop()
        if run_id in seen:continue
        seen.add(run_id)
        definition=jobs.definition(run_id)
        if definition['kind']!='rule_refinement':known=False;continue
        config=definition['config'];root=jobs.directory(run_id)/'refinement'
        from .views import accepted_rule_snapshot
        cp,_,_=accepted_rule_snapshot(jobs,run_id)
        pool=PoolStore(root,None)
        members.extend(pool.get(cp['pool_version'])['members'])
        for batch in pool.batches():members.extend(pool.get(batch['pool_version'])['members'])
        source=config['initial_source_ref']
        if source.get('kind')=='research_rules' and source.get('run_ids'):
            pending.extend(source['run_ids'])
        elif config['initialization']['mode']=='model' or source.get('kind')=='empty':
            pass
        else:
            initial=config['initial_rules']
            if initial.get('rules') or initial.get('claims'):known=False
    return {'members':members},known,sorted(seen)


def evaluation_usage(jobs):
    return [read_receipt(p) for p in sorted((jobs.state_root/'rule_evaluations'/'usage').glob('*.json'))]


def prepare_rule_evaluation(catalog,datasets,jobs,inventory,body):
    fields(body,{'kb_ref','dataset_ref','selection','phase'},{'kb_ref','dataset_ref','selection','phase'})
    if body['phase'] not in {'development','final'}:raise ValueError('Evaluation phase must be development or final')
    kb,source,item=resolve_rule_knowledge(catalog,inventory,body['kb_ref'])
    selected=DatasetInputs(catalog,datasets).preview(body['dataset_ref'],body['selection'],purpose='evaluation',method_id='rule_refinement',phase=body['phase'])
    blockers=deepcopy(selected['blockers']);pool=None;report={};known=False;ancestry=[];exposure_hash=None
    try:
        with TemporaryDirectory(prefix='.rule-evaluation-',dir=catalog.root) as directory:
            pool=PoolStore(Path(directory),catalog).freeze_members(selected['binding']['keys'],purpose='evaluation',source_bindings=[selected['binding']])
        prior,known,ancestry=research_exposure(jobs,item)
        exposure_hash=canonical_hash(prior)
        report=check_independence(prior,pool)
        if not report['eligible']:
            blockers.append({'code':'research_overlap' if report['overlap'] else 'missing_identity',
                             'message':'评测题与已有研究材料重叠，或缺少可核验的独立身份'})
    except (ValueError,KeyError,OSError):
        blockers.append({'code':'evaluation_material_unavailable','message':'评测题或 KB 研究谱系无法核验'})
    usage=evaluation_usage(jobs)
    used={'members':[m for receipt in usage for m in receipt['members']]}
    repeat=bool(pool and check_independence(used,pool)['overlap'])
    independence='repeated_evaluation' if repeat else 'verified_first_use' if known else 'unknown_prior_exposure'
    frozen=dict(protocol='rule_evaluation_v1',kb_ref=body['kb_ref'],kb_snapshot=kb,dataset_binding=selected['binding'],
                phase=body['phase'],pool=pool,independence=independence,research_runs=ancestry,
                research_exposure_hash=exposure_hash,research_source={'kind':item['kind'],'sources':item.get('sources',[])},
                selection_health=selected['preview_hash'],usage_version=canonical_hash(usage),transport={'stream':False})
    preview_hash=canonical_hash({'config':frozen,'source_fingerprint':source_fingerprint(),'blockers':blockers})
    return frozen,dict(preview_hash=preview_hash,can_run=not blockers,blockers=blockers,counts={'questions':selected['count'],'pairs':selected['pair_count']},
                       independence=independence,independence_report=report,model_required=False,protocol='rule_evaluation_v1')


def record_evaluation_use(jobs,identifier):
    definition=jobs.definition(identifier);config=definition['config']
    if definition['kind']!='rule_evaluation' or config['protocol']!='rule_evaluation_v1':raise ValueError('Wrong evaluation kind')
    path=jobs.state_root/'rule_evaluations'/'usage'/(identifier+'.json')
    value=_seal({'run_id':identifier,'definition_hash':definition['definition_hash'],'kb_ref':config['kb_ref'],
                 'members':[{'ref':m['ref'],'identity':m['identity']} for m in config['pool']['members']],
                 'phase':config['phase'],'independence':config['independence']})
    if path.exists() and read_receipt(path)!=value:raise ValueError('Evaluation usage is immutable')
    write_json_atomic(path,value)
    return value
