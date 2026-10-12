"""Durable one-question tasks, separate from formal held-out evaluations."""
from fastapi import Body, HTTPException, Query, Request
from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.tasks import TaskStore, TaskConflict
from architecture_iq.studio.task_answers import eligible_kbs, kb_description, prepare_task, public_task_run


def register_task_routes(api, *, catalog, models, jobs, inventory_provider, require_execution, allowed_roots):
    tasks = TaskStore(jobs.state_root)
    api.state.tasks = tasks
    prefix = '/api/studio/tasks'

    def invoke(operation):
        try:
            return operation()
        except TaskConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(404, '任务或引用的资料不存在') from exc
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(422, '任务配置或资料不可用，请检查题目、模型和 KB 后重新保存预览') from exc

    def fields(body, allowed):
        if set(body) != set(allowed):
            raise ValueError('请求字段不完整或包含未知字段')

    def prepare(card):
        return prepare_task(card, catalog=catalog, models=models, inventory=inventory_provider(), allowed_roots=allowed_roots)

    def dispatch(receipt):
        if receipt['mode'] != 'llm':
            return
        job = jobs.get(receipt['job_id'], full=False)
        if job['status'] != 'queued':
            return
        require_execution()
        from architecture_iq.studio.jobs import source_fingerprint
        if job['source_fingerprint'] != source_fingerprint():
            raise TaskConflict('已保存的运行与当前程序版本不同，不能自动恢复执行')
        try:
            jobs.launch(job['id'])
        except ValueError:
            # Another explicitly authorized dispatcher may have won the job's
            # launch lock. Never retry a starting/running/uncertain operation.
            if jobs.get(job['id'], full=False)['status'] == 'queued':
                raise

    @api.get(prefix)
    def listing():
        def operation():
            items = tasks.list()
            return {'items': items, 'total': len(items)}
        return invoke(operation)

    # Register this fixed path before the identity route.
    @api.get(prefix + '/kbs')
    def kbs(mode: str = Query('llm', pattern='^(llm|rules)$')):
        def operation():
            items = [kb_description(item) for item in eligible_kbs(inventory_provider(), mode)]
            return {'items': items, 'total': len(items)}
        return invoke(operation)

    @api.post(prefix)
    def create(body: dict = Body(...)):
        return invoke(lambda: tasks.create(body))

    @api.get(prefix + '/{identifier}')
    def detail(identifier: str):
        return invoke(lambda: tasks.get(identifier))

    @api.put(prefix + '/{identifier}')
    def update(identifier: str, body: dict = Body(...)):
        return invoke(lambda: tasks.save(identifier, expected_revision=body.get('expected_revision'),
                                        changes={k: v for k, v in body.items() if k != 'expected_revision'}))

    @api.post(prefix + '/{identifier}/preview')
    def preview(identifier: str, body: dict = Body(...)):
        def operation():
            fields(body, {'expected_revision'})
            with tasks.lock():
                card = tasks.require(identifier, body['expected_revision'])
                return prepare(card)[1]
        return invoke(operation)

    @api.get(prefix + '/{identifier}/runs')
    def history(identifier: str):
        def operation():
            items = [public_task_run(receipt, jobs) for receipt in tasks.history(identifier)]
            return {'items': items, 'total': len(items)}
        return invoke(operation)

    @api.post(prefix + '/{identifier}/runs')
    def run(identifier: str, request: Request, body: dict = Body(...)):
        def operation():
            fields(body, {'expected_revision', 'preview_hash'})
            if not isinstance(body['preview_hash'], str) or len(body['preview_hash']) != 64:
                raise ValueError('需要有效预览')
            key = request.headers.get('Idempotency-Key')
            with tasks.lock():
                prior = tasks.prior(identifier, key, body)
                if prior:
                    dispatch(prior)
                    return public_task_run(prior, jobs)
                card = tasks.require(identifier, body['expected_revision'])
                if card['mode'] == 'llm':
                    require_execution()
                try:
                    config, shown = prepare(card)
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    raise TaskConflict('题目、模型或 KB 已变化，请重新预览') from exc
                if shown['preview_hash'] != body['preview_hash']:
                    raise TaskConflict('预览已失效，请重新预览')
                if not shown['can_run']:
                    raise TaskConflict('当前没有可执行的作答配置')
                value = {'task_id': identifier, 'task_revision': card['revision'], 'mode': card['mode'],
                         'config': config, 'preview_hash': shown['preview_hash'], 'status': 'complete'}
                if card['mode'] == 'rules':
                    value['result'] = {k: shown[k] for k in ('prediction', 'selected_kbs', 'question', 'warnings')}
                else:
                    job = jobs.create('rag', config, idempotency_key='task:' + canonical_hash([identifier, key]))
                    value.update(job_id=job['id'], status=job['status'])
                receipt = tasks.record(identifier, key, body, value)
                dispatch(receipt)
                return public_task_run(receipt, jobs)
        return invoke(operation)
