"""shinkansen_stations (día 24): estaciones del Shinkansen, una por nombre.

1. method = route: las paradas de las relaciones de ruta de OSM (shinkansen_route_stop)
   que se pudieron unir a una estación. Es topología exacta, pero al 2026-10-07 solo
   existe para el Tōhoku.
2. method = distance: para las demás, las estaciones a 10 m o menos de una vía del
   Shinkansen, sin operadores ajenos a JR (el New Shuttle corre pegado al Tōhoku). El
   radio es chico a propósito: las estaciones convencionales pegadas al viaducto, como
   Yūrakuchō o Kanda, están a 29-40 m; las del Shinkansen, casi siempre sobre la vía.
   Límite conocido del radio (2026-10-07): se pierde Niigata (su nodo queda a 25 m de
   las vías de andén) y se cuelan algunas convencionales a ~11 m del viaducto, como
   Kanmaki o Nonoichi. Una regla de cabeceras por topes de vía sumaba estaciones al lado
   de los depósitos, así que se descartó.

lines: las líneas de cada estación. En las de ruta, el nombre de la ruta sin el
sentido; en las demás, los nombres de las vías del Shinkansen a 300 m o menos (las vías
de andén pegadas a la estación suelen no tener nombre).

Los mini-Shinkansen (Akita, Yamagata) corren por vías convencionales sin highspeed=yes
en OSM, así que no entran: es un límite de la fuente.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

TRACK_DEG = 0.0001  # ~10 m
LINE_NAME_DEG = 0.003  # ~300 m para nombrar la línea
LICENSE = "ODbL-1.0"
# Operadores de JR como aparecen en OSM; NULL también vale (la mayoría no lo tiene).
JR_OPERATOR = "(旅客鉄道|^JR)"
# "東北新幹線（上り）" -> "東北新幹線"
DIRECTION = "[（(].*[）)]\\s*$"


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    stops = gold_path("shinkansen_route_stop", root).as_posix()
    station = gold_path("station", root).as_posix()
    rail = gold_path("rail", root).as_posix()
    query = f"""
        WITH from_routes AS (
            SELECT r.name_ja,
                   min(r.station_id) AS station_id,
                   list(DISTINCT trim(regexp_replace(r.route_name, '{DIRECTION}', '')))
                       AS lines
            FROM read_parquet('{stops}') r
            WHERE r.name_ja IS NOT NULL
            GROUP BY r.name_ja
        ),
        shinkansen AS (
            SELECT name_ja, geometry FROM read_parquet('{rail}') WHERE kind = 'shinkansen'
        ),
        jr_stations AS (
            SELECT station_id, name_ja, geometry FROM read_parquet('{station}')
            WHERE name_ja IS NOT NULL
              AND (operator IS NULL OR regexp_matches(operator, '{JR_OPERATOR}'))
        ),
        near_track AS (
            SELECT s.station_id, s.name_ja, min(ST_Distance(s.geometry, k.geometry)) AS d
            FROM jr_stations s JOIN shinkansen k ON ST_DWithin(s.geometry, k.geometry, {TRACK_DEG})
            GROUP BY s.station_id, s.name_ja
        ),
        chosen AS (
            SELECT name_ja, arg_min(station_id, d) AS station_id FROM near_track
            WHERE name_ja NOT IN (SELECT name_ja FROM from_routes)
            GROUP BY name_ja
        ),
        from_distance AS (
            SELECT c.name_ja, c.station_id,
                   list(DISTINCT k.name_ja) FILTER (WHERE k.name_ja IS NOT NULL) AS lines
            FROM chosen c
            JOIN jr_stations s USING (station_id)
            LEFT JOIN shinkansen k ON ST_DWithin(s.geometry, k.geometry, {LINE_NAME_DEG})
            GROUP BY c.name_ja, c.station_id
        ),
        stations AS (
            SELECT name_ja, station_id, lines, 'route' AS method FROM from_routes
            UNION ALL
            SELECT name_ja, station_id, lines, 'distance' AS method FROM from_distance
        )
        SELECT 'shinkansen:' || st.name_ja AS station_key, st.station_id, st.name_ja,
               st.method, list_sort(coalesce(st.lines, [])) AS lines, s.prefecture_code,
               '{LICENSE}' AS license, s.geometry
        FROM stations st JOIN read_parquet('{station}') s USING (station_id)
    """
    summary = write_entity(con, "shinkansen_stations", query, root=root, layer="gold")
    written = gold_path("shinkansen_stations", root).as_posix()
    by_method = dict(
        con.execute(f"SELECT method, count(*) FROM read_parquet('{written}') GROUP BY 1").fetchall()
    )
    return {**summary, "stats": {f"stations_by_{k}": v for k, v in sorted(by_method.items())}}
