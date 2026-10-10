"""Discovery-only empirical snapshots; no scientific admission capability."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .roles import exclusive_lock, read_receipt
from .store import canonical_hash, write_json_atomic


def _read(path):
    return json.loads(path.read_text())


def initial_experience_snapshot() -> dict:
    """Pure empty snapshot shared by first-request preview and durable storage."""
    payload = {'parent_version': None, 'episodes': [], 'lessons': [],
               'operations': [], 'scientific_status': 'unverified'}
    return {**payload, 'version': canonical_hash(payload)}


def compact_question(question: dict) -> dict:
    """Keep public mechanisms and candidate views, clipping only prose."""
    value = copy.deepcopy(question)
    value['prompt'] = value['prompt'][:1600]
    return value


def compact_answer(answer: dict) -> dict:
    return {'valid': bool(answer.get('valid')), 'ranking': copy.deepcopy(answer.get('ranking', [])),
            'rationale': str(answer.get('rationale', ''))[:800]}


def _source(root: Path, reference: dict) -> dict:
    if not isinstance(reference, dict) or set(reference) != {'path', 'receipt_hash'}:
        raise ValueError('Invalid episode source reference')
    path = (root / reference['path']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Episode source escapes run or is missing')
    record = read_receipt(path)
    if record['receipt_hash'] != reference['receipt_hash']:
        raise ValueError('Episode source integrity failure')
    return record['result']


def _relationship(question: dict, manifest: dict) -> dict:
    if manifest.get('practice', {}).get('kind') == 'same_question_practice':
        return {'type': 'same_question_practice', 'question_id': question['id'],
                'independent_evaluation': False}
    for pair in manifest['config'].get('pair_manifest', []):
        for member in pair.get('members', []):
            if member.get('key', member.get('id')) == question['id']:
                return {'type': 'normal_counterfactual_pair', 'pair_key': pair['pair_key'],
                        'pair_id': pair['pair_id'], 'member_role': member['role']}
    return {'type': 'single_attempt', 'question_id': question['id']}


def build_episode(out: Path, *, round_index: int, question: dict,
                  answer_path: Path, feedback_path: Path) -> dict:
    """Build from committed answer and revealed feedback; raw artifacts stay on disk."""
    out = Path(out).resolve()
    refs = {}
    for key, path in [('answer', answer_path), ('feedback', feedback_path)]:
        path = Path(path).resolve()
        if not path.is_relative_to(out):
            raise ValueError('Episode source escapes run')
        refs[key] = {'path': str(path.relative_to(out)), 'receipt_hash': read_receipt(path)['receipt_hash']}
    answer, revealed = _source(out, refs['answer']), _source(out, refs['feedback'])
    episode = {'id': 'E' + canonical_hash({'round': round_index, 'question': question['id']})[:24],
               'round': round_index, 'question': compact_question(question),
               'answer': compact_answer(answer),
               'feedback': {'correct_letter': revealed['feedback']['correct_letter']},
               'source_refs': refs, 'scientific_status': 'unverified',
               'relationship': _relationship(question, _read(out / 'manifest.json'))}
    episode['seal_hash'] = canonical_hash(episode)
    validate_episode(episode, out)
    return episode


def episode_is_sealed(episode: dict) -> bool:
    return (isinstance(episode, dict) and episode.get('scientific_status') == 'unverified'
            and episode.get('question', {}).get('split') == 'discovery'
            and episode.get('seal_hash') == canonical_hash({k: v for k, v in episode.items() if k != 'seal_hash'}))


def validate_episode(episode: dict, out: Path) -> None:
    fields = {'id', 'round', 'question', 'answer', 'feedback', 'source_refs', 'scientific_status', 'seal_hash', 'relationship'}
    if not isinstance(episode, dict) or set(episode) != fields or not episode_is_sealed(episode):
        raise ValueError('Episode must be sealed discovery data')
    manifest = _read(out / 'manifest.json')
    public, private = _read(out / 'public_questions.json'), _read(out / 'private_feedback.json')
    for name, value in [('public_questions.json', public), ('private_feedback.json', private)]:
        if canonical_hash(value) != manifest['inputs'][name]:
            raise ValueError('Frozen episode source integrity failure')
    identifier = episode['question']['id']
    if type(episode['round']) is not int or identifier not in manifest['round_questions'].get(str(episode['round']), []):
        raise ValueError('Episode not in discovery round')
    question = next((q for q in public if q['id'] == identifier and q['split'] == 'discovery'), None)
    if question is None or compact_question(question) != episode['question']:
        raise ValueError('Episode question source mismatch')
    if episode['relationship'] != _relationship(question, manifest):
        raise ValueError('Episode relationship source mismatch')
    if episode['id'] != 'E' + canonical_hash({'round': episode['round'], 'question': identifier})[:24]:
        raise ValueError('Episode identity mismatch')
    if set(episode['source_refs']) != {'answer', 'feedback'}:
        raise ValueError('Episode source refs required')
    for field, directory in [('answer', 'answers'), ('feedback', 'revealed')]:
        expected = f"rounds/{episode['round']}/{directory}/{canonical_hash(identifier)}.json"
        if episode['source_refs'][field].get('path') != expected:
            raise ValueError('Episode answer/feedback source does not match question and round')
    answer = _source(out, episode['source_refs']['answer'])
    revealed = _source(out, episode['source_refs']['feedback'])
    if compact_answer(answer) != episode['answer']:
        raise ValueError('Episode answer source mismatch')
    if (revealed != {'question_id': identifier, 'feedback': private[identifier]}
            or episode['feedback'] != {'correct_letter': private[identifier]['correct_letter']}):
        raise ValueError('Episode feedback source mismatch')


def _strings(value, name):
    if not isinstance(value, list) or len(value) > 16 or any(not isinstance(v, str) or len(v) > 800 for v in value):
        raise ValueError(f'Invalid lesson {name}')
    return copy.deepcopy(value)


def apply_operations(lessons: list[dict], episodes: list[dict], operations: list[dict]) -> list[dict]:
    """Validate model proposals; identity, revision and authority are program-owned."""
    if not isinstance(operations, list) or len(operations) > 12:
        raise ValueError('At most twelve experience operations')
    current = {v['id']: copy.deepcopy(v) for v in lessons}
    episode_ids = {v['id'] for v in episodes}
    touched = set()
    for operation in operations:
        if not isinstance(operation, dict) or operation.get('op') not in {'add', 'edit', 'retire', 'reinforce'}:
            raise ValueError('Invalid experience operation')
        refs = operation.get('source_episode_ids')
        if (not isinstance(refs, list) or not refs or len(refs) > 32
                or any(not isinstance(v, str) or v not in episode_ids for v in refs)):
            raise ValueError('Lesson needs eligible source episode IDs')
        reason = operation.get('reason')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1600:
            raise ValueError('Lesson operation needs reason')
        op = operation['op']
        old = None
        if op != 'add':
            identifier = operation.get('id')
            if not isinstance(identifier, str) or identifier not in current:
                raise ValueError('Unknown lesson ID')
            old = current[identifier]
        else:
            identifier = 'L' + canonical_hash({'text': operation.get('text'), 'source_episode_ids': sorted(set(refs))})[:24]
            if identifier in current:
                raise ValueError('Duplicate lesson; reinforce or edit existing ID')
        if identifier in touched:
            raise ValueError('Only one operation per lesson per publication')
        touched.add(identifier)
        if op in {'add', 'edit'}:
            text = operation.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 2400:
                raise ValueError('Invalid lesson text')
            lesson = {'id': identifier, 'text': text,
                      'conditions': _strings(operation.get('conditions'), 'conditions'),
                      'exceptions': _strings(operation.get('exceptions'), 'exceptions'), 'status': 'active'}
        else:
            lesson = copy.deepcopy(old)
            if op == 'retire':
                lesson['status'] = 'retired'
        lesson.update(revision=(old['revision'] + 1 if old else 1),
                      parent_revision=(old['revision'] if old else None),
                      source_episode_ids=sorted(set(refs) | set(old['source_episode_ids'] if old else [])),
                      scientific_status='unverified', reason=reason)
        current[identifier] = lesson
    return sorted(current.values(), key=lambda value: value['id'])


class ExperienceStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _write(self, payload):
        snapshot = {**payload, 'version': canonical_hash(payload)}
        path = self.root / 'snapshots' / (snapshot['version'] + '.json')
        if path.exists() and _read(path) != snapshot:
            raise ValueError('Immutable experience snapshot integrity failure')
        write_json_atomic(path, snapshot)
        write_json_atomic(self.root / 'CURRENT.json', {'version': snapshot['version']})
        return snapshot

    def current(self) -> dict:
        version = _read(self.root / 'CURRENT.json')['version']
        if not isinstance(version, str) or len(version) != 64 or any(c not in '0123456789abcdef' for c in version):
            raise ValueError('Invalid experience version')
        snapshot = _read(self.root / 'snapshots' / (version + '.json'))
        if snapshot.get('version') != version or canonical_hash({k: v for k, v in snapshot.items() if k != 'version'}) != version:
            raise ValueError('Experience snapshot integrity failure')
        return snapshot

    def initialize(self) -> dict:
        with exclusive_lock(self.root / '.lock'):
            if (self.root / 'CURRENT.json').exists():
                return self.current()
            snapshot = initial_experience_snapshot()
            return self._write({k: v for k, v in snapshot.items() if k != 'version'})

    def publish(self, parent_version: str, episodes: list[dict], operations: list[dict]) -> dict:
        with exclusive_lock(self.root / '.lock'):
            if not isinstance(episodes, list):
                raise ValueError('Episodes must be a list')
            if (not isinstance(parent_version, str) or len(parent_version) != 64
                    or any(c not in '0123456789abcdef' for c in parent_version)):
                raise ValueError('Invalid experience parent version')
            parent_path = self.root / 'snapshots' / (parent_version + '.json')
            if not parent_path.is_file():
                raise ValueError('Unknown experience parent')
            parent = _read(parent_path)
            if parent.get('version') != parent_version or canonical_hash({k: v for k, v in parent.items() if k != 'version'}) != parent_version:
                raise ValueError('Experience parent integrity failure')
            by_id = {e['id']: e for e in parent['episodes']}
            for episode in episodes:
                validate_episode(episode, self.root.parent)
                if episode['id'] in by_id and by_id[episode['id']] != episode:
                    raise ValueError('Immutable episode identity conflict')
                by_id[episode['id']] = copy.deepcopy(episode)
            all_episodes = sorted(by_id.values(), key=lambda v: (v['round'], v['id']))
            for episode in all_episodes:
                validate_episode(episode, self.root.parent)
            lessons = apply_operations(parent['lessons'], all_episodes, operations)
            # Store only allowed proposal fields: model supplied authority is discarded.
            allowed = {'op', 'id', 'text', 'conditions', 'exceptions', 'source_episode_ids', 'reason'}
            safe_operations = [{k: copy.deepcopy(v) for k, v in op.items() if k in allowed} for op in operations]
            payload = {'parent_version': parent_version, 'episodes': all_episodes, 'lessons': lessons,
                       'operations': safe_operations, 'scientific_status': 'unverified'}
            expected = canonical_hash(payload)
            current = self.current()
            if current['version'] == expected:
                return current
            if current['version'] != parent_version:
                raise ValueError('Stale experience parent version')
            return self._write(payload)
