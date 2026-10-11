"""Guarded rule research and model-free evaluation endpoints."""
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from architecture_iq.kb.roles import exclusive_lock
from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.jobs import read
from architecture_iq.studio.rule_refinement.contracts import fields
from architecture_iq.studio.rule_refinement.inputs import (
    match_rules,prepare_refinement,prepare_rule_evaluation,record_evaluation_use,
)
from architecture_iq.studio.rule_refinement.runner import request_refinement_control,recover_refinement
from architecture_iq.studio.rule_refinement.views import artifact_index,public_refinement_job


def register_rule_refinement_routes(api,*,catalog,datasets,models,jobs,inventory_provider,require_execution):
    prefix='/api/studio/rule-refinement'
    def invoke(operation):
        try:return operation()
        except HTTPException as exc:
            detail=exc.detail if isinstance(exc.detail,dict) else {'code':'execution_unavailable','message':str(exc.detail)}
            return JSONResponse(status_code=exc.status_code,content={'detail':detail})
        except (ValueError,KeyError,OSError,RuntimeError) as exc:
            status=409 if isinstance(exc,RuntimeError) else 404 if isinstance(exc,(KeyError,FileNotFoundError)) else 422
            return JSONResponse(status_code=status,content={'detail':{
                'code':'refinement_conflict' if status==409 else 'artifact_unavailable' if status==404 else 'invalid_refinement_request',
                'message':'请求或产物不可用，请核对配置并重新预览'}})
    def key(request):
        value=request.headers.get('Idempotency-Key')
        if not value or len(value)>200:raise ValueError('Idempotency-Key required')
        return value
    def existing(identifier,body):
        path=jobs.root/'idempotency'/(canonical_hash(identifier)+'.json')
        if not path.exists():return None
        old=jobs.get(read(path)['id'])
        if old['config'].get('request_hash')!=canonical_hash(body):
            raise HTTPException(409,{'code':'idempotency_conflict','message':'同一请求标识的内容已变化'})
        return old
    def submit(request,body,*,evaluation=False):
        allowed={'kb_ref','dataset_ref','selection','phase','preview_hash'} if evaluation else {'workflow','dataset_ref','selection','initial_kb_ref','preview_hash'}
        required={'kb_ref','dataset_ref','selection','phase','preview_hash'} if evaluation else {'workflow','dataset_ref','selection','preview_hash'}
        fields(body,allowed,required)
        identifier=key(request)
        if not evaluation:require_execution()
        lock=jobs.state_root/'rule_evaluations'/'usage.lock' if evaluation else jobs.root/'refinement_submit.lock'
        with exclusive_lock(lock):
            prior=existing(identifier,body)
            if prior:return public_refinement_job(prior,jobs)
            selected={k:v for k,v in body.items() if k!='preview_hash'}
            frozen,preview=(prepare_rule_evaluation(catalog,datasets,jobs,inventory_provider(),selected) if evaluation
                            else prepare_refinement(catalog,datasets,models,inventory_provider(),selected))
            if preview['preview_hash']!=body['preview_hash']:
                raise HTTPException(409,{'code':'preview_changed','message':'输入、模型版本或来源状态已变化，请重新预览'})
            if not preview['can_run']:
                raise HTTPException(409,{'code':'preflight_blocked','message':'配置尚不满足运行条件','blockers':preview['blockers']})
            job=jobs.create('rule_evaluation' if evaluation else 'rule_refinement',
                            {**frozen,'request_hash':canonical_hash(body)},idempotency_key=identifier)
            if evaluation:record_evaluation_use(jobs,job['id'])
            if job['status']=='queued':jobs.launch(job['id'])
            return public_refinement_job(jobs.get(job['id']),jobs)

    @api.post(prefix+'/match')
    def match(request:Request,body:dict=Body(...)):
        def operation():
            if set(request.query_params)-{'offset','limit'}:raise ValueError('Unknown pagination fields')
            return match_rules(catalog,datasets,inventory_provider(),body,offset=int(request.query_params.get('offset',0)),limit=int(request.query_params.get('limit',25)))
        return invoke(operation)

    @api.post(prefix+'/preview')
    def preview(body:dict=Body(...)):
        return invoke(lambda:prepare_refinement(catalog,datasets,models,inventory_provider(),body)[1])

    @api.post(prefix+'/runs')
    def runs(request:Request,body:dict=Body(...)):
        return invoke(lambda:submit(request,body))

    @api.get(prefix+'/runs/{identifier}/artifacts/{artifact_id}')
    def artifact(identifier:str,artifact_id:str):
        def operation():
            found=next((a for a in artifact_index(jobs,identifier) if a['id']==artifact_id),None)
            if found is None:raise KeyError('Unknown public artifact')
            return {k:found[k] for k in ('id','kind','label','value')}
        return invoke(operation)

    @api.post(prefix+'/runs/{identifier}/control')
    def control(identifier:str,body:dict=Body(...)):
        def operation():
            fields(body,{'action'},{'action'})
            if body['action']=='resume':require_execution()
            return request_refinement_control(jobs,identifier,body['action'])
        return invoke(operation)

    @api.post(prefix+'/runs/{identifier}/recover')
    def recover(identifier:str,body:dict=Body(default={})):
        def operation():
            fields(body,set())
            require_execution()
            return public_refinement_job(recover_refinement(jobs,identifier),jobs)
        return invoke(operation)

    @api.post(prefix+'/evaluations/preview')
    def evaluation_preview(body:dict=Body(...)):
        return invoke(lambda:prepare_rule_evaluation(catalog,datasets,jobs,inventory_provider(),body)[1])

    @api.post(prefix+'/evaluations')
    def evaluations(request:Request,body:dict=Body(...)):
        return invoke(lambda:submit(request,body,evaluation=True))
