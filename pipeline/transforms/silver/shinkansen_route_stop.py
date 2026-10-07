"""shinkansen_route_stop: paradas de las relaciones de ruta del Shinkansen en OSM.

Las relaciones vienen con out geom: cada miembro nodo trae sus coordenadas, pero no sus
tags. Las paradas son los miembros con rol stop (o stop_entry_only / stop_exit_only),
numeradas en el orden de la relación. El nombre sale de la estación de Silver más
cercana a menos de 300 m (station_id NULL si no hay ninguna).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms import osm
from pipeline.transforms.base import Bronze, silver_path, write_entity

LICENSE = "ODbL-1.0"
STOP_ROLES = ("stop", "stop_entry_only", "stop_exit_only")
STATION_RADIUS_DEG = 0.003  # ~300 m
# "東北新幹線（上り）" -> "東北新幹線"
DIRECTION = r"[（(].*[）)]\s*$"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    files = osm.overpass_files(bronze, "osm_overpass", ("shinkansen_routes",))
    stats = osm.load_elements(con, "osm_routes", files)
    roles = ", ".join(f"'{r}'" for r in STOP_ROLES)
    station = silver_path("station", root).as_posix()
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE route_stops AS
        WITH members AS (
            SELECT 'osm:' || osm_key AS route_id,
                   coalesce({osm.tag("name:ja")}, {osm.tag("name")}) AS route_name,
                   unnest(CAST(e -> 'members' AS JSON[])) AS m,
                   generate_subscripts(CAST(e -> 'members' AS JSON[]), 1) AS position
            FROM osm_routes WHERE osm_type = 'relation'
        )
        SELECT route_id, route_name,
               row_number() OVER (PARTITION BY route_id ORDER BY position)::INTEGER AS stop_order,
               'osm:node/' || (m ->> 'ref') AS stop_node,
               ST_SetCRS(ST_Point((m ->> 'lon')::DOUBLE, (m ->> 'lat')::DOUBLE), 'OGC:CRS84')
                   AS geometry
        FROM members
        WHERE (m ->> 'type') = 'node' AND (m ->> 'role') IN ({roles})
          AND (m ->> 'lat') IS NOT NULL
    """)
    query = f"""
        WITH nearest AS (
            SELECT r.route_id, r.stop_order,
                   arg_min(s.station_id, ST_Distance(r.geometry, s.geometry)) AS station_id,
                   arg_min(s.name_ja, ST_Distance(r.geometry, s.geometry)) AS name_ja
            FROM route_stops r
            JOIN read_parquet('{station}') s
              ON ST_DWithin(r.geometry, s.geometry, {STATION_RADIUS_DEG})
            GROUP BY r.route_id, r.stop_order
        )
        SELECT r.route_id, r.route_name, r.stop_order, r.stop_node, n.station_id, n.name_ja,
               '{LICENSE}' AS license, r.geometry
        FROM route_stops r LEFT JOIN nearest n USING (route_id, stop_order)
    """
    summary = write_entity(con, "shinkansen_route_stop", query, root=root)
    routes = con.execute("SELECT count(DISTINCT route_id) FROM route_stops").fetchone()[0]
    return {**summary, "stats": {**stats, "routes_with_stops": routes}}
