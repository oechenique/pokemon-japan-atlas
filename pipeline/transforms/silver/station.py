"""station: estaciones de OSM (railway=station), deduplicadas por id de OSM.

`lines` sale del tag `line` (separado por ;) cuando existe; en OSM casi nunca está en
el nodo, así que queda NULL y se reporta como faltante, sin inventarlo.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms import osm
from pipeline.transforms.base import Bronze, write_entity

LICENSE = "ODbL-1.0"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    files = osm.overpass_files(bronze, "osm_overpass", ("station",))
    stats = osm.load_elements(con, "osm_station", files)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE station_points AS
        SELECT 'osm:' || osm_key AS station_id,
               coalesce({osm.tag("name:ja")}, {osm.tag("name")}) AS name_ja,
               {osm.tag("name:en")} AS name_en,
               {osm.tag("name:es")} AS name_es,
               {osm.tag("operator")} AS operator,
               CASE WHEN {osm.tag("line")} IS NOT NULL
                    THEN list_transform(string_split({osm.tag("line")}, ';'), x -> trim(x)) END
                   AS lines,
               {osm.point_sql()} AS geometry
        FROM osm_station
        WHERE osm_type = 'node'
    """)
    stats |= osm.assign_prefecture(con, "station_points", "station_id", root)
    query = f"""
        SELECT s.station_id, s.name_ja, s.name_en, s.name_es, s.operator, s.lines,
               p.prefecture_code,
               h3_latlng_to_cell_string(ST_Y(s.geometry), ST_X(s.geometry), 9) AS h3_r9,
               '{LICENSE}' AS license, s.geometry
        FROM station_points s
        LEFT JOIN station_points_pref p USING (station_id)
    """
    summary = write_entity(con, "station", query, root=root)
    return {**summary, "stats": stats}
