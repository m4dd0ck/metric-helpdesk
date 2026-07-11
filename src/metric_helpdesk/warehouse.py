"""Open a MetricForge store over a warehouse file that queries cannot modify."""

import re
from pathlib import Path

from metricforge import MetricStore

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WarehouseError(ValueError):
    """Raised when the warehouse file cannot be attached safely."""


def open_store(metrics_dir: Path, db_path: Path) -> MetricStore:
    """Return a MetricStore whose tables resolve to ``db_path`` attached READ_ONLY.

    MetricForge itself opens files read-write, so the store gets an in-memory database and the
    warehouse is attached into it read-only. The alias is the file stem because DuckDB views
    (e.g. ones built by dbt-duckdb) reference their catalog by that name.

    Args:
        metrics_dir: MetricForge YAML definitions.
        db_path: DuckDB warehouse file.

    Raises:
        WarehouseError: If the file is missing or its stem is not a plain identifier.
    """
    if not db_path.is_file():
        raise WarehouseError(f"Warehouse not found: {db_path}")
    alias = db_path.stem
    if not _IDENTIFIER.match(alias):
        raise WarehouseError(f"Warehouse file name must be a plain identifier, got {alias!r}")

    store = MetricStore(metrics_dir, None)
    # Reason: ATTACH does not accept a bound parameter for the path, so escape the literal.
    path_literal = str(db_path.resolve()).replace("'", "''")
    store.executor.conn.execute(f"ATTACH '{path_literal}' AS {alias} (READ_ONLY)")
    store.executor.conn.execute(f"USE {alias}")
    return store
