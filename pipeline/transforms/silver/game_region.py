"""game_region: las 4 regiones del juego en Japón, como unión de sus prefecturas.

- Prefecturas, generación y año del seed game_regions; geometría de Silver prefecture.
- confidence de la región: la más baja entre sus filas (Johto mezcla Kansai oficial con
  Tōkai ampliamente aceptada, así que queda ampliamente aceptada).
- Nombres ja/en/es de Wikidata, por la etiqueta en inglés (Kanto → kanto).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import Bronze, create_table, silver_path, sparql_rows, write_entity

WIKIDATA_COLUMNS = ("region", "name_ja", "name_en", "name_es")
LICENSE = "LicenseRef-seeds + public-domain + CC0-1.0"
CONFIDENCE_RANK = "(VALUES ('oficial', 3), ('ampliamente aceptada', 2), ('teoría de fans', 1))"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    seed = bronze.path("seeds", "game_regions.csv")
    rows = sparql_rows(bronze.json("wikidata", "game_regions.json"), WIKIDATA_COLUMNS)
    create_table(con, "wd_game_region", WIKIDATA_COLUMNS, rows)
    prefecture = silver_path("prefecture", root).as_posix()
    query = f"""
        WITH seed AS (SELECT * FROM read_csv('{seed}', all_varchar = true)),
        rank AS (SELECT * FROM {CONFIDENCE_RANK} AS t(confidence, r)),
        agg AS (
            SELECT s.region_id,
                   min(s.game_name) AS game_name,
                   min(s.generation) AS generation,
                   min(s.year) AS year,
                   string_agg(DISTINCT s.real_region, ' + ' ORDER BY s.real_region) AS real_region,
                   min(rank.r) AS min_rank,
                   list(DISTINCT s.prefecture_code ORDER BY s.prefecture_code) AS prefecture_codes,
                   list(DISTINCT s.source_url ORDER BY s.source_url) AS source_urls,
                   ST_Union_Agg(p.geometry) AS geometry
            FROM seed s
            JOIN rank USING (confidence)
            JOIN read_parquet('{prefecture}') p USING (prefecture_code)
            GROUP BY s.region_id
        )
        SELECT a.region_id, a.game_name, w.name_ja, w.name_en, w.name_es, a.real_region,
               a.generation, a.year, rank.confidence, a.prefecture_codes, a.source_urls,
               '{LICENSE}' AS license,
               ST_Multi(ST_MakeValid(a.geometry)) AS geometry
        FROM agg a
        JOIN rank ON rank.r = a.min_rank
        LEFT JOIN wd_game_region w ON lower(w.name_en) = a.region_id
    """
    return write_entity(con, "game_region", query, root=root)
