from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path
from typing import Any

from architecture_iq.profile import Profile


class DatasetFamily(ABC):
    name: str

    #: Which generated ``train.py`` template this family needs. The template
    #: decides what ``train_and_eval`` returns, so it has to agree with
    #: ``selection_metric_name()``; see ``candidates.generator._TRAIN_PY_BY_KIND``.
    train_loop_kind: str = "regression"

    #: Names of the optional keyword arguments ``create_instance`` accepts
    #: beyond ``profile`` and ``seed`` (CLI ``--input-dim`` / ``--rule-family``
    #: and friends). Generic code validates user options against this instead
    #: of hard-coding which family takes what.
    instance_option_names: tuple[str, ...] = ()

    def data_interventions(self) -> list[dict[str, Any]]:
        """Public factors with a controlled, family-owned intervention contract."""
        return []

    def validate_data_intervention(self, profile: Profile, factor: str, value: Any) -> None:
        raise ValueError(f"{self.name} does not support data intervention {factor!r}")

    def create_intervention_pair(
        self, profile: Profile, seed: int, *, factor: str,
        original_value: Any, counterfactual_value: Any, **options: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Sample once, changing only a declared parameter before materialization.

        Family validation must ensure both values preserve the synthesis
        contract, including any domain assumptions used by expression sampling.
        Private renderer inputs stay frozen alongside the public spec.
        """
        self.validate_data_intervention(profile, factor, original_value)
        self.validate_data_intervention(profile, factor, counterfactual_value)
        if original_value == counterfactual_value:
            raise ValueError("The intervention must change its declared factor")
        partial = self.create_instance(profile, seed, **options)
        conditions = []
        for value in (original_value, counterfactual_value):
            condition = deepcopy(partial)
            condition["params"][factor] = deepcopy(value)
            conditions.append({
                "dataset_spec": self.build_spec_with_id(condition),
                "synthesis_context": {key: item for key, item in condition.items() if key.startswith("_")},
            })
        return conditions[0], conditions[1]

    @abstractmethod
    def create_instance(
        self,
        profile: Profile,
        seed: int,
    ) -> dict[str, Any]:
        """Return dataset_spec dict (without dataset_id).

        ``seed`` is the single user-facing instance seed; each family derives
        any internal RNG streams from it.
        """

    @abstractmethod
    def materialize(self, spec: dict[str, Any], out_dir: Path) -> None:
        """Write synthesize.py, tensors, and dataset_spec.json to out_dir."""

    @abstractmethod
    def load_tensors(self, dataset_path: Path) -> tuple[Any, Any, Any, Any]:
        """Return train_x, train_y, test_x, test_y tensors."""

    @abstractmethod
    def selection_metric_name(self) -> str:
        ...

    @abstractmethod
    def default_significance(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def compatible_model_types(self) -> list[str]:
        ...
