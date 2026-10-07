"""shinkansen_line_station: estaciones del Shinkansen por línea (seed oficial + OSM).

El seed shinkansen_stations trae el listado oficial de cada línea (hecho, con fuente
por línea). Cada estación se cruza con los nodos de estación de OSM por nombre en
japonés:

- un solo nodo con ese nombre: match_method = unique;
- varios (por ejemplo, 福島 en Fukushima y en Osaka): en las líneas full, y en la
  primera estación de una mini, gana el más cercano a una vía del Shinkansen (track);
  en el resto de una mini, que corre por vías convencionales, el más cercano a la
  estación anterior de la línea ya elegida (sequence);
- ninguno: la fila queda sin station_id ni geometría y el DQ gate bloquea.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from pipeline.transforms.base import Bronze, create_table, silver_path, write_entity

LICENSE = "LicenseRef-seeds + ODbL-1.0"
SEED_COLUMNS = (
    "line_id",
    "line_name_ja",
    "kind",
    "operator",
    "seq",
    "station_name_ja",
    "source_url",
)


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    seed_path = Path(bronze.path("seeds", "shinkansen_stations.csv"))
    with seed_path.open(encoding="utf-8") as f:
        seed = [{k: row[k] for k in SEED_COLUMNS} for row in csv.DictReader(f)]
    station = silver_path("station", root).as_posix()
    rail = silver_path("rail", root).as_posix()
    names = sorted({row["station_name_ja"] for row in seed})
    candidates: dict[str, list[tuple[str, float, float, str | None, float | None]]] = {}
    for name, station_id, lon, lat, prefecture, track_m in con.execute(
        f"""
        WITH named AS (
            SELECT station_id, name_ja, prefecture_code, geometry FROM read_parquet('{station}')
            WHERE name_ja IN (SELECT unnest(?::VARCHAR[]))
        )
        SELECT n.name_ja, n.station_id, ST_X(n.geometry), ST_Y(n.geometry), n.prefecture_code,
               min(ST_Distance(n.geometry, r.geometry)) * 111000 AS track_m
        FROM named n
        LEFT JOIN read_parquet('{rail}') r
          ON r.kind = 'shinkansen' AND ST_DWithin(n.geometry, r.geometry, 0.02)
        GROUP BY ALL ORDER BY n.name_ja, n.station_id
    """,
        [names],
    ).fetchall():
        candidates.setdefault(name, []).append((station_id, lon, lat, prefecture, track_m))

    rows = []
    previous: dict[str, tuple[float, float]] = {}
    for row in sorted(seed, key=lambda r: (r["line_id"], int(r["seq"]))):
        found = candidates.get(row["station_name_ja"], [])
        chosen, method = choose(found, row["kind"], previous.get(row["line_id"]))
        if chosen is not None:
            previous[row["line_id"]] = (chosen[1], chosen[2])
        station_id, lon, lat, prefecture = chosen[:4] if chosen else (None, None, None, None)
        rows.append(
            (*(row[k] for k in SEED_COLUMNS), station_id, lon, lat, prefecture, len(found), method)
        )
    columns = (
        *SEED_COLUMNS,
        "station_id",
        "lon",
        "lat",
        "prefecture_code",
        "candidates",
        "match_method",
    )
    create_table(con, "line_stations", columns, rows)
    query = f"""
        SELECT line_id, line_name_ja, kind, operator, seq::INTEGER AS seq,
               station_name_ja AS name_ja, station_id, candidates::INTEGER AS candidates,
               match_method, prefecture_code, source_url, '{LICENSE}' AS license,
               CASE WHEN lon IS NOT NULL THEN ST_Point(lon::DOUBLE, lat::DOUBLE) END AS geometry
        FROM line_stations
    """
    summary = write_entity(con, "shinkansen_line_station", query, root=root)
    unmatched = sorted({r[5] for r in rows if r[7] is None})
    methods: dict[str, int] = {}
    for r in rows:
        methods[r[12] or "none"] = methods.get(r[12] or "none", 0) + 1
    return {
        **summary,
        "stats": {"unmatched": unmatched, **{f"by_{k}": v for k, v in methods.items()}},
    }


def choose(found, kind: str, previous: tuple[float, float] | None):
    """Elige el nodo de OSM de una estación del seed; devuelve (candidato, método)."""
    if not found:
        return None, None
    if len(found) == 1:
        return found[0], "unique"
    # La primera estación de una mini (Morioka, Fukushima) está sobre la vía del Tōhoku.
    if kind == "full" or previous is None:
        on_track = [c for c in found if c[4] is not None]
        if on_track:
            return min(on_track, key=lambda c: (c[4], c[0])), "track"
    if previous is not None:
        lon0, lat0 = previous
        return min(found, key=lambda c: ((c[1] - lon0) ** 2 + (c[2] - lat0) ** 2, c[0])), "sequence"
    return min(found, key=lambda c: c[0]), "sequence"
