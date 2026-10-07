"""poi_clusters (día 4): clusters de Poké Lids y, como capa secundaria, de tiendas,
centros y cafés Pokémon.

DuckDB no tiene DBSCAN: un cluster es un componente conexo de celdas H3 de resolución 7
ocupadas, donde dos celdas están conectadas si están a 2 anillos o menos (~3 km). Las
Poké Lids se instalan en series por municipio, así que dan clusters reales en todo
Japón. Solo se guardan los clusters de 2 o más puntos; cluster_id es la capa y la
celda más chica del cluster (estable entre corridas).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

LAYERS = {
    "poke_lids": ("poke_lids",),
    "pokemon_retail": ("pokemon_center", "pokemon_store", "pokemon_cafe"),
}
RING = 2
MARGIN_DEG = 0.002  # ~200 m alrededor de la envolvente
LICENSE = "ODbL-1.0"


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    poi = gold_path("poi", root).as_posix()
    rows = []
    stats = {}
    for layer, categories in LAYERS.items():
        cats = ", ".join(f"'{c}'" for c in categories)
        points = con.execute(
            f"SELECT poi_id, h3_r7, prefecture_code FROM read_parquet('{poi}') "
            f"WHERE category IN ({cats}) ORDER BY poi_id"
        ).fetchall()
        cells = sorted({cell for _, cell, _ in points})
        neighbors = (
            dict(
                con.execute(
                    f"SELECT c, h3_grid_disk(c, {RING}) FROM (SELECT unnest(?::VARCHAR[]) AS c)",
                    [cells],
                ).fetchall()
            )
            if cells
            else {}
        )
        component = connected_components(cells, neighbors)
        groups: dict[str, list[tuple[str, str | None]]] = {}
        for poi_id, cell, prefecture in points:
            groups.setdefault(component[cell], []).append((poi_id, prefecture))
        kept = {root_cell: members for root_cell, members in groups.items() if len(members) >= 2}
        stats[f"{layer}_points"] = len(points)
        stats[f"{layer}_clusters"] = len(kept)
        stats[f"{layer}_isolated_points"] = sum(len(m) for m in groups.values() if len(m) < 2)
        for root_cell, members in kept.items():
            rows.append(
                (
                    f"{layer}:{root_cell}",
                    layer,
                    len(members),
                    sorted(p for p, _ in members),
                    sorted({pref for _, pref in members if pref}),
                )
            )
    con.execute("""
        CREATE OR REPLACE TEMP TABLE clusters (
            cluster_id VARCHAR, layer VARCHAR, member_count INTEGER,
            members VARCHAR[], prefecture_codes VARCHAR[])
    """)
    if rows:
        con.executemany("INSERT INTO clusters VALUES (?, ?, ?, ?, ?)", rows)
    query = f"""
        SELECT c.cluster_id, c.layer, c.member_count, c.members, c.prefecture_codes,
               '{LICENSE}' AS license,
               ST_Buffer(ST_ConvexHull(ST_Collect(list(p.geometry))), {MARGIN_DEG}) AS geometry
        FROM clusters c
        JOIN read_parquet('{poi}') p ON list_contains(c.members, p.poi_id)
        GROUP BY ALL
    """
    summary = write_entity(con, "poi_clusters", query, root=root, layer="gold")
    return {**summary, "stats": stats}


def connected_components(cells: list[str], neighbors: dict[str, list[str]]) -> dict[str, str]:
    """Union-find: cada celda ocupada -> la celda más chica de su componente."""
    parent = {c: c for c in cells}

    def find(c: str) -> str:
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    occupied = set(cells)
    for cell in cells:
        for other in neighbors.get(cell, ()):
            if other in occupied:
                a, b = find(cell), find(other)
                if a != b:
                    parent[max(a, b)] = min(a, b)
    return {c: find(c) for c in cells}
