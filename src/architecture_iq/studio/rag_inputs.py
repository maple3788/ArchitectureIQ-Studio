"""Public-only inference inputs, independent of evaluation feedback readiness."""
from __future__ import annotations

import copy
import math

from architecture_iq.kb.rules import CONTROL_FIELDS

PUBLIC_KEYS = {'id', 'family', 'dataset_id', 'lineage_id', 'prompt', 'split', 'pair_id', 'profile_hash'}


def validate_rag_question(public: dict) -> dict:
    if not isinstance(public, dict) or any(
        not isinstance(public.get(key), str) or not public[key].strip()
        for key in ('id', 'family', 'prompt')
    ):
        raise ValueError('RAG 需要完整的公开题干和题型')
    choices = public.get('choices')
    if not isinstance(choices, list) or len(choices) < 2:
        raise ValueError('RAG 至少需要两个候选方案')
    letters, ids = [], []
    for choice in choices:
        if not isinstance(choice, dict):
            raise ValueError('候选方案格式无效')
        letter, identifier, view = choice.get('letter'), choice.get('id'), choice.get('view')
        if (not isinstance(letter, str) or len(letter) != 1 or letter not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                or not isinstance(identifier, str) or not identifier or not isinstance(view, dict)):
            raise ValueError('候选方案缺少有效标识、字母或公开条件')
        if any(key not in CONTROL_FIELDS or value is not None and not isinstance(value, (str, int, float, bool))
               or isinstance(value, float) and not math.isfinite(value) for key, value in view.items()):
            raise ValueError('候选方案含非公开或无效条件')
        letters.append(letter)
        ids.append(identifier)
    if len(set(letters)) != len(letters) or len(set(ids)) != len(ids):
        raise ValueError('候选方案标识或字母重复')
    result = {key: value for key, value in public.items() if key in PUBLIC_KEYS and isinstance(value, str)}
    result['choices'] = [{key: choice[key] for key in ('id', 'letter', 'view')} for choice in choices]
    return copy.deepcopy(result)


def rag_ready(public: dict) -> bool:
    try:
        validate_rag_question(public)
        return True
    except (ValueError, TypeError):
        return False
