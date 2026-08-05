"""Inputs and outputs of the help-desk tools, shared by the MCP server, the API loop and tests."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

TimeGrain = Literal["day", "week", "month", "quarter", "year"]


class HelpDeskError(ValueError):
    """A request the tools refuse, with a message the model can act on."""


class MetricInfo(BaseModel):
    """What a metric is and how it can be sliced."""

    name: str
    type: str
    description: str | None = None
    semantic_model: str
    dimensions: list[str]
    time_dimension: str | None = None


class MetricList(BaseModel):
    """Every queryable metric."""

    metrics: list[MetricInfo]


class MetricDetail(MetricInfo):
    """A metric's full definition and the SQL a monthly query compiles to."""

    definition: dict[str, Any]
    example_sql: str


class DimensionFilter(BaseModel):
    """Keep rows whose dimension equals one of the values."""

    dimension: str = Field(description="Dimension name from list_metrics")
    values: list[str] = Field(min_length=1, max_length=50)


class QueryRequest(BaseModel):
    """Metrics to compute, optionally by time grain and dimensions, within a date range."""

    metrics: list[str] = Field(min_length=1, max_length=8, description="Metric names")
    group_by: list[str] = Field(default_factory=list, description="Dimension names")
    grain: TimeGrain | None = Field(
        default="month", description="Time grain; null for no time split"
    )
    start_date: date | None = None
    end_date: date | None = None
    filters: list[DimensionFilter] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1, le=500)


class QueryResult(BaseModel):
    """Rows returned by a metric query, plus the SQL that produced them."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    sql: str


class ComparisonRequest(BaseModel):
    """Compare one metric across two date ranges, broken down by a dimension."""

    metric: str
    dimension: str = Field(description="Dimension to break the change down by")
    period_a_start: date
    period_a_end: date
    period_b_start: date
    period_b_end: date
    filters: list[DimensionFilter] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    """One dimension value's contribution to the change."""

    value: str | None
    period_a: float | None
    period_b: float | None
    change: float | None
    share_of_change: float | None = Field(
        description="Fraction of the total change; only for additive metrics (sums and counts)"
    )


class PeriodComparison(BaseModel):
    """How a metric moved between two periods and which dimension values drove it."""

    metric: str
    dimension: str
    is_additive: bool
    total_a: float | None
    total_b: float | None
    total_change: float | None
    rows: list[ComparisonRow] = Field(description="Largest absolute changes first, at most 25")
