"""Humo del entorno: confirma que DuckDB carga spatial y h3 y que data/ y publish/
están montados con escritura. No produce artefactos."""

from __future__ import annotations

import os
from pathlib import Path

import pendulum
from airflow.sdk import dag, task


@dag(
    dag_id="atlas_smoke",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["fase-0", "entorno"],
)
def atlas_smoke():
    @task
    def duckdb_extensions() -> str:
        import duckdb

        con = duckdb.connect()
        con.load_extension("spatial")
        con.load_extension("h3")
        cell = con.sql(
            "SELECT h3_latlng_to_cell_string(35.6586, 139.7454, 9)"
            " FROM (SELECT ST_Point(139.7454, 35.6586))"
        ).fetchone()[0]
        return cell

    @task
    def mounts_writable() -> None:
        for var in ("ATLAS_DATA_DIR", "ATLAS_PUBLISH_DIR"):
            root = Path(os.environ[var])
            probe = root / ".write-probe"
            probe.write_text("ok")
            probe.unlink()

    duckdb_extensions() >> mounts_writable()


atlas_smoke()
