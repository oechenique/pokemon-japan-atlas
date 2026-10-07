"""DQ gate entre Silver y Gold (reglas/03). Escribe publish/<run_id>/quality_report.json.

Bloqueantes (si alguno falla, la tarea falla y no se construye Gold):
- esquema igual al del contrato;
- columnas no nulables sin nulos (incluida license);
- clave primaria única;
- pattern, allowed y range de cada columna;
- geometrías válidas, no vacías y del tipo del contrato;
- todo dentro del bbox de Japón, salvo las entidades globales;
- conteos mínimos y máximos, también por categoría;
- cruces: generación de cada región del juego contra PokeAPI y año contra la fecha de
  los primeros juegos (Wikidata), y toda estación del seed oficial del Shinkansen con
  su nodo en OSM.

Informativos (no bloquean): tasas de nulos por columna y por prefectura, variación de
conteos contra la corrida anterior, estadísticas de Silver (deduplicación, prefecturas)
y la sección coverage, con los huecos de las fuentes. El informe es el insumo del día 18.

El informe se escribe siempre, pase o no, antes de fallar.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb

from pipeline.quality.contracts import Contract, load_contracts
from pipeline.sources.base import RUN_ID, utc_now
from pipeline.sources.registry import JAPAN_EXTENT
from pipeline.transforms.base import (
    GEOMETRY_PARQUET_TYPE,
    RUNS_DIR,
    SILVER,
    Bronze,
    connect,
    data_root,
    silver_path,
    sparql_rows,
)
from pipeline.transforms.silver.outside_region import ROMAN
from pipeline.transforms.silver.shinkansen_route_stop import DIRECTION

REPORT_NAME = "quality_report.json"
REPORT_VERSION = 1
# Kuriles del sur dentro de la bbox de Hokkaidō: se sigue a Natural Earth (control de
# hecho), así que sus puntos quedan sin prefectura.
KURILS = {"min_lon": 145.3, "min_lat": 43.3}


class QualityError(RuntimeError):
    """Falló al menos un check bloqueante."""


def publish_root() -> Path:
    return Path(os.environ.get("ATLAS_PUBLISH_DIR", "publish"))


def run_gate(run_id: str, *, root: Path | None = None, publish: Path | None = None) -> dict:
    if not RUN_ID.match(run_id):
        raise ValueError(f"run_id inválido: {run_id!r}")
    contracts = load_contracts()
    bronze = Bronze(run_id, root)
    con = connect()
    try:
        checks: list[dict[str, Any]] = []
        null_rates: dict[str, Any] = {}
        rows: dict[str, int] = {}
        for entity, contract in sorted(contracts.items()):
            path = silver_path(entity, root)
            if not path.is_file():
                checks.append(_check(entity, "exists", 1, "falta el parquet de Silver"))
                continue
            table = f"'{path.as_posix()}'"
            rows[entity] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            checks += entity_checks(con, contract, table)
            if contract.null_report_columns:
                null_rates[entity] = null_report(con, contract, table)
        checks += cross_checks(con, bronze, root)
        lineage = _lineage(run_id, root)
        report = {
            "version": REPORT_VERSION,
            "run_id": run_id,
            "generated_at": utc_now(),
            "status": "passed" if all(c["passed"] for c in checks) else "failed",
            "blocking": {
                "passed": sum(c["passed"] for c in checks),
                "failed": sum(not c["passed"] for c in checks),
                "checks": checks,
            },
            "informative": {
                "rows": rows,
                "null_rates": null_rates,
                "count_variation": count_variation(run_id, rows, publish),
                "silver_stats": {e["entity"]: e.get("stats", {}) for e in lineage},
                "bronze": bronze_modes(bronze),
            },
            "coverage": coverage_findings(con, bronze, root, lineage),
        }
    finally:
        con.close()
    target = (publish or publish_root()) / run_id / REPORT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["status"] != "passed":
        failed = [f"{c['entity']}.{c['check']}" for c in checks if not c["passed"]]
        raise QualityError(f"DQ gate: {len(failed)} checks bloqueantes fallaron: {failed[:10]}")
    return {
        "status": report["status"],
        "path": target.as_posix(),
        "failed": 0,
        "checks": len(checks),
    }


# Bloqueantes ---------------------------------------------------------------------


def entity_checks(con: duckdb.DuckDBPyConnection, contract: Contract, table: str) -> list[dict]:
    entity = contract.entity
    checks = [_schema_check(con, contract, table)]
    count = lambda where: con.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]  # noqa: E731

    for column in contract.columns:
        name = column.name
        if not column.nullable:
            checks.append(_check(entity, f"not_null.{name}", count(f"{name} IS NULL")))
        if column.pattern:
            pattern = column.pattern.replace("'", "''")
            checks.append(
                _check(
                    entity,
                    f"pattern.{name}",
                    count(f"{name} IS NOT NULL AND NOT regexp_matches({name}, '{pattern}')"),
                )
            )
        if column.allowed:
            allowed = ", ".join("'" + str(v).replace("'", "''") + "'" for v in column.allowed)
            checks.append(
                _check(
                    entity,
                    f"allowed.{name}",
                    count(f"{name} IS NOT NULL AND {name} NOT IN ({allowed})"),
                )
            )
        if column.range:
            lo, hi = column.range
            checks.append(
                _check(
                    entity,
                    f"range.{name}",
                    count(f"{name} IS NOT NULL AND ({name} < {lo} OR {name} > {hi})"),
                )
            )

    pk = ", ".join(contract.primary_key)
    duplicates = con.execute(f"SELECT count(*) - count(DISTINCT ({pk})) FROM {table}").fetchone()[0]
    checks.append(_check(entity, "primary_key_unique", duplicates))

    south, west, north, east = JAPAN_EXTENT
    if contract.has_geometry:
        checks.append(
            _check(
                entity,
                "geometry_valid",
                count("geometry IS NULL OR ST_IsEmpty(geometry) OR NOT ST_IsValid(geometry)"),
            )
        )
        types = ", ".join(f"'{t}'" for t in contract.geometry_types)
        checks.append(
            _check(
                entity,
                "geometry_type",
                count(f"ST_GeometryType(geometry)::VARCHAR NOT IN ({types})"),
            )
        )
        if contract.inside_japan:
            checks.append(
                _check(
                    entity,
                    "inside_japan",
                    count(
                        f"ST_XMin(geometry) < {west} OR ST_XMax(geometry) > {east} "
                        f"OR ST_YMin(geometry) < {south} OR ST_YMax(geometry) > {north}"
                    ),
                )
            )
    elif contract.inside_japan and "h3" in contract.column_names:
        checks.append(
            _check(
                entity,
                "inside_japan",
                count(
                    f"h3_cell_to_lng(h3) < {west} OR h3_cell_to_lng(h3) > {east} "
                    f"OR h3_cell_to_lat(h3) < {south} OR h3_cell_to_lat(h3) > {north}"
                ),
            )
        )

    rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    too_few = rows < contract.count_min
    too_many = contract.count_max is not None and rows > contract.count_max
    expected = f">= {contract.count_min}" + (
        f" y <= {contract.count_max}" if contract.count_max is not None else ""
    )
    checks.append(
        _check(entity, "count", int(too_few or too_many), f"{rows} filas (se espera {expected})")
    )
    if contract.count_by_column:
        found = dict(
            con.execute(
                f"SELECT {contract.count_by_column}, count(*) FROM {table} GROUP BY 1"
            ).fetchall()
        )
        for value, minimum in sorted(contract.count_by_min.items()):
            n = found.get(value, 0)
            checks.append(
                _check(
                    entity, f"count_by.{value}", int(n < minimum), f"{n} filas (mínimo {minimum})"
                )
            )
    return checks


def _schema_check(con: duckdb.DuckDBPyConnection, contract: Contract, table: str) -> dict:
    actual = [(r[0], r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM {table}").fetchall()]
    expected = [
        (c.name, GEOMETRY_PARQUET_TYPE if c.type == "GEOMETRY" else c.type)
        for c in contract.columns
    ]
    detail = "" if actual == expected else f"esperado {expected}, encontrado {actual}"
    return _check(contract.entity, "schema", int(actual != expected), detail)


def cross_checks(con: duckdb.DuckDBPyConnection, bronze: Bronze, root: Path | None) -> list[dict]:
    """Generación (PokeAPI) y año (Wikidata) de cada región, y estaciones del seed del
    Shinkansen con su nodo en OSM."""
    games = sparql_rows(
        bronze.json("wikidata", "generation_games.json"), ("generation", "first_release")
    )
    year_of = {}
    for generation, release in games:
        year_of[int(generation)] = min(year_of.get(int(generation), 9999), int(release[:4]))
    checks = []
    for entity in ("game_region", "outside_region"):
        path = silver_path(entity, root)
        if not path.is_file():
            continue
        for region_id, generation, year in con.execute(
            f"SELECT region_id, generation, year FROM '{path.as_posix()}' ORDER BY 1"
        ).fetchall():
            data = bronze.json("pokeapi", f"region/{region_id}.json")
            pokeapi = ROMAN[data["main_generation"]["name"].removeprefix("generation-")]
            checks.append(
                _check(
                    entity,
                    f"pokeapi_generation.{region_id}",
                    int(pokeapi != generation),
                    f"Silver {generation}, PokeAPI {pokeapi}",
                )
            )
            expected = year_of.get(generation)
            checks.append(
                _check(
                    entity,
                    f"release_year.{region_id}",
                    int(expected != year),
                    f"Silver {year}, Wikidata {expected}",
                )
            )
    stations = silver_path("shinkansen_line_station", root)
    if stations.is_file():
        missing = [
            name
            for (name,) in con.execute(
                f"SELECT DISTINCT name_ja FROM '{stations.as_posix()}' "
                "WHERE station_id IS NULL ORDER BY 1"
            ).fetchall()
        ]
        detail = f"Sin nodo en OSM: {', '.join(missing)}" if missing else ""
        checks.append(
            _check("shinkansen_line_station", "seed_station_in_osm", len(missing), detail)
        )
    return checks


def _check(entity: str, check: str, failing: int, detail: str = "") -> dict:
    return {
        "entity": entity,
        "check": check,
        "passed": failing == 0,
        "failing": int(failing),
        "detail": detail,
    }


# Informativos --------------------------------------------------------------------


def null_report(con: duckdb.DuckDBPyConnection, contract: Contract, table: str) -> dict:
    result = {}
    for column in contract.null_report_columns:
        overall = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE {column} IS NULL) FROM {table}"
        ).fetchone()
        entry = {"rows": overall[0], "nulls": overall[1], "rate": _rate(overall[1], overall[0])}
        by = contract.null_report_by
        if by and by != column:
            groups = con.execute(f"""
                SELECT coalesce({by}, '(sin {by})'), count(*),
                       count(*) FILTER (WHERE {column} IS NULL)
                FROM {table} GROUP BY 1 ORDER BY 1
            """).fetchall()
            entry["by"] = {g: {"rows": n, "nulls": z, "rate": _rate(z, n)} for g, n, z in groups}
        result[column] = entry
    return result


def count_variation(run_id: str, rows: dict[str, int], publish: Path | None) -> dict:
    """Filas por entidad contra el último informe anterior a esta corrida."""
    base = publish or publish_root()
    previous = sorted(
        p
        for p in base.glob(f"*/{REPORT_NAME}")
        if p.parent.name < run_id and RUN_ID.match(p.parent.name)
    )
    if not previous:
        return {"previous_run_id": None, "entities": {}}
    before = json.loads(previous[-1].read_text(encoding="utf-8"))["informative"]["rows"]
    entities = {
        entity: {
            "previous": before.get(entity),
            "current": n,
            "change": None
            if not before.get(entity)
            else round((n - before[entity]) / before[entity], 4),
        }
        for entity, n in sorted(rows.items())
    }
    return {"previous_run_id": previous[-1].parent.name, "entities": entities}


def bronze_modes(bronze: Bronze) -> dict:
    """Cómo se obtuvo cada fuente: reusos y modo de Overpass (lo usa la Fase 3)."""
    result = {}
    for source in sorted(
        p.name for p in bronze.root.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        try:
            meta = bronze.metadata(source)
        except Exception:
            continue
        result[source] = {
            "checksum": meta.get("checksum"),
            "files": len(meta.get("files", [])),
            "reused_files": sum(1 for f in meta.get("files", []) if f.get("reused_from")),
            "overpass_mode": meta.get("extra", {}).get("overpass_mode"),
            "warnings": meta.get("warnings", []),
        }
    return result


def coverage_findings(
    con: duckdb.DuckDBPyConnection, bronze: Bronze, root: Path | None, lineage: list[dict]
) -> list[dict]:
    """Huecos de las fuentes que fueron apareciendo: insumo del día 18 (NULL)."""
    silver = lambda entity: f"'{silver_path(entity, root).as_posix()}'"  # noqa: E731
    one = lambda sql: con.execute(sql).fetchone()  # noqa: E731
    stats = {e["entity"]: e.get("stats", {}) for e in lineage}
    findings = []

    places = sparql_rows(bronze.json("wikidata", "game_places_p144.json"), ("place", "based_on"))
    total = len({p for p, _ in places})
    with_p144 = len({p for p, b in places if b})
    findings.append(
        _finding(
            "wikidata_p144_places",
            "Lugares del juego (Kanto, Johto, Hoenn, Sinnoh) con P144 en Wikidata",
            with_p144,
            total,
            "wikidata",
            "Ninguno cita referencias; uno apunta fuera de Japón (Battle Zone → Sajalín).",
        )
    )
    based = sparql_rows(bronze.json("wikidata", "game_regions_based_on.json"), ("region",))
    regions = sparql_rows(bronze.json("wikidata", "game_regions.json"), ("region", "name_en"))
    missing = sorted(name for q, name in regions if q not in {r for (r,) in based})
    findings.append(
        _finding(
            "wikidata_p144_regions",
            "Regiones principales con P144 en Wikidata",
            len(regions) - len(missing),
            len(regions),
            "wikidata",
            f"Sin P144: {', '.join(missing)}.",
        )
    )

    cafes = one(f"SELECT count(*) FROM {silver('poi')} WHERE category = 'pokemon_cafe'")[0]
    osm_brand = stats.get("poi", {}).get("seed_cafes_replacing_osm", 0)
    findings.append(
        _finding(
            "osm_pokemon_cafe_brand",
            "Pokémon Café con la etiqueta brand en OSM",
            osm_brand,
            cafes,
            "osm_overpass",
            "El de Osaka está en OSM solo por nombre (nodo 7012998620); "
            "los dos entran por el seed.",
        )
    )
    findings.append(
        _finding(
            "osm_center_store_brand",
            "Pokémon Center y Store con la marca equivocada en OSM",
            stats.get("poi", {}).get("reclassified_by_name", 0),
            None,
            "osm_overpass",
            "Se separan por el nombre en Silver.",
        )
    )

    n, with_lines = one(f"SELECT count(*), count(lines) FROM {silver('station')}")
    findings.append(
        _finding(
            "osm_station_lines",
            "Estaciones con el tag de línea en OSM",
            with_lines,
            n,
            "osm_overpass",
        )
    )
    n, height, levels = one(
        f"SELECT count(*), count(height_m), count(levels) FROM {silver('building')}"
    )
    findings.append(
        _finding(
            "osm_building_height",
            "Edificios con altura en OSM (día 14)",
            height,
            n,
            "osm_buildings",
        )
    )
    findings.append(
        _finding(
            "osm_building_levels",
            "Edificios con cantidad de pisos en OSM (día 14)",
            levels,
            n,
            "osm_buildings",
        )
    )

    zones = con.execute(f"""
        SELECT CASE WHEN ST_X(geometry) > {KURILS["min_lon"]}
                         AND ST_Y(geometry) > {KURILS["min_lat"]}
                    THEN 'kuriles' ELSE 'islas' END AS zone, count(*)
        FROM (SELECT geometry FROM {silver("poi")} WHERE prefecture_code IS NULL
              UNION ALL SELECT geometry FROM {silver("station")} WHERE prefecture_code IS NULL)
        GROUP BY 1
    """).fetchall()
    zone = dict(zones)
    findings.append(
        _finding(
            "points_without_prefecture",
            "Puntos (POI y estaciones) sin prefectura",
            sum(zone.values()),
            None,
            "natural_earth",
            f"{zone.get('kuriles', 0)} en las Kuriles del sur (se sigue a Natural Earth: "
            "control de hecho) y "
            f"{zone.get('islas', 0)} en islas chicas que Natural Earth a 10 m no tiene.",
        )
    )

    routes = con.execute(f"""
        SELECT DISTINCT trim(regexp_replace(route_name, '{DIRECTION}', ''))
        FROM {silver("shinkansen_route_stop")} WHERE route_name IS NOT NULL
    """).fetchall()
    lines = one(f"""
        SELECT count(DISTINCT name_ja) FROM {silver("rail")}
        WHERE kind = 'shinkansen' AND name_ja LIKE '%新幹線'
    """)[0]
    findings.append(
        _finding(
            "osm_shinkansen_routes",
            "Líneas del Shinkansen con relación de ruta y paradas en OSM",
            len(routes),
            lines,
            "osm_overpass",
            f"Con ruta: {', '.join(sorted(r for (r,) in routes))}. Las estaciones del día 24 "
            "salen del listado oficial de JR (seed shinkansen_stations).",
        )
    )

    lids = one(f"SELECT count(*) FROM {silver('poi')} WHERE category = 'poke_lids'")[0]
    reference = _reference(con, bronze, "poke_lids_total")
    findings.append(
        _finding(
            "osm_poke_lids",
            "Poké Lids en OSM contra el total de referencia",
            lids,
            int(reference["value"]),
            "osm_overpass",
            f"Referencia: {reference['notes']} ({reference['as_of']}, {reference['source_url']}).",
        )
    )

    dishes = sparql_rows(bronze.json("wikidata", "regional_dishes.json"), ("dish", "iso"))
    prefectures = {iso for _, iso in dishes if iso}
    all_codes = {f"JP-{i:02d}" for i in range(1, 48)}
    findings.append(
        _finding(
            "wikidata_regional_dishes",
            "Prefecturas con algún plato regional en Wikidata",
            len(prefectures),
            47,
            "wikidata",
            f"{len({d for d, iso in dishes if iso})} de {len({d for d, _ in dishes})} "
            "platos de Japón tienen "
            f"prefectura. Sin ninguno: {', '.join(sorted(all_codes - prefectures))}.",
        )
    )

    nulls, cells = one(f"""
        SELECT count(*) FILTER (WHERE value IS NULL), count(*) FROM {silver("h3_metric")}
        WHERE metric = 'night_light' AND resolution = 8
    """)
    by_pref = con.execute(f"""
        SELECT coalesce(prefecture_code, '(sin prefectura)'), count(*) FROM {silver("h3_metric")}
        WHERE metric = 'night_light' AND resolution = 8 AND value IS NULL GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    findings.append(
        _finding(
            "viirs_night_light_null",
            "Celdas de luz nocturna (resolución 8) sin dato (NULL)",
            nulls,
            cells,
            "viirs_night",
            "Sin ningún píxel válido en la celda (relleno o calidad 255); "
            "quedan en NULL, nunca en 0. " + ", ".join(f"{p}: {n}" for p, n in by_pref),
        )
    )
    return findings


def _finding(
    id_: str, title: str, value: int, total: int | None, source: str, detail: str = ""
) -> dict:
    return {
        "id": id_,
        "title": title,
        "value": value,
        "total": total,
        "share": None if not total else round(value / total, 4),
        "source": source,
        "detail": detail,
    }


def _reference(con: duckdb.DuckDBPyConnection, bronze: Bronze, reference_id: str) -> dict:
    path = bronze.path("seeds", "coverage_references.csv")
    row = con.execute(
        f"SELECT * FROM read_csv('{path}', all_varchar = true) WHERE reference_id = ?",
        [reference_id],
    ).fetchone()
    columns = [d[0] for d in con.description]
    return dict(zip(columns, row, strict=True))


def _lineage(run_id: str, root: Path | None) -> list[dict]:
    path = (root or data_root()) / SILVER / RUNS_DIR / f"run_id={run_id}.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["entities"]


def _rate(part: int, whole: int) -> float | None:
    return None if not whole else round(part / whole, 4)
