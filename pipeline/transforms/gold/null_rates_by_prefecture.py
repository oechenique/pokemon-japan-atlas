"""null_rates_by_prefecture (día 18): tasas de nulos por prefectura, desde
informative.null_rates del quality_report de la corrida."""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import create_table, write_entity
from pipeline.transforms.gold.null_findings import LICENSE, load_report

COLUMNS = ("entity", "column_name", "prefecture_code", "row_count", "null_count", "rate")


def build(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    *,
    root: Path | None = None,
    publish: Path | None = None,
) -> dict:
    report = load_report(run_id, publish)
    rows = []
    for entity, columns in sorted(report["informative"]["null_rates"].items()):
        for column, entry in sorted(columns.items()):
            for prefecture, group in sorted(entry.get("by", {}).items()):
                rows.append(
                    (entity, column, prefecture, group["rows"], group["nulls"], group["rate"])
                )
    create_table(con, "rates", COLUMNS, rows)
    query = f"""
        SELECT entity, column_name, prefecture_code, row_count::BIGINT AS row_count,
               null_count::BIGINT AS null_count, rate::DOUBLE AS rate, '{LICENSE}' AS license
        FROM rates
    """
    return write_entity(con, "null_rates_by_prefecture", query, root=root, layer="gold")
