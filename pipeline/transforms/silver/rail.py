"""rail: vías de OSM, el Shinkansen de todo Japón y la red completa de Kanto.

Deduplicadas por id de OSM. Una vía del Shinkansen también aparece en la red de
Kanto: gana shinkansen. Geometría desde out geom; length_m sobre el elipsoide.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms import osm
from pipeline.transforms.base import Bronze, write_entity

PRECEDENCE = ("shinkansen", "rail_kanto")
LICENSE = "ODbL-1.0"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    files = osm.overpass_files(bronze, "osm_overpass", PRECEDENCE)
    stats = osm.load_elements(con, "osm_rail", files, PRECEDENCE)
    stats["rail_without_geometry"] = con.execute(
        "SELECT count(*) FROM osm_rail WHERE (e -> 'geometry') IS NULL "
        "OR json_array_length(e -> 'geometry') < 2"
    ).fetchone()[0]
    query = f"""
        WITH lines AS (
            SELECT 'osm:' || osm_key AS rail_id,
                   CASE category WHEN 'shinkansen' THEN 'shinkansen' ELSE 'line' END AS kind,
                   coalesce({osm.tag("name:ja")}, {osm.tag("name")}) AS name_ja,
                   {osm.tag("name:en")} AS name_en,
                   {osm.tag("name:es")} AS name_es,
                   {osm.tag("operator")} AS operator,
                   {osm.line_sql("e -> 'geometry'")} AS geometry
            FROM osm_rail
            WHERE osm_type = 'way' AND json_array_length(e -> 'geometry') >= 2
        )
        SELECT rail_id, kind, name_ja, name_en, name_es, operator,
               ST_Length_Spheroid(ST_FlipCoordinates(geometry)) AS length_m,
               '{LICENSE}' AS license, geometry
        FROM lines
    """
    summary = write_entity(con, "rail", query, root=root)
    return {**summary, "stats": stats}
