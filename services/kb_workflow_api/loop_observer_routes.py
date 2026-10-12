"""Read-only HTTP/SSE views of already persisted external loop observations."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse


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
