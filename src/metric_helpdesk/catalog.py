"""Metric metadata from MetricForge definitions.

MetricForge compiles single-table queries, so every metric is tied to one semantic model here.
Metrics that cannot be answered correctly (cumulative ones, whose SQL is not time-aware yet, and
any whose inputs span tables) are left out of the catalog rather than returned wrong.
"""

import difflib
from pathlib import Path

from metricforge.models.metric import Metric
from metricforge.models.semantic_model import Dimension, DimensionType, SemanticModel
from metricforge.parser.loader import MetricRegistry

from metric_helpdesk.models import HelpDeskError, MetricInfo


def suggest(name: str, choices: list[str]) -> str:
    """Error text naming the closest valid choices."""
    close = difflib.get_close_matches(name, choices, n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    return f"{hint} Valid: {', '.join(sorted(choices))}."


class MetricCatalog:
    """Queryable metrics and the dimensions each one can be grouped or filtered by."""

    def __init__(self, registry: MetricRegistry) -> None:
        self.registry = registry
        self._model_by_metric: dict[str, str] = {}
        for metric in registry.metrics.values():
            models = self._models_of(metric)
            if metric.type != "cumulative" and len(models) == 1:
                self._model_by_metric[metric.name] = models.pop()

    @classmethod
    def from_directory(cls, metrics_dir: Path) -> "MetricCatalog":
        """Load every MetricForge YAML file in a directory."""
        registry = MetricRegistry()
        registry.load_directory(metrics_dir)
        return cls(registry)

    def _models_of(self, metric: Metric) -> set[str]:
        params = metric.type_params
        if metric.type in ("simple", "cumulative"):
            return {self.registry.get_model_for_measure(params.measure).name}
        if metric.type == "derived":
            referenced = params.metrics
        else:
            referenced = [params.numerator, params.denominator]
        models: set[str] = set()
        for name in referenced:
            models |= self._models_of(self.registry.get_metric(name))
        return models

    @property
    def metric_names(self) -> list[str]:
        return sorted(self._model_by_metric)

    def metric(self, name: str) -> Metric:
        """Look up a queryable metric or raise with suggestions."""
        if name not in self._model_by_metric:
            raise HelpDeskError(f"Unknown metric '{name}'.{suggest(name, self.metric_names)}")
        return self.registry.get_metric(name)

    def model_of(self, metric_name: str) -> SemanticModel:
        self.metric(metric_name)
        return self.registry.get_semantic_model(self._model_by_metric[metric_name])

    def time_dimension(self, model: SemanticModel) -> Dimension | None:
        return next((d for d in model.dimensions if d.type == DimensionType.TIME), None)

    def dimension(self, model: SemanticModel, name: str) -> Dimension:
        """A categorical dimension of the model, or raise with the valid names."""
        categorical = [d.name for d in model.dimensions if d.type == DimensionType.CATEGORICAL]
        if name not in categorical:
            raise HelpDeskError(
                f"'{name}' is not a dimension of {model.name}.{suggest(name, categorical)}"
            )
        return model.get_dimension(name)

    def info(self, name: str) -> MetricInfo:
        metric = self.metric(name)
        model = self.model_of(name)
        time_dimension = self.time_dimension(model)
        return MetricInfo(
            name=metric.name,
            type=metric.type,
            description=metric.description,
            semantic_model=model.name,
            dimensions=[d.name for d in model.dimensions if d.type == DimensionType.CATEGORICAL],
            time_dimension=time_dimension.name if time_dimension else None,
        )
