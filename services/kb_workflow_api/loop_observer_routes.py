"""Read-only HTTP/SSE views of already persisted external loop observations."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from architecture_iq.studio.loop_observer import ObservationConflict


def _frame(event, value, sequence=None):
    identifier = f'id: {sequence}\n' if sequence is not None else ''
    return identifier + f'event: {event}\ndata: ' + json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n\n'


async def observation_events(observer, request, *, after=0):
    cursor = after
    sync = await asyncio.to_thread(observer.sync)
    yield _frame('sync', {'sync': sync})
    if not observer.configured:
        return
    heartbeat = time.monotonic()
    while not await request.is_disconnected():
        records = await asyncio.to_thread(observer.events, after=cursor)
        for value in records:
            cursor = value['sequence']
            yield _frame('snapshot', value, cursor)
        latest_sync = await asyncio.to_thread(observer.sync)
        if latest_sync != sync:
            sync = latest_sync
            yield _frame('sync', {'sync': sync})
            heartbeat = time.monotonic()
        elif time.monotonic() - heartbeat >= 15:
            yield ': heartbeat\n\n'
            heartbeat = time.monotonic()
        if len(records) < 200:
            await asyncio.sleep(0.5)


def register_loop_observer_routes(api, *, observer):
    prefix = '/api/studio/kb-loop'

    @api.get(prefix)
    def snapshot():
        return observer.snapshot()

    @api.get(prefix + '/claims/{identifier}')
    def claim(identifier: str):
        try:
            return observer.claim(identifier)
        except KeyError as exc:
            raise HTTPException(404, '命题记录不可用') from exc

    @api.get(prefix + '/rounds/{number}')
    def round_detail(number: int = Path(..., ge=1)):
        try:
            return observer.round(number)
        except KeyError as exc:
            raise HTTPException(404, '轮次记录不可用') from exc

    @api.get(prefix + '/questions/{identifier}')
    def question(identifier: str):
        try:
            return observer.question(identifier)
        except KeyError as exc:
            raise HTTPException(404, '来源尚无这道题的完整题面') from exc
        except Exception as exc:
            raise HTTPException(503, '完整题面暂时无法读取，请稍后重试') from exc

    @api.get(prefix + '/questions/{identifier}/evidence')
    def question_evidence(identifier: str,
                          source_identity: str = Query(..., pattern=r'^[0-9a-f]{64}$'),
                          sequence: int = Query(..., ge=1, le=2**63-1),
                          claim_id: str | None = Query(None, min_length=1, max_length=1000),
                          claim_version: int | None = Query(None, ge=1, le=100000)):
        try:
            return observer.question_evidence(identifier, source_identity=source_identity, sequence=sequence,
                                               claim_id=claim_id, claim_version=claim_version)
        except ObservationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, '题目或知识的阅读记录无效，请重新打开后重试') from exc

    @api.get(prefix + '/stream')
    def stream(request: Request, after: int = Query(0, ge=0, le=2**63-1)):
        previous = request.headers.get('last-event-id')
        if previous is not None:
            try:
                previous_id = int(previous)
                if not 0 <= previous_id <= 2**63-1:
                    raise ValueError()
            except ValueError as exc:
                raise HTTPException(400, 'Invalid Last-Event-ID') from exc
            after = max(after, previous_id)
        return StreamingResponse(observation_events(observer, request, after=after),
                                 media_type='text/event-stream', headers={
                                     'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                                 })
