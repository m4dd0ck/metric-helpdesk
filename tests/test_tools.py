from datetime import date
from pathlib import Path

import pytest

from metric_helpdesk.models import ComparisonRequest, DimensionFilter, HelpDeskError, QueryRequest
from metric_helpdesk.tools import HelpDesk
from metric_helpdesk.warehouse import WarehouseError, open_store


class TestCatalog:
    def test_cumulative_and_cross_table_metrics_are_hidden(self, helpdesk: HelpDesk) -> None:
        names = {metric.name for metric in helpdesk.list_metrics().metrics}
        assert names == {"revenue", "completed_orders", "average_order_value", "total_sessions"}

    def test_unknown_metric_suggests_the_closest_name(self, helpdesk: HelpDesk) -> None:
        with pytest.raises(HelpDeskError, match="Did you mean revenue"):
            helpdesk.describe_metric("revenu")

    def test_describe_shows_definition_and_sql(self, helpdesk: HelpDesk) -> None:
        detail = helpdesk.describe_metric("average_order_value")
        assert detail.definition["type_params"]["metrics"] == ["revenue", "completed_orders"]
        assert "DATE_TRUNC" in detail.example_sql


class TestQuery:
    def test_monthly_totals(self, helpdesk: HelpDesk) -> None:
        result = helpdesk.query_metrics(QueryRequest(metrics=["revenue", "completed_orders"]))
        assert result.rows == [
            {"order_date": "2024-01-01", "revenue": 930.0, "completed_orders": 93},
            {"order_date": "2024-02-01", "revenue": 870.0, "completed_orders": 87},
        ]

    def test_date_range_is_inclusive(self, helpdesk: HelpDesk) -> None:
        request = QueryRequest(
            metrics=["completed_orders"],
            grain=None,
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 11),
        )
        assert helpdesk.query_metrics(request).rows == [{"completed_orders": 6}]

    def test_filter_value_with_a_quote_matches_exactly(self, helpdesk: HelpDesk) -> None:
        request = QueryRequest(
            metrics=["completed_orders"],
            grain=None,
            filters=[DimensionFilter(dimension="country", values=["Côte d'Ivoire"])],
        )
        assert helpdesk.query_metrics(request).rows == [{"completed_orders": 60}]

    def test_injection_attempt_is_treated_as_a_plain_value(self, helpdesk: HelpDesk) -> None:
        request = QueryRequest(
            metrics=["completed_orders"],
            grain=None,
            filters=[DimensionFilter(dimension="country", values=["x') OR 1=1 --"])],
        )
        assert helpdesk.query_metrics(request).rows == [{"completed_orders": 0}]

    def test_row_limit_sets_truncated(self, helpdesk: HelpDesk) -> None:
        request = QueryRequest(metrics=["revenue"], grain="day", limit=5)
        result = helpdesk.query_metrics(request)
        assert result.row_count == 5
        assert result.truncated

    def test_metrics_from_different_tables_are_refused(self, helpdesk: HelpDesk) -> None:
        with pytest.raises(HelpDeskError, match="different tables"):
            helpdesk.query_metrics(QueryRequest(metrics=["revenue", "total_sessions"]))

    def test_unknown_dimension_lists_valid_ones(self, helpdesk: HelpDesk) -> None:
        with pytest.raises(HelpDeskError, match="Valid: country, order_status"):
            helpdesk.query_metrics(QueryRequest(metrics=["revenue"], group_by=["region"]))

    def test_reversed_date_range_is_refused(self, helpdesk: HelpDesk) -> None:
        request = QueryRequest(
            metrics=["revenue"], start_date=date(2024, 2, 1), end_date=date(2024, 1, 1)
        )
        with pytest.raises(HelpDeskError, match="start_date"):
            helpdesk.query_metrics(request)


class TestWarehouse:
    def test_writes_are_rejected(self, helpdesk: HelpDesk) -> None:
        with pytest.raises(Exception, match="read-only|Cannot execute"):
            helpdesk.store.executor.conn.execute("delete from orders")

    def test_missing_file_raises(self, warehouse: tuple[Path, Path], tmp_path: Path) -> None:
        with pytest.raises(WarehouseError, match="not found"):
            open_store(warehouse[0], tmp_path / "missing.duckdb")


class TestComparePeriods:
    def request(self, metric: str) -> ComparisonRequest:
        return ComparisonRequest(
            metric=metric,
            dimension="country",
            period_a_start=date(2024, 1, 1),
            period_a_end=date(2024, 1, 31),
            period_b_start=date(2024, 2, 1),
            period_b_end=date(2024, 2, 29),
        )

    def test_additive_change_is_split_by_dimension(self, helpdesk: HelpDesk) -> None:
        result = helpdesk.compare_periods(self.request("revenue"))
        assert result.is_additive
        assert result.total_change == -60.0  # 29 days vs 31 days, three countries
        assert {row.value: row.change for row in result.rows} == {
            "US": -20.0,
            "GB": -20.0,
            "Côte d'Ivoire": -20.0,
        }
        assert sum(row.share_of_change or 0 for row in result.rows) == pytest.approx(1.0, abs=1e-3)

    def test_averages_get_no_share_of_change(self, helpdesk: HelpDesk) -> None:
        result = helpdesk.compare_periods(self.request("average_order_value"))
        assert not result.is_additive
        assert all(row.share_of_change is None for row in result.rows)
