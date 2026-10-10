"""Preview-guarded standalone RAG routes; accepts catalog references only."""
from fastapi import Body, HTTPException, Request
from architecture_iq.studio.execution import public_job
from architecture_iq.studio.rag import prepare_rag


def register_rag_routes(api, *, catalog, models, jobs, inventory_provider, require_execution, allowed_roots):
    prefix = '/api/studio/rag'

    def selection(body, *, run=False):
        allowed = {'question_key', 'model_id', 'knowledge_limit'} | ({'preview_hash'} if run else set())
        if set(body) - allowed:
            raise ValueError('RAG 输入包含未知字段')
        for key in ('question_key', 'model_id'):
            if not isinstance(body.get(key), str) or not body[key].strip():
                raise ValueError('请选择题目和模型')
        limit = body.get('knowledge_limit', 8)
        if type(limit) is not int or not 1 <= limit <= 12:
            raise ValueError('知识条数必须为 1–12 的整数')
        return {key: body[key] for key in ('question_key', 'model_id')} | {'knowledge_limit': limit}

    @api.post(prefix + '/preview')
    def preview(body: dict = Body(...)):
        return prepare_rag(catalog, models, inventory_provider(), **selection(body), allowed_roots=allowed_roots)[1]

    @api.post(prefix + '/runs')
    def runs(request: Request, body: dict = Body(...)):
        require_execution()
        selected = selection(body, run=True)
        if not isinstance(body.get('preview_hash'), str) or not body['preview_hash']:
            raise HTTPException(409, '请先预览匹配结果')
        key = request.headers.get('Idempotency-Key')
        if not key or len(key) > 200:
            raise ValueError('需要有效 Idempotency-Key')
        try:
            config, result = prepare_rag(catalog, models, inventory_provider(), **selected, allowed_roots=allowed_roots)
        except ValueError as exc:
            raise HTTPException(409, '配置或来源已变化，请重新预览：' + str(exc)) from exc
        if result['preview_hash'] != body['preview_hash']:
            raise HTTPException(409, '预览已失效，请重新匹配')
        if not result['can_answer']:
            raise HTTPException(409, '没有可用匹配知识，无法启动 RAG 作答')
        try:
            job = jobs.create('rag', config, idempotency_key=key)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if job['status'] == 'queued':
            try:
                jobs.launch(job['id'])
            except ValueError:
                if jobs.get(job['id'])['status'] == 'queued':
                    raise
        return public_job(jobs.get(job['id']))
