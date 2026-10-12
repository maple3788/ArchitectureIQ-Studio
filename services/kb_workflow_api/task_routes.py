"""Durable one-question tasks, separate from formal held-out evaluations."""
from fastapi import Body, HTTPException, Query, Request
from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.tasks import TaskStore, TaskConflict
from architecture_iq.studio.task_answers import eligible_kbs, kb_description, prepare_task, public_task_run
from architecture_iq.studio.evolution_task_sources import EvolutionTaskSources
from architecture_iq.studio.task_review import task_run_detail


def register_task_routes(api, *, catalog, models, jobs, inventory_provider, require_execution, allowed_roots, observer):
    tasks = TaskStore(jobs.state_root)
    evolution = EvolutionTaskSources(jobs.state_root, observer)
    api.state.tasks = tasks
    api.state.task_sources = evolution
    prefix = '/api/studio/tasks'

    class TaskCatalog:
        root = catalog.root

        def get_question(self, key, *, include_private=False):
            if isinstance(key, str) and key.startswith('evolution_'):
                return evolution.get_question(key, include_private=False)
            return catalog.get_question(key, include_private=False)

    task_catalog = TaskCatalog()

    def inventory(reference=None):
        current = inventory_provider()
        observed = evolution.inventory(reference=reference)
        return {'items': [*current.get('items', []), *observed['items']],
                'warnings': [*current.get('warnings', []), *observed.get('warnings', [])]}

    def invoke(operation):
        try:
            return operation()
        except TaskConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(404, '任务或引用的资料不存在') from exc
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(422, '任务配置或资料不可用，请检查题目、模型和 KB 后重新保存预览') from exc
        except RuntimeError as exc:
            raise HTTPException(503, '知识演化资料暂时无法读取，请稍后重试') from exc

    def fields(body, allowed):
        if set(body) != set(allowed):
            raise ValueError('请求字段不完整或包含未知字段')

    def prepare(card):
        reference = card['kb_selection'].get('ref') if card['kb_selection']['mode'] == 'manual' else None
        return prepare_task(card, catalog=task_catalog, models=models, inventory=inventory(reference), allowed_roots=allowed_roots)

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
    @api.post(prefix + '/evolution/selection')
    def evolution_selection(body: dict = Body(...)):
        def operation():
            seed = evolution.selection(body)
            return {**seed, 'kb': kb_description(seed['kb'])}
        return invoke(operation)

    @api.get(prefix + '/evolution/questions')
    def evolution_questions(search: str = Query('', max_length=200), offset: int = Query(0, ge=0),
                            limit: int = Query(25, ge=1, le=100)):
        return invoke(lambda: evolution.list_questions(search=search, offset=offset, limit=limit))

    @api.post(prefix + '/evolution/questions/{question_id}')
    def select_evolution_question(question_id: str):
        def operation():
            record = evolution.freeze_question(question_id)
            return {'key': record['metadata']['key'], 'record': record}
        return invoke(operation)

    @api.get(prefix + '/questions/{question_key}')
    def task_question(question_key: str):
        return invoke(lambda: task_catalog.get_question(question_key, include_private=False))

    @api.get(prefix + '/kbs')
    def kbs(mode: str = Query('llm', pattern='^(llm|rules)$'),
            kb_id: str | None = Query(None, max_length=512),
            kb_version: str | None = Query(None, max_length=128)):
        def operation():
            if (kb_id is None) != (kb_version is None):
                raise ValueError('KB 引用需要身份和版本')
            reference = {'id': kb_id, 'version': kb_version} if kb_id is not None else None
            items = [kb_description(item) for item in eligible_kbs(inventory(reference), mode)]
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

    @api.get(prefix + '/{identifier}/runs/{answer_id}')
    def answer_detail(identifier: str, answer_id: str):
        return invoke(lambda: task_run_detail(tasks.answer(identifier, answer_id), jobs=jobs,
            catalog=catalog, evolution=evolution, observer=observer))
