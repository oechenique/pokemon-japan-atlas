"""shinkansen_edges (día 24): tramos entre estaciones consecutivas del Shinkansen.

- method = route: paradas consecutivas de cada relación de ruta (topología exacta).
- method = distance: para cada línea sin relación de ruta, el árbol de expansión mínima
  entre sus estaciones (distancia sobre la esfera). En una línea, eso conecta cada
  estación con sus vecinas; ordenar sobre las vías dobles y los ramales de OSM es más
  frágil.

Un tramo por par de estaciones (el sentido no importa). La geometría es la recta entre
las estaciones: el grafo es esquemático, las vías reales están en rail.
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity
from pipeline.transforms.gold.shinkansen_stations import DIRECTION

LICENSE = "ODbL-1.0"
EARTH_KM = 6371.0088


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    stations_path = gold_path("shinkansen_stations", root).as_posix()
    stops = gold_path("shinkansen_route_stop", root).as_posix()
    stations = {
        key: (name, method, lines, lat, lon)
        for key, name, method, lines, lat, lon in con.execute(
            f"SELECT station_key, name_ja, method, lines, ST_Y(geometry), ST_X(geometry) "
            f"FROM read_parquet('{stations_path}')"
        ).fetchall()
    }
    key_of = {name: key for key, (name, *_rest) in stations.items()}
    edges: dict[tuple[str, str], tuple[str, str]] = {}

    route_rows = con.execute(f"""
        SELECT trim(regexp_replace(route_name, '{DIRECTION}', '')) AS line, route_id,
               stop_order, name_ja
        FROM read_parquet('{stops}') WHERE name_ja IS NOT NULL ORDER BY route_id, stop_order
    """).fetchall()
    route_lines = set()
    previous: tuple[str, str] | None = None
    for line, route_id, _order, name in route_rows:
        route_lines.add(line)
        if previous and previous[0] == route_id and previous[1] != name:
            _add(edges, key_of.get(previous[1]), key_of.get(name), line, "route")
        previous = (route_id, name)

    by_line: dict[str, list[str]] = {}
    for key, (_name, method, lines, _lat, _lon) in stations.items():
        if method != "distance":
            continue
        for line in lines or ():
            if line not in route_lines:
                by_line.setdefault(line, []).append(key)
    for line, keys in sorted(by_line.items()):
        for a, b in minimum_spanning_tree(sorted(keys), lambda k: stations[k][3:5]):
            _add(edges, a, b, line, "distance")

    rows = [
        (f"{a}|{b}", a, b, line, method, *stations[a][3:5], *stations[b][3:5])
        for (a, b), (line, method) in sorted(edges.items())
    ]
    con.execute("""
        CREATE OR REPLACE TEMP TABLE edges (edge_id VARCHAR, from_key VARCHAR, to_key VARCHAR,
            line VARCHAR, method VARCHAR, lat1 DOUBLE, lon1 DOUBLE, lat2 DOUBLE, lon2 DOUBLE)
    """)
    if rows:
        con.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    query = f"""
        SELECT edge_id, from_key, to_key, line, method,
               ST_Distance_Sphere(ST_Point(lon1, lat1), ST_Point(lon2, lat2)) / 1000 AS distance_km,
               '{LICENSE}' AS license,
               ST_MakeLine(ST_Point(lon1, lat1), ST_Point(lon2, lat2)) AS geometry
        FROM edges
    """
    summary = write_entity(con, "shinkansen_edges", query, root=root, layer="gold")
    methods = {}
    for _line, method in edges.values():
        methods[method] = methods.get(method, 0) + 1
    return {**summary, "stats": {f"edges_by_{k}": v for k, v in sorted(methods.items())}}


def _add(edges: dict, a: str | None, b: str | None, line: str, method: str) -> None:
    if a is None or b is None or a == b:
        return
    pair = (min(a, b), max(a, b))
    edges.setdefault(pair, (line, method))


def minimum_spanning_tree(keys: list[str], position) -> list[tuple[str, str]]:
    """Kruskal sobre la distancia de gran círculo entre (lat, lon)."""

    def distance(a: str, b: str) -> float:
        (la1, lo1), (la2, lo2) = position(a), position(b)
        p1, p2 = math.radians(la1), math.radians(la2)
        dp, dl = p2 - p1, math.radians(lo2 - lo1)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * EARTH_KM * math.asin(math.sqrt(h))

    candidates = sorted((distance(a, b), a, b) for i, a in enumerate(keys) for b in keys[i + 1 :])
    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    tree = []
    for _d, a, b in candidates:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            tree.append((a, b))
    return tree
