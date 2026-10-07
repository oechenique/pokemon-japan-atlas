"""null_findings (día 18): los huecos de las fuentes, desde el quality_report de la
corrida, más Null Island (el elemento ficticio de Natural Earth en 0°, 0°, que el mapa
base excluye)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from pipeline.quality.gate import REPORT_NAME, publish_root
from pipeline.transforms.base import RUNS_DIR, SILVER, create_table, data_root, write_entity

LICENSE = "LicenseRef-quality-report"
COLUMNS = ("finding_id", "title", "value", "total", "share", "source", "detail")


def load_report(run_id: str, publish: Path | None = None) -> dict:
    path = (publish or publish_root()) / run_id / REPORT_NAME
    return json.loads(path.read_text(encoding="utf-8"))


def build(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    *,
    root: Path | None = None,
    publish: Path | None = None,
) -> dict:
    report = load_report(run_id, publish)
    rows = [
        tuple(f[k] for k in ("id", "title", "value", "total", "share", "source", "detail"))
        for f in report["coverage"]
    ]
    lineage = json.loads(
        ((root or data_root()) / SILVER / RUNS_DIR / f"run_id={run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    basemap = next((e for e in lineage["entities"] if e["entity"] == "basemap"), {})
    excluded = basemap.get("stats", {}).get("null_island_excluded", 0)
    rows.append(
        (
            "natural_earth_null_island",
            "Null Island en Natural Earth",
            excluded,
            None,
            None,
            "natural_earth",
            "Elemento ficticio en 0°, 0° (featurecla = 'Null island') en las capas de costas y "
            "tierra; se excluye del mapa base.",
        )
    )
    create_table(con, "findings", COLUMNS, rows)
    query = f"""
        SELECT finding_id, title, value::BIGINT AS value, total::BIGINT AS total,
               share::DOUBLE AS share, source, detail, '{LICENSE}' AS license
        FROM findings
    """
    return write_entity(con, "null_findings", query, root=root, layer="gold")
