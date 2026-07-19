"""Seeded demo warehouse: a year of e-commerce orders and sessions with one planted story.

In July 2024 card checkout in Germany broke for most of the month, so many German card orders
were cancelled. Seasonality is flat from June to July, so that outage is the only reason July
revenue drops. It gives "why did revenue dip in July?" a real answer to find.
"""

import csv
import random
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

YEAR_START = date(2024, 1, 1)
YEAR_END = date(2024, 12, 31)
ORDERS_PER_DAY = 40
SESSIONS_PER_ORDER = 6

COUNTRIES = {"US": 0.40, "DE": 0.20, "GB": 0.15, "FR": 0.13, "CA": 0.12}
PAYMENT_METHODS = {"card": 0.75, "paypal": 0.17, "bank_transfer": 0.08}
CATEGORIES = {"apparel": 0.35, "home": 0.25, "electronics": 0.20, "beauty": 0.20}
DEVICES = {"mobile": 0.58, "desktop": 0.36, "tablet": 0.06}
# Daily demand by month. July is scaled by 30/31 so June and July monthly volumes match and
# the outage is the only July effect.
SEASONALITY = {
    1: 0.92, 2: 0.94, 3: 0.98, 4: 1.00, 5: 1.02, 6: 1.04,
    7: 1.04 * 30 / 31, 8: 1.02, 9: 1.03, 10: 1.06, 11: 1.18, 12: 1.25,
}  # fmt: skip

# Reason: with this seed ordinary noise between countries stays small, so the outage reads as
# the one clear driver (July revenue about -8%, Germany more than all of it).
DEMO_SEED = 2

BASE_CANCEL_RATE = 0.05
PENDING_RATE = 0.03
OUTAGE_START = date(2024, 7, 2)
OUTAGE_END = date(2024, 7, 30)
OUTAGE_CANCEL_RATE = 0.65


def pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def order_status(rng: random.Random, day: date, country: str, payment_method: str) -> str:
    """Completed unless cancelled or pending; the outage raises German card cancellations."""
    in_outage = OUTAGE_START <= day <= OUTAGE_END and country == "DE" and payment_method == "card"
    cancel_rate = OUTAGE_CANCEL_RATE if in_outage else BASE_CANCEL_RATE
    roll = rng.random()
    if roll < cancel_rate:
        return "cancelled"
    if roll < cancel_rate + PENDING_RATE:
        return "pending"
    return "completed"


def generate_rows(seed: int) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Return (orders, sessions) rows for the demo year."""
    rng = random.Random(seed)
    orders: list[tuple[object, ...]] = []
    sessions: list[tuple[object, ...]] = []
    day = YEAR_START
    while day <= YEAR_END:
        daily_orders = round(ORDERS_PER_DAY * SEASONALITY[day.month] * rng.uniform(0.95, 1.05))
        for _ in range(daily_orders):
            country = pick(rng, COUNTRIES)
            payment_method = pick(rng, PAYMENT_METHODS)
            quantity = rng.choices([1, 2, 3, 4], weights=[0.6, 0.25, 0.1, 0.05])[0]
            amount = round(rng.lognormvariate(3.9, 0.3) * quantity, 2)
            orders.append(
                (
                    len(orders) + 1,
                    rng.randint(1, 4000),
                    rng.randint(1, 300),
                    amount,
                    quantity,
                    order_status(rng, day, country, payment_method),
                    country,
                    pick(rng, CATEGORIES),
                    payment_method,
                    day,
                )
            )
        for _ in range(daily_orders * SESSIONS_PER_ORDER):
            sessions.append(
                (
                    len(sessions) + 1,
                    rng.randint(1, 20000),
                    day,
                    rng.randint(1, 12),
                    pick(rng, COUNTRIES),
                    pick(rng, DEVICES),
                )
            )
        day += timedelta(days=1)
    return orders, sessions


def build_warehouse(db_path: Path, seed: int = DEMO_SEED) -> dict[str, int]:
    """Write the demo tables to ``db_path``, replacing any existing file.

    Returns:
        Row count per table.
    """
    orders, sessions = generate_rows(seed)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            """
            create table orders (
                order_id integer primary key, customer_id integer, product_id integer,
                amount decimal(10, 2), quantity integer, status varchar, country varchar,
                category varchar, payment_method varchar, order_date date
            )
            """
        )
        _bulk_insert(connection, "orders", orders)
        connection.execute(
            """
            create table sessions (
                session_id integer primary key, visitor_id integer, session_date date,
                page_views integer, country varchar, device varchar
            )
            """
        )
        _bulk_insert(connection, "sessions", sessions)
    return {"orders": len(orders), "sessions": len(sessions)}


@dataclass(frozen=True)
class DemoPaths:
    """Where the demo definitions and warehouse were written."""

    metrics_dir: Path
    db_path: Path


DEMO_METRICS = Path(__file__).parent / "demo_metrics"


def build_demo(out_dir: Path) -> DemoPaths:
    """Write the demo warehouse and a copy of its metric definitions under ``out_dir``."""
    paths = DemoPaths(metrics_dir=out_dir / "metrics", db_path=out_dir / "shop.duckdb")
    shutil.rmtree(paths.metrics_dir, ignore_errors=True)
    shutil.copytree(DEMO_METRICS, paths.metrics_dir)
    build_warehouse(paths.db_path)
    return paths


def _bulk_insert(
    connection: duckdb.DuckDBPyConnection, table: str, rows: list[tuple[object, ...]]
) -> None:
    # Reason: executemany takes minutes for ~100k rows; a CSV bulk load takes under a second.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{table}.csv"
        with path.open("w", newline="") as handle:
            csv.writer(handle).writerows(rows)
        connection.execute(
            f"insert into {table} select * from read_csv(?, header = false)", [str(path)]
        )
