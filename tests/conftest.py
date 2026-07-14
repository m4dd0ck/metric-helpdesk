from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from metric_helpdesk.tools import HelpDesk

METRICS_YAML = """
semantic_models:
  - name: orders
    table: orders
    primary_entity: order_id
    entities:
      - {name: order_id, type: primary}
    measures:
      - {name: order_amount, agg: sum, expr: amount}
      - {name: order_count, agg: count, expr: order_id}
    dimensions:
      - {name: order_date, type: time, time_granularity: day}
      - {name: country, type: categorical}
      - {name: order_status, type: categorical, expr: status}
  - name: sessions
    table: sessions
    primary_entity: session_id
    entities:
      - {name: session_id, type: primary}
    measures:
      - {name: session_count, agg: count, expr: session_id}
    dimensions:
      - {name: session_date, type: time, time_granularity: day}
metrics:
  - name: revenue
    type: simple
    type_params: {measure: order_amount}
    filter: "status = 'completed'"
  - name: completed_orders
    type: simple
    type_params: {measure: order_count}
    filter: "status = 'completed'"
  - name: average_order_value
    type: derived
    type_params: {expr: "revenue / completed_orders", metrics: [revenue, completed_orders]}
  - {name: total_sessions, type: simple, type_params: {measure: session_count}}
  - {name: running_revenue, type: cumulative, type_params: {measure: order_amount}}
  - name: orders_per_session
    type: ratio
    type_params: {numerator: completed_orders, denominator: total_sessions}
"""

COUNTRIES = ["US", "GB", "Côte d'Ivoire"]


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Two months of orders: every day, one completed order of 10.0 per country."""
    root = tmp_path_factory.mktemp("warehouse")
    metrics_dir = root / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "metrics.yaml").write_text(METRICS_YAML)
    db_path = root / "shop.duckdb"
    rows = []
    day, order_id = date(2024, 1, 1), 0
    while day <= date(2024, 2, 29):
        for country in COUNTRIES:
            order_id += 1
            rows.append((order_id, day, country, "completed", 10.0))
        day += timedelta(days=1)
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            "create table orders (order_id int, order_date date, country varchar,"
            " status varchar, amount decimal(10, 2))"
        )
        connection.executemany("insert into orders values (?, ?, ?, ?, ?)", rows)
        connection.execute(
            "create table sessions as select 1 as session_id, date '2024-01-01' as session_date"
        )
    return metrics_dir, db_path


@pytest.fixture
def helpdesk(warehouse: tuple[Path, Path]) -> HelpDesk:
    return HelpDesk.open(*warehouse)
