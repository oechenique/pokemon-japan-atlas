"""power_plants_kanto (día 12): centrales de la región Kanto del juego, sin ruido.

Entran las nucleares, hidroeléctricas y térmicas (carbón, gas, petróleo; también las
combinadas, como "coal;gas;oil") y cualquier central de 10 MW o más, sea cual sea su
fuente. Las solares chicas, que son la gran mayoría, quedan fuera de la vista del día.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

SOURCES = ("nuclear", "hydro", "coal", "gas", "oil")
MIN_OUTPUT_MW = 10.0


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    poi = gold_path("poi", root).as_posix()
    pattern = "(^|;)\\s*(" + "|".join(SOURCES) + ")\\s*(;|$)"
    query = f"""
        WITH kanto AS (
            SELECT *,
                   coalesce(regexp_matches(lower(plant_source), '{pattern}'), false) AS by_source,
                   coalesce(plant_output_mw >= {MIN_OUTPUT_MW}, false) AS by_capacity
            FROM read_parquet('{poi}')
            WHERE category = 'power_plant' AND game_region = 'kanto'
        )
        SELECT poi_id, name_ja, name_en, plant_source, plant_output_mw,
               CASE WHEN by_source AND by_capacity THEN 'source+capacity'
                    WHEN by_source THEN 'source' ELSE 'capacity' END AS reason,
               prefecture_code, license, geometry
        FROM kanto WHERE by_source OR by_capacity
    """
    summary = write_entity(con, "power_plants_kanto", query, root=root, layer="gold")
    total = con.execute(
        f"SELECT count(*) FROM read_parquet('{poi}') "
        "WHERE category = 'power_plant' AND game_region = 'kanto'"
    ).fetchone()[0]
    return {**summary, "stats": {"kanto_power_plants": total, "kept": summary["rows"]}}
