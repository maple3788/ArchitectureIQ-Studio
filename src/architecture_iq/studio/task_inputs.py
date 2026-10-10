"""Frozen research/Task set composition, with no split rewriting or side effects."""
from __future__ import annotations

import copy


def workflow_inputs(question_set: dict, task_question_set: dict | None = None,
                    *, phase: str | None = None) -> tuple[list[dict], dict]:
    """Compose native inputs only when evaluation is enabled.

    A separately selected Task set is never allowed to duplicate a research
    example, dataset, lineage, or DataFlip pair, even with matching splits.
    Existing bundles keep their existing held-out questions and split labels.
    """
    if phase not in (None, "development", "final"):
        raise ValueError("Unknown Task evaluation phase")
    public = copy.deepcopy(question_set["questions"])
    private = copy.deepcopy(question_set["feedback"])
    if task_question_set is None:
        return public, private
    task = copy.deepcopy(task_question_set["questions"])
    if not task:
        raise ValueError("Task question set must be nonempty")
    for name, rows in (("Data", public), ("Task", task)):
        ids = [q["id"] for q in rows]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate question ID in {name} set")
    for field in ("id", "dataset_id", "lineage_id", "pair_id"):
        left = {q.get(field) for q in public if q.get(field) is not None}
        right = {q.get(field) for q in task if q.get(field) is not None}
        if left & right:
            raise ValueError(f"Task and Data overlap on {field}; choose independent held-out questions")
    if phase is not None:
        if any(q.get("split", "discovery") != phase for q in task):
            raise ValueError(f"Task questions must already belong to {phase} split; splits are never rewritten")
        # The separate Task set replaces bundled evaluation inputs, while the
        # complete original Data set remains frozen in the job configuration.
        public = [q for q in public if q.get("split", "discovery") == "discovery"]
        private = {q["id"]: private[q["id"]] for q in public}
        public.extend(task)
        private.update(copy.deepcopy(task_question_set["feedback"]))
    return public, private


def task_summary(question_set: dict, task_question_set: dict | None, *, phase: str,
                 enabled: bool, research_limit: int | None = None) -> dict:
    """Public preflight metadata, with no feedback or held-out prompt preview."""
    selected = task_question_set or question_set
    splits = {split: sum(q.get("split", "discovery") == split for q in selected["questions"])
              for split in ("discovery", "development", "final")}
    count = len(selected["questions"]) if task_question_set else splits[phase]
    data = question_set["questions"]
    research_count = sum(q.get("split", "discovery") == "discovery" for q in data)
    if research_limit is not None and (type(research_limit) is not int or research_limit <= 0):
        raise ValueError("Research coverage limit must be a positive integer")
    effective_research = min(research_count, research_limit) if research_limit is not None else research_count
    extra_research = research_count - effective_research
    omitted = sum(q.get("split", "discovery") != "discovery" for q in data) if task_question_set and enabled else 0
    notice = (f"独立 Task 题集用于本次评测；Data 中 {omitted} 道旧评测题不参与，原题集仍完整冻结。"
              if task_question_set and enabled else
              "评测已关闭，保留 Task 选择但不执行。" if not enabled else
              "使用 Data 原题集内已有的独立评测分区；题目 split 不变。")
    if extra_research:
        notice += f" 研究轮次按冻结顺序覆盖前 {effective_research} 道 discovery 题，另 {extra_research} 道研究题不执行。"
    return {"configured": task_question_set is not None, "enabled": enabled, "phase": phase,
            "source": "separate" if task_question_set else "bundled",
            "question_set_id": selected.get("id"), "count": count,
            "executed_count": count if enabled else 0, "split_counts": splits,
            "effective_research_count": effective_research,
            "omitted_data_research_count": extra_research,
            "effective_evaluation_count": count if enabled else 0,
            "omitted_data_evaluation_count": omitted,
            "notice": notice}


def workflow_pairs(question_set: dict, task_question_set: dict | None = None,
                   *, phase: str | None = None) -> list[dict]:
    """Keep manifests for exactly the same sets as workflow_inputs, never infer pairs."""
    pairs = copy.deepcopy(question_set.get("pairs", []))
    if task_question_set is not None and phase is not None:
        pairs = [p for p in pairs if p.get("split") == "discovery"]
        pairs.extend(copy.deepcopy(task_question_set.get("pairs", [])))
    return pairs
