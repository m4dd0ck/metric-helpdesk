"""The help-desk tools. Plain Python with no AI dependency, shared by the MCP server and ask loop.

The model never supplies SQL. It names metrics and dimensions, which are checked against the
catalog, and filter values, which are escaped into literals. Dates arrive as parsed ``date``
objects. Everything else in the SQL comes from MetricForge definitions.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from metricforge import MetricStore
from metricforge.models.semantic_model import SemanticModel

from metric_helpdesk.catalog import MetricCatalog
from metric_helpdesk.models import (
    DimensionFilter,
    HelpDeskError,
    MetricDetail,
    MetricList,
    QueryRequest,
    QueryResult,
)
from metric_helpdesk.warehouse import open_store


def sql_literal(value: str) -> str:
    """Single-quoted SQL string literal with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def to_json_value(value: Any) -> Any:
    """Make DuckDB result values JSON-friendly."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class HelpDesk:
    """Answers metric questions through MetricForge only."""

    def __init__(self, catalog: MetricCatalog, store: MetricStore) -> None:
        self.catalog = catalog
        self.store = store

    @classmethod
    def open(cls, metrics_dir: Path, db_path: Path) -> "HelpDesk":
        """Load definitions and attach the warehouse read-only."""
        return cls(MetricCatalog.from_directory(metrics_dir), open_store(metrics_dir, db_path))

    def list_metrics(self) -> MetricList:
        """Every queryable metric with its dimensions."""
        return MetricList(metrics=[self.catalog.info(name) for name in self.catalog.metric_names])

    def describe_metric(self, name: str) -> MetricDetail:
        """A metric's definition and the SQL a monthly query of it compiles to."""
        info = self.catalog.info(name)
        metric = self.catalog.metric(name)
        definition: dict[str, Any] = {"type_params": metric.type_params.model_dump()}
        if metric.filter:
            definition["filter"] = metric.filter
        dimensions = [info.time_dimension] if info.time_dimension else []
        sql = self.store.get_sql(metrics=[name], dimensions=dimensions, time_grain="month")
        return MetricDetail(**info.model_dump(), definition=definition, example_sql=sql)

    def query_metrics(self, request: QueryRequest) -> QueryResult:
        """Compute metrics, optionally by time grain and dimensions, within a date range."""
        model = self._single_model(request.metrics)
        time_dimension = self.catalog.time_dimension(model)
        if (request.grain or request.start_date or request.end_date) and time_dimension is None:
            raise HelpDeskError(f"{model.name} has no time dimension; drop grain and dates.")
        if request.start_date and request.end_date and request.start_date > request.end_date:
            raise HelpDeskError("start_date must be on or before end_date.")

        group_by = [self.catalog.dimension(model, name).name for name in request.group_by]
        dimensions = group_by
        if request.grain and time_dimension:
            dimensions = [time_dimension.name, *group_by]

        conditions = [self._filter_condition(model, f) for f in request.filters]
        if time_dimension:
            time_expr = time_dimension.expr or time_dimension.name
            if request.start_date:
                conditions.append(f"{time_expr} >= DATE '{request.start_date.isoformat()}'")
            if request.end_date:
                conditions.append(f"{time_expr} <= DATE '{request.end_date.isoformat()}'")

        result = self.store.query(
            metrics=request.metrics,
            dimensions=dimensions,
            filters=conditions,
            time_grain=request.grain,
            limit=request.limit + 1,  # one extra row tells us whether the result was cut off
        )
        rows = [{k: to_json_value(v) for k, v in row.items()} for row in result.data]
        return QueryResult(
            columns=result.columns,
            rows=rows[: request.limit],
            row_count=min(len(rows), request.limit),
            truncated=len(rows) > request.limit,
            sql=result.sql,
        )

    def _single_model(self, metric_names: list[str]) -> SemanticModel:
        models = {name: self.catalog.model_of(name) for name in metric_names}
        names = {model.name for model in models.values()}
        if len(names) > 1:
            by_model = ", ".join(f"{m} ({models[m].name})" for m in metric_names)
            raise HelpDeskError(
                f"Metrics come from different tables: {by_model}. Query each table separately."
            )
        return next(iter(models.values()))

    def _filter_condition(self, model: SemanticModel, dimension_filter: DimensionFilter) -> str:
        dimension = self.catalog.dimension(model, dimension_filter.dimension)
        expr = dimension.expr or dimension.name
        literals = ", ".join(sql_literal(value) for value in dimension_filter.values)
        return f"{expr} IN ({literals})"
