"""Deterministic public selection previews and atomic legacy input freezing."""
from contextlib import closing

from .catalog import Catalog, _hash
from .datasets import DatasetStore, DatasetConflict
from .methods import resolve_method
from .pairs import pair_manifest
from .question_bank import matches, question_summary, validate_filters


class DatasetInputs:
    def __init__(self, catalog: Catalog, datasets: DatasetStore):
        self.catalog, self.datasets = catalog, datasets

    def _select(self, revision, selection):
        if not isinstance(selection, dict) or set(selection) - {'keys', 'pair_keys', 'filters', 'limit', 'seed'}:
            raise ValueError('Unknown Dataset selection fields')
        paired = revision['selection_mode'] == 'pairs'
        field = 'pair_keys' if paired else 'keys'
        wrong = 'keys' if paired else 'pair_keys'
        if wrong in selection or field in selection and 'filters' in selection:
            raise ValueError('Choose explicit complete members or filters, not both')
        units = {p['pair_key']: [m['key'] for m in p['members']] for p in revision['pairs']} if paired else {
            k: [k] for k in revision['keys']}
        filters = validate_filters(selection.get('filters'))
        explicit = selection.get(field)
        if field in selection:
            if not isinstance(explicit, list) or any(not isinstance(k, str) or k not in units for k in explicit):
                raise ValueError('Selection contains members outside the frozen Dataset')
            chosen = list(dict.fromkeys(explicit))
        else:
            chosen = [k for k, members in units.items() if any(
                matches(question_summary(self.catalog, m)[0], filters) for m in members)]
        limit = selection.get('limit')
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('Selection limit must be a positive integer')
        seed = selection.get('seed')
        if 'seed' in selection and type(seed) is not int:
            raise ValueError('Selection seed must be an integer')
        if limit is not None:
            sample = sorted(chosen, key=lambda k: _hash({'seed': seed, 'key': k}))[:limit] if seed is not None else chosen[:limit]
            chosen = [k for k in chosen if k in set(sample)]
        return [m for k in chosen for m in units[k]], chosen if paired else []

    def preview(self, ref: dict, selection: dict, *, purpose: str,
                method_id: str | None = None, phase: str | None = None) -> dict:
        if (not isinstance(ref, dict) or set(ref) != {'collection_id', 'revision'}
                or any(not isinstance(v, str) or not v for v in ref.values())):
            raise ValueError('A fixed Dataset reference is required')
        if purpose not in ('public', 'research', 'evaluation'):
            raise ValueError('Unknown Dataset input purpose')
        if phase not in (None, 'development', 'final') or purpose == 'evaluation' and phase is None:
            raise ValueError('Evaluation requires development or final phase')
        method = resolve_method({'method_id': method_id}) if method_id else None
        revision = self.datasets.get(ref['collection_id'], ref['revision'])
        keys, pair_keys = self._select(revision, selection)
        blockers, questions, hashes, health = [], [], [], []
        def block(key, code, message):
            blockers.append({'key': key, 'code': code, 'message': message})
        if not keys:
            block('', 'empty_selection', '请选择题目')
        if method and revision['selection_mode'] not in method['data_modes']:
            block('', 'method_data_mode', '所选方法不支持此 Dataset 的题目模式')
        if purpose == 'research' and method_id == 'basic_learning' and len(keys) != 1:
            block('', 'basic_requires_one_question', '单题学习需要明确选择一道题')
        for key in keys:
            summary, sources = question_summary(self.catalog, key)
            hashes.append(summary['hash'])
            health.append({'key': key, 'summary': summary, 'sources': sources})
            try:
                questions.append(self.catalog.get_question(key)['public'])
            except (OSError, ValueError, KeyError, TypeError):
                questions.append({'id': key, 'unavailable': True})
            readiness = 'rag_ready' if purpose == 'public' else 'evaluation_ready' if purpose == 'evaluation' or method_id == 'rule_refinement' else 'kb_ready'
            if method_id == 'rule_refinement':
                try:
                    from .rule_refinement.pool import _case
                    _case(self.catalog.get_question(key))
                except (ValueError, KeyError, OSError, TypeError):
                    block(key, 'invalid_rule_material', '规则匹配需要完整合法的公开候选规格')
            if not summary.get(readiness):
                block(key, 'question_unavailable', '题目资料不满足当前用途，请检查来源和配置')
            expected_split = phase if purpose == 'evaluation' else 'discovery' if purpose == 'research' else None
            if expected_split and summary.get('split') != expected_split:
                block(key, 'wrong_split', f'题目不属于 {expected_split} 分区')
        selected_pairs = [next(p for p in revision['pairs'] if p['pair_key'] == k) for k in pair_keys]
        for pair in selected_pairs:
            try:
                current = pair_manifest([self.catalog.get_question(m['key']) for m in pair['members']])
                if current['pair_key'] != pair['pair_key'] or purpose != 'public' and not current.get(
                        'evaluation_ready' if purpose == 'evaluation' or method_id == 'rule_refinement' else 'kb_ready'):
                    block(pair['pair_key'], 'pair_unavailable', '完整题对身份或可用性检查失败')
            except (OSError, ValueError, KeyError, TypeError):
                block(pair['pair_key'], 'pair_unavailable', '完整题对来源不可用')
        if keys and not blockers and purpose != 'public' and method_id != 'rule_refinement':
            try:
                self.catalog._question_set_body(revision['name'], keys)
            except ValueError as exc:
                block('', 'invalid_question_set', str(exc))
        binding = {**ref, 'selection': selection, 'keys': keys, 'hashes': hashes, 'pair_keys': pair_keys}
        fingerprint = _hash({'binding': binding, 'purpose': purpose, 'method_id': method_id, 'phase': phase,
                             'health': health, 'blockers': blockers})
        return {'binding': binding, 'preview_hash': fingerprint, 'can_apply': not blockers,
                'blockers': blockers, 'questions': questions, 'count': len(keys), 'pair_count': len(pair_keys)}

    def materialize(self, ref: dict, selection: dict, *, purpose: str, preview_hash: str,
                    method_id: str | None = None, phase: str | None = None) -> dict:
        if purpose == 'public':
            raise ValueError('Public input uses its preview binding, not a private question set')
        # Prevent source imports from racing the availability check and publication.
        with closing(self.catalog._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            preview = self.preview(ref, selection, purpose=purpose, method_id=method_id, phase=phase)
            if not isinstance(preview_hash, str) or preview_hash != preview['preview_hash']:
                raise DatasetConflict('Dataset selection preview changed; preview again')
            if not preview['can_apply']:
                raise ValueError('; '.join(b['message'] for b in preview['blockers']))
            revision = self.datasets.get(ref['collection_id'], ref['revision'])
            pairs = [next(p for p in revision['pairs'] if p['pair_key'] == key) for key in preview['binding']['pair_keys']]
            if method_id == 'rule_refinement':
                records = [self.catalog.get_question(k, include_private=True) for k in preview['binding']['keys']]
                body = {'schema_version': 1, 'name': revision['name'], 'keys': preview['binding']['keys'],
                        'hashes': preview['binding']['hashes'], 'dataset_binding': preview['binding'],
                        'questions': [r['public'] for r in records],
                        'feedback': {r['metadata']['key']: r['feedback'] for r in records}}
                if revision['selection_mode'] == 'pairs':
                    body.update(selection_mode='pairs', pairs=pairs, pair_keys=preview['binding']['pair_keys'],
                                pair_count=len(pairs), count=len(records))
            else:
                body = self.catalog._bound_question_set_body(revision['name'], preview['binding']['keys'],
                    preview['binding'], pairs if revision['selection_mode'] == 'pairs' else None)
            identifier = self.catalog._store_question_set(body, conn)
        return self.catalog.get_question_set(identifier)
