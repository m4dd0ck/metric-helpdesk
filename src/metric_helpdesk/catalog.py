"""Metric metadata from MetricForge definitions.

Every metric is tied to the semantic models it reads from. Metrics from different tables can
be queried together; MetricForge aggregates each table on its own and joins on the dimensions
every table declares, so those shared dimensions are the only ones such a query can use.
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
        self._models_by_metric: dict[str, list[str]] = {
            metric.name: self._models_of(metric) for metric in registry.metrics.values()
        }

    @classmethod
    def from_directory(cls, metrics_dir: Path) -> "MetricCatalog":
        """Load every MetricForge YAML file in a directory."""
        registry = MetricRegistry()
        registry.load_directory(metrics_dir)
        return cls(registry)

    def _models_of(self, metric: Metric) -> list[str]:
        """Model names a metric reads from, in first-seen order."""
        params = metric.type_params
        if metric.type in ("simple", "cumulative"):
            return [self.registry.get_model_for_measure(params.measure).name]
        if metric.type == "derived":
            referenced = params.metrics
        else:
            referenced = [params.numerator, params.denominator]
        names: list[str] = []
        for name in referenced:
            for model_name in self._models_of(self.registry.get_metric(name)):
                if model_name not in names:
                    names.append(model_name)
        return names

    @property
    def metric_names(self) -> list[str]:
        return sorted(self._models_by_metric)

    def metric(self, name: str) -> Metric:
        """Look up a metric or raise with suggestions."""
        if name not in self._models_by_metric:
            raise HelpDeskError(f"Unknown metric '{name}'.{suggest(name, self.metric_names)}")
        return self.registry.get_metric(name)

    def models_of(self, metric_names: list[str]) -> list[SemanticModel]:
        """Every model the metrics read from, in first-seen order."""
        names: list[str] = []
        for metric_name in metric_names:
            self.metric(metric_name)
            names += [n for n in self._models_by_metric[metric_name] if n not in names]
        return [self.registry.get_semantic_model(name) for name in names]

    def time_dimension(self, models: list[SemanticModel]) -> Dimension | None:
        """The time axis for a query over these models, or None if one of them has no time.

        The first model's time dimension names the axis; MetricForge buckets the other models
        by their own time dimension under that name.
        """
        firsts = [
            next((d for d in model.dimensions if d.type == DimensionType.TIME), None)
            for model in models
        ]
        if any(first is None for first in firsts):
            return None
        return firsts[0]

    def shared_dimensions(self, models: list[SemanticModel]) -> list[str]:
        """Categorical dimensions every model declares, in the first model's order."""
        names = [d.name for d in models[0].dimensions if d.type == DimensionType.CATEGORICAL]
        return [n for n in names if all(m.get_dimension(n) is not None for m in models)]

    def dimension(self, models: list[SemanticModel], name: str) -> Dimension:
        """A categorical dimension shared by the models, or raise with the valid names."""
        shared = self.shared_dimensions(models)
        if name not in shared:
            where = " and ".join(model.name for model in models)
            raise HelpDeskError(f"'{name}' is not a dimension of {where}.{suggest(name, shared)}")
        dimension = models[0].get_dimension(name)
        assert dimension is not None  # it is in shared, so the first model declares it
        return dimension

    def info(self, name: str) -> MetricInfo:
        metric = self.metric(name)
        models = self.models_of([name])
        time_dimension = self.time_dimension(models)
        return MetricInfo(
            name=metric.name,
            type=metric.type,
            description=metric.description,
            semantic_model=", ".join(model.name for model in models),
            dimensions=self.shared_dimensions(models),
            time_dimension=time_dimension.name if time_dimension else None,
        )
