"""Public-spec knowledge applicability before a human chooses an answer."""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory

from architecture_iq.kb.rules import match_rule, public_views
from .human_practice import _observed_question
from .knowledge import resolve_initial_knowledge
from .rule_refinement.inputs import resolve_rule_knowledge
from .rule_refinement.pool import _case
from .task_answers import formal_rule_admission
from .task_explanations import _expression


def _latest_libraries(items):
    latest, other = {}, []
    for item in items:
        library = item.get('library') or {}
        if not library.get('id'):
            other.append(item)
            continue
        key = library['id']
        old = latest.get(key)
        if old is None or library.get('version_order', 0) > old['library'].get('version_order', 0):
            latest[key] = item
    return [*other, *latest.values()]


def _conditions(rule):
    values = []
    if rule.get('scope') is not None:
        values.append('适用条件：' + _expression(rule['scope']))
    for key, label in (('same', '保持相同'), ('differ', '比较差异')):
        if rule.get(key):
            values.append(label + '：' + '、'.join(rule[key]))
    if 'max_param_ratio' in rule:
        values.append(f"参数量比值不超过 {rule['max_param_ratio']}")
    return values or ['依据规则所描述的公开配置进行比较，无额外适用条件。']


def _record_and_inventory(catalog, observer, evolution, inventory, source, reference):
    if not isinstance(source, dict):
        raise ValueError('Invalid public question source')
    capture = None
    if source.get('kind') == 'catalog':
        if (set(source) != {'kind', 'key'} or not isinstance(source['key'], str)
                or not 1 <= len(source['key']) <= 512):
            raise ValueError('Invalid catalog question reference')
        record = (evolution.get_question(source['key'], include_private=False)
                  if source['key'].startswith('evolution_') else
                  catalog.get_question(source['key'], include_private=False))
    elif source.get('kind') == 'knowledge_evolution':
        record = _observed_question(observer, source)
        capture = observer.capture(**source['observation'])
        # _case validates the same public specifications used by Task. The
        # observer's frozen public artifact has its own hash instead of a key.
        record = {**record, 'metadata': {**record.get('metadata', {}),
                  'key': source['question_id'], 'hash': source['expected_question_hash']}}
    else:
        raise ValueError('Unknown public question source')

    items = [item for item in inventory.get('items', []) if item.get('kind') in {'formal', 'research_rules'}]
    if reference is not None:
        if (not isinstance(reference, dict) or set(reference) != {'id', 'version'}
                or any(not isinstance(reference[key], str) or not 1 <= len(reference[key]) <= 512
                       for key in ('id', 'version'))):
            raise ValueError('Invalid knowledge reference')
        if reference['id'].startswith('evolution_kb_'):
            items = [evolution.resolve_kb(reference)]
        else:
            items = [item for item in items if all(item.get(key) == value for key, value in reference.items())]
        if len(items) != 1:
            raise KeyError('Knowledge snapshot unavailable')
    else:
        items = _latest_libraries(items)
        if capture is not None:
            # Reuse the Task adapter's source-status gates and canonical import
            # without creating a Task, updating a KB head, or freezing user state.
            from .evolution_task_sources import EvolutionTaskSources
            with TemporaryDirectory(prefix='studio-public-knowledge-') as directory:
                item = EvolutionTaskSources(Path(directory), observer)._freeze_kb(capture, update_head=False)
            if item is not None:
                items.append(item)
    return record, items


def applicable_knowledge(catalog, observer, evolution, inventory, body):
    if not isinstance(body, dict) or set(body) - {'source', 'knowledge_ref'} or 'source' not in body:
        raise ValueError('Only a public question source and optional knowledge reference are accepted')
    record, items = _record_and_inventory(catalog, observer, evolution, inventory,
                                         body['source'], body.get('knowledge_ref'))
    case = _case(record)
    views = public_views(case['dataset_spec'], case['candidate_specs'])
    choices = [{key: choice[key] for key in ('id', 'letter')} for choice in case['question']['choices']]
    result, unavailable = [], False
    for item in sorted(items, key=lambda row: (row['id'], row['version'])):
        try:
            if item['kind'] == 'formal':
                resolve_initial_knowledge({key: item[key] for key in ('id', 'version')}, {'items': [item]})
            snapshot, _, _ = resolve_rule_knowledge(catalog, {'items': [item]},
                                                   {key: item[key] for key in ('id', 'version')})
            admission = formal_rule_admission(case['question'], item) if item['kind'] == 'formal' else None
            matched = []
            for rule in snapshot['rules']:
                metadata = rule.get('metadata', {})
                if rule['state'] != 'active' or metadata.get('inject') is False:
                    continue
                pairs = []
                for a, b in combinations(range(len(choices)), 2):
                    if admission is not None and not admission(rule, views[a], views[b]):
                        continue
                    # The canonical matcher is used only as an applicability
                    # predicate. Never return its preferred candidate or a graph.
                    if match_rule(rule['rule'], views[a], views[b]) is not None:
                        pairs.append({'candidates': [choices[a], choices[b]],
                                      'reasons': ['两项公开配置满足这条规则的适用条件与比较条件。']})
                if not pairs:
                    continue
                shown = {key: deepcopy(rule[key]) for key in ('rule_id', 'revision', 'text', 'rule')}
                shown.update(validity_status='replicated_in_scope' if admission else metadata.get('validity_status', 'proposed'),
                             conditions=_conditions(rule['rule']), matched_pairs=pairs)
                statuses = sorted({ref['source_status'] for ref in rule.get('source_refs', [])
                                   if ref.get('source_status') in {'candidate', 'verified', 'flagged', 'retired'}})
                if statuses:
                    shown['source_status'] = '、'.join(statuses)
                matched.append(shown)
            if matched:
                kb = {key: item[key] for key in ('id', 'version', 'name', 'kind')}
                kb['verification'] = 'per_rule_scope' if item['kind'] == 'formal' else 'research_hypothesis'
                if item.get('source_kind') == 'knowledge_evolution':
                    kb['source_kind'] = 'knowledge_evolution'
                result.append({'kb': kb, 'rules': matched})
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            unavailable = True
    response = {'scope': 'public_applicability', 'feedback_released': False,
                'items': result, 'total': len(result)}
    if not result:
        response['notice'] = '当前公开配置没有匹配到可用知识规则。'
    if unavailable:
        response['notice'] = '部分知识版本未通过公开资料校验，已略过；仅展示可核对的匹配规则。'
    return response
