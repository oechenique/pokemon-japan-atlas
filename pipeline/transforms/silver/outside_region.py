"""outside_region: regiones fuera de Japón, como un punto en su inspiración real.

- Las 5 vienen del seed regions_outside_japan, con fuente, grupo editorial y confidence
  por fila (coordenadas del ítem de Wikidata del lugar real, CC0).
- Wikidata P144 queda de respaldo: si una región falta en el seed, entra desde ahí
  como "teoría de fans" (una sola fuente).
- Generación de PokeAPI (main_generation de cada región); año de la fecha de los
  primeros juegos de esa generación (Wikidata).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import Bronze, create_table, sparql_rows, write_entity

OUTSIDE = ("unova", "kalos", "alola", "galar", "paldea")
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9}
BASED_ON_COLUMNS = ("region", "based_on", "based_on_en", "based_on_es", "coord")
REGION_COLUMNS = ("region", "name_ja", "name_en", "name_es")
GAMES_COLUMNS = ("generation", "game", "first_release")


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    create_table(
        con,
        "wd_based_on",
        BASED_ON_COLUMNS,
        sparql_rows(bronze.json("wikidata", "game_regions_based_on.json"), BASED_ON_COLUMNS),
    )
    create_table(
        con,
        "wd_regions",
        REGION_COLUMNS,
        sparql_rows(bronze.json("wikidata", "game_regions.json"), REGION_COLUMNS),
    )
    create_table(
        con,
        "wd_games",
        GAMES_COLUMNS,
        sparql_rows(bronze.json("wikidata", "generation_games.json"), GAMES_COLUMNS),
    )
    create_table(
        con,
        "pokeapi_region",
        ("region_id", "generation"),
        [(name, pokeapi_generation(bronze, name)) for name in OUTSIDE],
    )
    seed = bronze.path("seeds", "regions_outside_japan.csv")
    outside = ", ".join(f"'{r}'" for r in OUTSIDE)
    query = f"""
        WITH from_wikidata AS (
            SELECT lower(r.name_en) AS region_id, r.name_en AS game_name,
                   coalesce(b.based_on_es, b.based_on_en) AS real_place,
                   b.based_on AS real_place_wikidata,
                   'teoría de fans' AS confidence,
                   'https://www.wikidata.org/wiki/' || b.region || '#P144' AS source_url,
                   'CC0-1.0' AS license,
                   ST_GeomFromText(b.coord) AS geometry
            FROM wd_based_on b JOIN wd_regions r USING (region)
            WHERE lower(r.name_en) IN ({outside}) AND b.coord IS NOT NULL
        ),
        from_seed AS (
            SELECT region_id, game_name, real_place, real_place_wikidata, confidence,
                   source_url, 'LicenseRef-seeds + CC0-1.0' AS license,
                   ST_Point(lon::DOUBLE, lat::DOUBLE) AS geometry
            FROM read_csv('{seed}', all_varchar = true)
        ),
        places AS (
            SELECT * FROM from_seed
            UNION ALL
            SELECT * FROM from_wikidata
            WHERE region_id NOT IN (SELECT region_id FROM from_seed)
        ),
        years AS (
            SELECT generation::INTEGER AS generation, min(year(first_release::TIMESTAMP)) AS year
            FROM wd_games GROUP BY 1
        )
        SELECT p.region_id, p.game_name, g.generation::INTEGER AS generation, y.year,
               p.real_place, p.real_place_wikidata, p.confidence, p.source_url,
               p.license || ' + LicenseRef-factual-data' AS license, p.geometry
        FROM places p
        JOIN pokeapi_region g USING (region_id)
        LEFT JOIN years y ON y.generation = g.generation::INTEGER
    """
    return write_entity(con, "outside_region", query, root=root)


def pokeapi_generation(bronze: Bronze, region: str) -> int:
    data = bronze.json("pokeapi", f"region/{region}.json")
    numeral = data["main_generation"]["name"].removeprefix("generation-")
    return ROMAN[numeral]
