"""Reference-only Data routes; all writes preserve immutable source snapshots."""
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from architecture_iq.studio.datasets import DatasetArchived, DatasetConflict


def dataset_error(exc):
    if isinstance(exc, DatasetConflict):
        return JSONResponse(status_code=409, content={'detail': {'code': 'dataset_revision_conflict',
            'message': str(exc), 'current_revision': exc.current_revision}})
    if isinstance(exc, DatasetArchived):
        return JSONResponse(status_code=409, content={'detail': {'code': 'dataset_archived', 'message': str(exc)}})
    status = 404 if isinstance(exc, (KeyError, FileNotFoundError)) else 422
    return JSONResponse(status_code=status, content={'detail': {
        'code': 'dataset_not_found' if status == 404 else 'invalid_dataset_request', 'message': str(exc)}})


def data_call(operation):
    try:
        return operation()
    except (DatasetConflict, DatasetArchived, ValueError, KeyError, FileNotFoundError) as exc:
        return dataset_error(exc)


def fields(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body):
        raise ValueError('Unknown or missing Dataset request fields')
    return body


def query_fields(request, allowed):
    if set(request.query_params) - set(allowed):
        raise ValueError('Unknown Dataset query fields')


def register_dataset_routes(api, *, catalog, bank, datasets, allowed_roots):
    prefix = '/api/studio'
    api.state.datasets, api.state.question_bank = datasets, bank

    @api.get(prefix + '/datasets')
    def list_datasets(request: Request, search: str = '', family: str = '', archived: bool = False,
                      offset: int = 0, limit: int = 25):
        def operation():
            query_fields(request, {'search', 'family', 'archived', 'offset', 'limit'})
            return datasets.list(search=search, family=family, archived=archived, offset=offset, limit=limit)
        return data_call(operation)

    @api.post(prefix + '/datasets')
    def create_dataset(request: Request, body: dict = Body(...)):
        return data_call(lambda: datasets.create(**fields(body, {'name', 'description', 'keys', 'pair_keys'}, {'name'}),
            operation_id=request.headers.get('Idempotency-Key')))

    @api.get(prefix + '/datasets/{collection_id}')
    def get_dataset(collection_id: str, request: Request, revision: str | None = None):
        def operation():
            query_fields(request, {'revision'})
            return datasets.get(collection_id, revision)
        return data_call(operation)

    @api.post(prefix + '/datasets/{collection_id}/revisions')
    def revise_dataset(collection_id: str, request: Request, body: dict = Body(...)):
        return data_call(lambda: datasets.revise(collection_id,
            **fields(body, {'expected_revision', 'changes'}, {'expected_revision', 'changes'}),
            operation_id=request.headers.get('Idempotency-Key')))

    @api.get(prefix + '/datasets/{collection_id}/questions')
    def members(collection_id: str, request: Request, revision: str, search: str = '', family: str = '',
                type: str = '', split: str = '', offset: int = 0, limit: int = 25):
        def operation():
            query_fields(request, {'revision', 'search', 'family', 'type', 'split', 'offset', 'limit'})
            return datasets.list_members({'collection_id': collection_id, 'revision': revision},
                filters={'search': search, 'family': family, 'type': type, 'split': split}, offset=offset, limit=limit)
        return data_call(operation)

    @api.get(prefix + '/question-bank')
    def question_bank(request: Request, search: str = '', family: str = '', type: str = '', split: str = '',
                      offset: int = 0, limit: int = 25):
        def operation():
            query_fields(request, {'search', 'family', 'type', 'split', 'offset', 'limit'})
            page = bank.list_questions(filters={'search': search, 'family': family, 'type': type, 'split': split},
                                       offset=offset, limit=limit)
            memberships = datasets.memberships([key for item in page['items'] for key in item['keys']])
            for item in page['items']:
                item['datasets'] = list({d['collection_id']: d for key in item['keys'] for d in memberships[key]}.values())
            return page
        return data_call(operation)

    @api.post(prefix + '/datasets/{collection_id}/imports')
    def attach_source(collection_id: str, request: Request, body: dict = Body(...)):
        def operation():
            fields(body, {'expected_revision', 'source_id'}, {'expected_revision', 'source_id'})
            source = next((s for s in catalog.list_sources() if s['id'] == body['source_id']), None)
            if source is None:
                raise KeyError('Unknown source')
            current = datasets.get(collection_id, body['expected_revision'])
            if current['selection_mode'] == 'pairs':
                raise ValueError('Import into a single-question Dataset; select complete pairs through pair selection')
            keys = [e['key'] for e in source['report'].get('entries', []) if e.get('key')]
            return datasets.revise(collection_id, expected_revision=body['expected_revision'],
                changes={'keys': current['keys'] + keys}, operation_id=request.headers.get('Idempotency-Key'))
        return data_call(operation)

    from architecture_iq.studio.dataset_inputs import DatasetInputs
    inputs = DatasetInputs(catalog, datasets)

    def selected_input(collection_id, body, *, materialize=False):
        allowed = {'revision', 'selection', 'purpose', 'method_id', 'phase'} | ({'preview_hash'} if materialize else set())
        fields(body, allowed, {'revision', 'purpose'} | ({'preview_hash'} if materialize else set()))
        ref = {'collection_id': collection_id, 'revision': body['revision']}
        kwargs = {k: body[k] for k in ('purpose', 'method_id', 'phase') if k in body}
        if materialize:
            return inputs.materialize(ref, body.get('selection', {}), preview_hash=body['preview_hash'], **kwargs)
        return inputs.preview(ref, body.get('selection', {}), **kwargs)

    @api.post(prefix + '/datasets/{collection_id}/selection-preview')
    def selection_preview(collection_id: str, body: dict = Body(...)):
        return data_call(lambda: selected_input(collection_id, body))

    @api.post(prefix + '/datasets/{collection_id}/question-set')
    def freeze_selection(collection_id: str, body: dict = Body(...)):
        return data_call(lambda: selected_input(collection_id, body, materialize=True))

    from architecture_iq.studio.dataset_generation import attach_generation_result, get_generation_attachment

    @api.get(prefix + '/generations/{run_id}/dataset-attachment')
    def generation_attachment(run_id: str):
        def operation():
            api.state.jobs.definition(run_id)
            return get_generation_attachment(datasets, run_id=run_id)
        return data_call(operation)

    @api.post(prefix + '/generations/{run_id}/dataset-attachment')
    def retry_attachment(run_id: str, request: Request, body: dict = Body(...)):
        def operation():
            fields(body, {'target'}, {'target'})
            return attach_generation_result(api.state.jobs, catalog, datasets, run_id=run_id,
                target=body['target'], operation_id=request.headers.get('Idempotency-Key'))
        return data_call(operation)
