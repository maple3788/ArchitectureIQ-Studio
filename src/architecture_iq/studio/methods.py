"""Versioned paper-inspired recipes over the existing scientific execution core.

Descriptors are server-owned, copied on read and frozen into new runs. They do
not grant tools, bypass evidence gates, or execute instructions from papers.
"""
from __future__ import annotations

import copy

from architecture_iq.kb.store import canonical_hash

METHOD_SETTINGS = {'method_id', 'method_version', 'loop_mode', 'stop_after_no_change_rounds',
                   'use_previous_experience', 'record_conditions'}


def _step(identifier: str, stage: str, label: str, *nodes: str) -> dict:
    return {'id': identifier, 'stage_id': stage, 'label': label, 'node_ids': list(nodes)}


def _recipe(identifier: str, name: str, description: str, *, paired=False, memory=False) -> dict:
    steps = [
        _step('assemble', 'data', '组装题目与材料', 'input'),
        _step('solve', 'harness', '独立作答', 'solver'),
        _step('commit', 'harness', '保存答案', 'commit'),
        _step('feedback', 'harness', '对照真实反馈', 'reveal'),
    ]
    if paired:
        steps += [_step('pair_induction', 'harness', '从正常题归纳', 'discoverer'),
                  _step('pair_transfer', 'harness', '预测反事实结果', 'solver'),
                  _step('pair_revision', 'harness', '修订条件与例外', 'discoverer')]
    else:
        steps.append(_step('hypothesize', 'harness', '提出可检验假说', 'discoverer'))
    steps += [_step('skeptic', 'harness', '检查假说', 'skeptic'),
              _step('experiment', 'harness', '执行受控实验', 'experiment'),
              _step('confirmation', 'harness', '独立确认（按配置）', 'confirmation'),
              _step('analysis', 'harness', '分析证据', 'analyst')]
    if memory:
        steps.append(_step('experience_consolidate', 'harness', '整理跨题经验', 'discoverer'))
    steps += [_step('curate', 'kb', '整理知识修改', 'curator'),
              _step('publish', 'kb', '校验与保存知识版本', 'publish'),
              _step('loop', 'kb', '决定是否继续', 'loop'),
              _step('evaluate', 'task', '独立新题效果验证', 'evaluate')]
    value = {
        'id': identifier, 'version': '1', 'name': name, 'description': description,
        'paper_url': 'https://arxiv.org/abs/2308.10144' if memory else None,
        'adaptation': ('固定 GLM，采用案例检索与经验规则修订；保留 ArchitectureIQ 的受控实验和知识验证。'
                       '这是 ExpeL 启发的改编方法，尚未声称复现论文效果。' if memory
                       else 'ArchitectureIQ 项目方法；知识仍须经过实验与证据校验。'),
        'status': 'available', 'learning_protocol': 'paired_progressive' if paired else 'single',
        'experience_mode': 'expel_inspired' if memory else 'off',
        'data_modes': ['pairs'] if paired else ['single'], 'steps': steps,
        'memory_policy': {'version': '1', 'retrieval': 'deterministic_public_features',
                          'scientific_status': 'unverified'} if memory else None,
        'publication_policy': 'existing_verified_kb_gate',
    }
    value['hash'] = canonical_hash(value)
    return value


def _basic_recipe() -> dict:
    value = {
        'id': 'basic_learning', 'version': '1', 'name': '单题学习',
        'description': '回答一道真实题目，对照已存反馈，保存未验证经验；手动选择是否同题再练。',
        'paper_url': None, 'adaptation': '同题重复练习；不代表独立评测、模型权重学习或科学验证。',
        'status': 'available', 'learning_protocol': 'single', 'experience_mode': 'basic_learning',
        'data_modes': ['single'],
        'steps': [_step('assemble', 'data', '读取一道题目', 'input'),
                  _step('solve', 'harness', '回答问题', 'solver'),
                  _step('commit', 'harness', '保存答案', 'commit'),
                  _step('feedback', 'harness', '对照真实反馈', 'reveal'),
                  _step('experience_consolidate', 'harness', '提炼经验', 'experience_curator'),
                  _step('experience_save', 'kb', '保存未验证经验', 'experience_save'),
                  _step('loop', 'kb', '决定是否同题再练', 'loop')],
        'memory_policy': {'version': '1', 'retrieval': 'same_question_practice',
                          'scientific_status': 'unverified'},
        'publication_policy': 'unverified_experience_only',
    }
    value['hash'] = canonical_hash(value)
    return value


_REGISTRY = {r['id']: r for r in [
    _basic_recipe(),
    _recipe('scientific', '受控科学研究', '独立作答、提出假说，经受控实验整理可验证知识。'),
    _recipe('paired_progressive', '渐进反事实学习', '从正常题归纳，再预测反事实并修订适用条件。', paired=True),
    _recipe('expel', 'ExpeL · 跨题经验学习', '检索既有案例，将多题反馈整理成可修订的经验规律。', memory=True),
    _recipe('paired_expel', 'ExpeL × 反事实学习', '用题对检验规律边界，并将修订累积到后续学习。', paired=True, memory=True),
]}


def list_methods() -> list[dict]:
    return copy.deepcopy(list(_REGISTRY.values()))


def resolve_method(settings: dict) -> dict | None:
    if 'method_id' not in settings:
        if 'method_version' in settings:
            raise ValueError('method_version requires method_id')
        return None  # Never silently recompile an old run under a new recipe.
    identifier = settings['method_id']
    if not isinstance(identifier, str) or identifier not in _REGISTRY:
        raise ValueError('Unknown method_id')
    recipe = _REGISTRY[identifier]
    if settings.get('method_version', recipe['version']) != recipe['version']:
        raise ValueError('Unsupported method_version')
    if 'learning_protocol' in settings and settings['learning_protocol'] != recipe['learning_protocol']:
        raise ValueError('learning_protocol contradicts selected method')
    return copy.deepcopy(recipe)
