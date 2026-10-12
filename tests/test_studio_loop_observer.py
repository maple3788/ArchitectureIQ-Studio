"""The observer never executes a model or a GT experiment."""
import json
import threading
import sqlite3
import zlib

import pytest

from architecture_iq.studio.loop_observer import LoopObserver, ObserverConfig, SSHSourceReader


def configuration(**overrides):
    return ObserverConfig.from_dict({
        'source_id': 'test', 'host': 'authorized.test', 'user': 'researcher',
        'port': 22, 'root': '/private/loop state', 'python': '/private/venv/bin/python',
        'poll_seconds': 5, 'timeout_seconds': 15, **overrides,
    }, authorized_host='authorized.test')


def capture(count=1):
    return {
        'source_updated_at': 12,
        'execution': {'status': 'unknown', 'stop_requested': False, 'alert': False},
        'round': {'index': 1, 'completed_stages': ['plan'], 'next_stage': 'build',
                  'plan': {'total': 30, 'target': 18, 'explore': 12},
                  'build': {'completed': count, 'ok': count, 'failed': 0}},
        'kb': {'claims': 1, 'candidate': 1, 'verified': 0, 'flagged': 0, 'retired': 0},
        'evidence': {'questions': 0, 'verdicts': 0},
        'claims': [{'id': 'C1', 'version': 2, 'status': 'candidate', 'text': 'A rule'}],
        'rounds': [{'index': 1, 'completed': False}], 'thresholds': {},
        'claim_details': {'C1': {'claim': {'id': 'C1', 'version': 2}, 'history': [],
                                'evidence': [], 'evidence_total': 0, 'evidence_truncated': False}},
        'round_details': {'1': {'index': 1, 'score': None}},
    }


def test_durable_change_only_journal_and_reopen(tmp_path):
    value = capture()
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value)
    assert observer.snapshot()['sync']['status'] == 'connecting'
    assert observer.poll_once()
    first = observer.snapshot()
    assert first['sequence'] == 1 and first['execution']['status'] == 'unknown'
    assert 'claim_details' not in first and 'round_details' not in first
    value['captured_at'] = 999  # Poll time is not a source content change.
    observer.poll_once()
    assert observer.snapshot()['sequence'] == 1
    value['round']['build']['ok'] = 2
    observer.poll_once()
    reopened = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value)
    assert reopened.snapshot()['sequence'] == 2
    assert [item['sequence'] for item in reopened.events(after=1)] == [2]
    assert reopened.claim('C1')['claim']['version'] == 2
    assert reopened.round(1)['score'] is None
    with pytest.raises(KeyError):
        reopened.claim('../credentials')


def test_disconnect_keeps_previous_capture_and_hides_error(tmp_path):
    source = [capture()]
    def reader(_):
        if isinstance(source[0], Exception):
            raise source[0]
        return source[0]
    observer = LoopObserver(tmp_path, config=configuration(), reader=reader)
    observer.poll_once()
    first = observer.snapshot()
    source[0] = RuntimeError('SECRET_SENTINEL /private/root user@server')
    assert not observer.poll_once()
    stale = observer.snapshot()
    assert stale['sequence'] == 1 and stale['claims'] == first['claims']
    assert stale['sync']['status'] == 'disconnected'
    assert stale['sync']['last_success_at'] == first['sync']['last_success_at']
    assert 'SECRET_SENTINEL' not in json.dumps(stale)
    source[0] = capture()
    observer.poll_once()
    assert observer.snapshot()['sequence'] == 1
    assert observer.snapshot()['sync']['status'] == 'connected'


def test_unconfigured_never_calls_reader(tmp_path):
    observer = LoopObserver(tmp_path, reader=lambda _: pytest.fail('no network'))
    observer.start()
    assert not observer.poll_once()
    observer.stop()
    assert observer.snapshot()['configured'] is False
    assert observer.snapshot()['sync']['status'] == 'unconfigured'


@pytest.mark.parametrize('values', [
    {'host': 'other.test'}, {'host': '-oProxyCommand=bad'}, {'port': 0},
    {'root': 'relative'}, {'python': '/bin/sh'}, {'poll_seconds': 0},
    {'timeout_seconds': True}, {'source_id': '../escape'}, {'user': 'bad;command'},
])
def test_configuration_rejects_unsafe_or_unauthorized(values):
    with pytest.raises(ValueError, match='观察连接配置不可用'):
        configuration(**values)


def test_private_config_not_in_capture_and_source_changes_are_isolated(tmp_path):
    value = capture()
    value.update(config={'password': 'SECRET_SENTINEL'}, root='/private/root', captured_at=1)
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value)
    observer.poll_once()
    assert 'SECRET_SENTINEL' not in json.dumps(observer.snapshot())
    other = LoopObserver(tmp_path, config=configuration(root='/private/different'), reader=lambda _: capture())
    assert other.snapshot()['sequence'] == 0


