"""Read existing public artifacts without touching the benchmark or disclosing GT."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from architecture_iq.studio import loop_source
from architecture_iq.studio.loop_observer import LoopObserver, ObserverConfig
from services.kb_workflow_api.loop_observer_routes import register_loop_observer_routes
from test_studio_loop_source import dump, rows
from test_studio_loop_observer import configuration, capture


@pytest.fixture
def question_source(tmp_path):
    root, artifacts = tmp_path / 'loop', tmp_path / 'artifacts'
    qrel = 'datasets/xor_classification/ds1/questions/run1/q_example'
    crel = 'datasets/xor_classification/ds1/candidates/set1/c_a'
    question = {'question_id': 'q_example', 'family': 'xor_classification', 'dataset_id': 'ds1',
                'type': 'architecture_only', 'profile': 'test', 'correct_letter': 'A',
                'significance': {'winner': 'SECRET_GT'}, 'evaluation': {'selection_metric': 'test_ce'},
                'choices': [{'letter': 'A', 'candidate_id': 'c_a', 'candidate_path': crel}]}
    qpath = dump(artifacts, qrel + '/question.json', question)
    (qpath.parent / 'prompt.txt').write_text('Original public question\n## Dataset\nXOR rule\n## Choices\nChoice A')
    dump(artifacts, 'datasets/xor_classification/ds1/dataset_spec.json', {
        'dataset_id': 'ds1', 'family': 'xor_classification', 'selection_metric': 'test_ce',
        'params': {'input_dim': 2, 'train_size': 128, 'secret': 'SECRET_PARAM'}, 'winner': 'SECRET_GT'})
    dump(artifacts, crel + '/candidate_spec.json', {
        'candidate_id': 'c_a', 'dataset_id': 'ds1', 'family': 'xor_classification',
        'model': {'type': 'mlp', 'depth': 2, 'width': 16, 'secret': 'SECRET_MODEL'},
        'optimizer': {'type': 'SGD', 'lr': 0.01}, 'budget': {'training_steps': 10, 'batch_size': 4, 'total_samples_seen': 40},
        'summary': {'test_accuracy': 'SECRET_GT'}, 'source_path': '/PRIVATE_SOURCE'})
    (artifacts / crel / 'model.py').write_text('class Model:\n    pass\n')
    rows(root, 'rounds/round_0001/build.jsonl', [{'item_id': 'r0001-0000', 'status': 'ok',
          'question_id': 'q_example', 'question_path': str(qpath)}])
    return root, artifacts, qpath


def collect_question(source):
    root, artifacts, _ = source
    return loop_source.collect_question(root, artifacts, 'q_example')


def test_read_canonical_prompt_and_choice_letters_without_regenerating(question_source):
    root, artifacts, qpath = question_source
    before = {p: p.read_bytes() for p in root.parent.rglob('*') if p.is_file()}
    value = collect_question(question_source)
    assert value['public']['prompt'] == (qpath.parent / 'prompt.txt').read_text()
    assert value['public']['choices'][0] == {'id': 'c_a', 'letter': 'A', 'view': {}}
    assert value['metadata']['metric'] == 'test_ce'
    assert value['detail']['choices'][0]['files']['candidate_spec.json']['model']['depth'] == 2
    assert 'correct_letter' not in json.dumps(value) and 'significance' not in json.dumps(value)
    assert {p: p.read_bytes() for p in root.parent.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('identifier', ['../q_example', '/q_example', 'q_example; echo bad', '', 'a' * 1024])
def test_question_identifier_cannot_select_a_path(question_source, identifier):
    with pytest.raises((ValueError, KeyError)):
        loop_source.collect_question(question_source[0], question_source[1], identifier)


def test_unfinished_build_record_cannot_authorize_question_artifacts(question_source):
    root, artifacts, qpath = question_source
    path = root / 'rounds/round_0001/build.jsonl'
    path.write_text(json.dumps({'item_id': 'x', 'status': 'ok', 'question_id': 'q_example', 'question_path': str(qpath)}))
    with pytest.raises(KeyError):
        collect_question(question_source)
    rows(root, 'rounds/round_0001/build.jsonl', [{'item_id': 'x', 'status': 'failed', 'question_id': 'q_example', 'question_path': str(qpath)}])
    with pytest.raises(KeyError):
        collect_question(question_source)


def test_question_and_candidate_ids_must_match_source_record(question_source):
    _, _, qpath = question_source
    value = json.loads(qpath.read_text()); value['question_id'] = 'q_other'; qpath.write_text(json.dumps(value))
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)
    value['question_id'] = 'q_example'; value['choices'][0]['candidate_id'] = 'c_other'; qpath.write_text(json.dumps(value))
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)


@pytest.mark.parametrize('reference', ['../outside/candidate', '/private/candidate'])
def test_candidate_paths_must_stay_inside_explicit_artifact_root(question_source, reference):
    _, _, qpath = question_source
    value = json.loads(qpath.read_text()); value['choices'][0]['candidate_path'] = reference; qpath.write_text(json.dumps(value))
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)


def test_prompt_link_and_half_written_json_are_rejected(question_source):
    root, _, qpath = question_source
    prompt = qpath.parent / 'prompt.txt'; prompt.unlink(); prompt.symlink_to(root / 'rounds/round_0001/build.jsonl')
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)
    prompt.unlink(); prompt.write_text('Public prompt'); qpath.write_text('{"question_id":')
    with pytest.raises(ValueError):
        collect_question(question_source)


def test_question_file_size_is_bounded(question_source, monkeypatch):
    monkeypatch.setattr(loop_source, 'MAX_FILE_BYTES', 8)
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)


def test_artifact_change_while_reading_rejects_whole_question(question_source, monkeypatch):
    original = loop_source.Reader.finish
    def mutate(reader):
        if reader.root == question_source[1]:
            (question_source[2].parent / 'prompt.txt').write_text('Changed during capture')
        return original(reader)
    monkeypatch.setattr(loop_source.Reader, 'finish', mutate)
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)


def test_observer_projects_and_persists_immutable_question_independently_of_sse(tmp_path, question_source):
    def reader(_config, identifier):
        assert identifier == 'q_example'
        return collect_question(question_source)
    observer = LoopObserver(tmp_path / 'state', config=configuration(artifact_root='/private/artifacts'),
                            reader=lambda _: capture(), question_reader=reader)
    observer.poll_once()
    value = observer.question('q_example')
    assert value['public']['choices'][0]['letter'] == 'A'
    assert value['detail']['choices'][0]['files']['candidate_spec.json']['model'] == {'type': 'mlp', 'depth': 2, 'width': 16}
    assert 'SECRET_' not in json.dumps(value) and '/PRIVATE_SOURCE' not in json.dumps(value)
    assert value['observation']['content_hash'] and value['observation']['captured_at'] > 0
    assert 'Original public question' not in json.dumps(observer.events(after=0))
    def unavailable(*_):
        raise RuntimeError('private SSH endpoint')
    reopened = LoopObserver(tmp_path / 'state', config=configuration(artifact_root='/private/artifacts'),
                            question_reader=unavailable)
    assert reopened.question('q_example') == value
    with sqlite3.connect(observer.database) as conn:
        assert conn.execute('select count(*) from question_artifacts').fetchone()[0] == 1


def test_private_artifact_root_is_optional_isolated_and_bounded():
    first = configuration()
    other = configuration(artifact_root='/private/artifacts')
    assert first.identity != other.identity
    for root in ['relative', '/path/../private', '/path\ncommand', '']:
        with pytest.raises(ValueError):
            configuration(artifact_root=root)


def test_question_api_hides_private_failures_and_does_not_accept_unconfigured_reads(tmp_path):
    from fastapi import FastAPI
    def unavailable(*_):
        raise RuntimeError('SECRET private SSH endpoint')
    observer = LoopObserver(tmp_path, config=configuration(artifact_root='/private/artifacts'), question_reader=unavailable)
    app = FastAPI(); register_loop_observer_routes(app, observer=observer)
    client = TestClient(app)
    response = client.get('/api/studio/kb-loop/questions/q_example')
    assert response.status_code == 503 and 'SECRET' not in response.text
    observer.question_reader = lambda *_: (_ for _ in ()).throw(KeyError('PRIVATE_ARTIFACT_PATH'))
    response = client.get('/api/studio/kb-loop/questions/q_example')
    assert response.status_code == 404 and 'PRIVATE_' not in response.text
    unconfigured = FastAPI(); register_loop_observer_routes(unconfigured, observer=LoopObserver(tmp_path / 'empty'))
    assert TestClient(unconfigured).get('/api/studio/kb-loop/questions/q_example').status_code == 503


def test_source_only_sends_public_spec_fields_over_observer_transport(question_source):
    value = collect_question(question_source)
    # Even the SSH payload must omit unknown GT/config fields, before the
    # stricter shared Catalog projection and persistence on the local host.
    assert 'SECRET_' not in json.dumps(value)
    assert '/PRIVATE_SOURCE' not in json.dumps(value)


def test_source_rejects_question_receipt_outside_allowed_root(question_source, tmp_path):
    root, artifacts, qpath = question_source
    outside = tmp_path / 'other/q_example/question.json'
    outside.parent.mkdir(parents=True)
    outside.write_text(qpath.read_text())
    rows(root, 'rounds/round_0001/build.jsonl', [{'item_id': 'x', 'status': 'ok', 'question_id': 'q_example', 'question_path': str(outside)}])
    with pytest.raises(loop_source.SourceUnavailable):
        collect_question(question_source)


def test_question_cache_detects_changed_frozen_content(tmp_path, question_source):
    observer = LoopObserver(tmp_path / 'state', config=configuration(artifact_root='/private/artifacts'),
                            question_reader=lambda *_: collect_question(question_source))
    first = observer.question('q_example')
    with sqlite3.connect(observer.database) as conn:
        conn.execute("UPDATE question_artifacts SET content_hash='invalid'")
    with pytest.raises(RuntimeError, match='integrity'):
        observer.question('q_example')


def test_question_transport_executes_only_studio_reader_and_safe_arguments(question_source, monkeypatch):
    import subprocess
    import sys
    from architecture_iq.studio.loop_observer import SSHSourceReader
    original_run = subprocess.run
    calls = []
    def run(argv, **kwargs):
        import shlex
        calls.append(argv)
        command = shlex.split(argv[-1])
        assert command[1:5] == ['-', str(question_source[0]), '--question', str(question_source[1])]
        assert command[5] in {'q_example', 'q_missing'}
        return original_run([sys.executable, *command[1:]], **kwargs)
    monkeypatch.setattr('architecture_iq.studio.loop_observer.subprocess.run', run)
    config = configuration(root=str(question_source[0]), artifact_root=str(question_source[1]))
    value = SSHSourceReader().question(config, 'q_example')
    assert value['public']['id'] == 'q_example' and len(calls) == 1
    with pytest.raises(KeyError):
        SSHSourceReader().question(config, 'q_missing')


def test_legacy_observer_journal_reopens_when_artifact_root_is_absent(tmp_path):
    # Identity and schema written by the released observer, before the optional
    # artifact root existed. Adding that option must not orphan existing runs.
    legacy = tmp_path / 'loop_observer/dfe8550584b2ad2a7598c16ddfb60eb3c313c4e2b60e277b12b2a34d002fe1a9'
    legacy.mkdir(parents=True)
    with sqlite3.connect(legacy / 'observations.sqlite3') as conn:
        conn.execute('CREATE TABLE captures (sequence INTEGER PRIMARY KEY AUTOINCREMENT, digest TEXT NOT NULL, captured_at REAL NOT NULL, payload TEXT NOT NULL)')
        conn.execute('INSERT INTO captures VALUES (1,?,12,?)', ('legacy-digest', json.dumps(capture(9))))
    observer = LoopObserver(tmp_path, config=configuration())
    assert observer.snapshot()['round']['build']['ok'] == 9
    assert observer.snapshot()['sequence'] == 1