def test_ssh_transport_uses_only_collector_stdin_and_quoted_fixed_command(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return type('Result', (), {'returncode': 0, 'stdout': json.dumps(capture()), 'stderr': ''})()
    monkeypatch.setattr('architecture_iq.studio.loop_observer.subprocess.run', run)
    assert SSHSourceReader()(configuration())['round']['index'] == 1
    argv, args = calls[0]
    assert argv[0] == 'ssh' and 'researcher@authorized.test' in argv
    assert argv[-1] == "/private/venv/bin/python - '/private/loop state'"
    assert 'def collect(' in args['input']
    assert 'shell' not in args and args['timeout'] == 15
    assert 'loop.py status' not in args['input']


def test_single_collector_per_source_even_with_two_observers(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def slow(_):
        entered.set()
        assert release.wait(3)
        return capture()
    first = LoopObserver(tmp_path, config=configuration(), reader=slow)
    second = LoopObserver(tmp_path, config=configuration(), reader=lambda _: pytest.fail('duplicate reader'))
    thread = threading.Thread(target=first.poll_once)
    thread.start()
    try:
        assert entered.wait(2)
        assert not second.poll_once()
    finally:
        release.set()
        thread.join(3)
    assert second.snapshot()['sequence'] == 1


def test_incomplete_payload_does_not_replace_last_good_capture(tmp_path):
    value = [capture()]
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value[0])
    observer.poll_once()
    value[0] = {'claims': []}
    assert not observer.poll_once()
    assert observer.snapshot()['sequence'] == 1
    assert observer.snapshot()['sync']['status'] == 'disconnected'


def test_private_configuration_requires_authorized_host_without_enabling_execution(tmp_path, monkeypatch):
    from dataclasses import asdict
    path = tmp_path / 'private-config.json'
    path.write_text(json.dumps(asdict(configuration())))
    monkeypatch.setenv('STUDIO_KB_LOOP_CONFIG', str(path))
    monkeypatch.delenv('ARCHITECTURE_IQ_KB_EXECUTION_HOST', raising=False)
    monkeypatch.setenv('ARCHITECTURE_IQ_KB_AUTHORIZED_HOST', '')
    with pytest.raises(ValueError, match='观察连接配置不可用'):
        ObserverConfig.from_environment()
    monkeypatch.setenv('ARCHITECTURE_IQ_KB_AUTHORIZED_HOST', 'authorized.test')
    assert ObserverConfig.from_environment() == configuration()
    import os
    assert 'ARCHITECTURE_IQ_KB_EXECUTION_HOST' not in os.environ


def test_capture_is_compressed_and_legacy_text_rows_still_replay(tmp_path):
    value = [capture()]
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value[0])
    observer.poll_once()
    with sqlite3.connect(observer.database) as connection:
        first = connection.execute('SELECT payload FROM captures').fetchone()[0]
        assert isinstance(first, bytes)
        assert json.loads(zlib.decompress(first)) == value[0]
        connection.execute('UPDATE captures SET payload=?', (json.dumps(value[0]),))
    value[0] = capture(2)
    observer.poll_once()
    assert [row['round']['build']['ok'] for row in observer.events()] == [1, 2]
    assert observer.claim('C1')['claim']['id'] == 'C1'


def test_persisted_connection_becomes_stale_without_polls(tmp_path, monkeypatch):
    now = [1000]
    monkeypatch.setattr('architecture_iq.studio.loop_observer.time.time', lambda: now[0])
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: capture())
    observer.poll_once()
    assert observer.sync()['status'] == 'connected'
    now[0] += 21  # max(2 * poll, timeout + poll) is 20 seconds.
    reopened = LoopObserver(tmp_path, config=configuration(), reader=lambda _: capture())
    assert reopened.sync()['status'] == 'disconnected'
    assert reopened.snapshot()['sequence'] == 1
    assert reopened.sync()['last_success_at'] == 1000
    reopened.poll_once()
    assert reopened.sync()['status'] == 'connected'
    assert reopened.snapshot()['sequence'] == 1


def test_ssh_source_change_gets_one_bounded_retry(monkeypatch):
    calls = []
    def run(_argv, **kwargs):
        calls.append(kwargs)
        result = {'returncode': 1, 'stdout': '{"error":"source_unavailable"}', 'stderr': ''} if len(calls) == 1 else {
            'returncode': 0, 'stdout': json.dumps(capture()), 'stderr': ''}
        return type('Result', (), result)()
    monkeypatch.setattr('architecture_iq.studio.loop_observer.subprocess.run', run)
    assert SSHSourceReader()(configuration())['round']['index'] == 1
    assert len(calls) == 2 and 0 < calls[1]['timeout'] <= calls[0]['timeout'] <= 15
