"""Gold: tablas derivadas y vistas v_day_XX."""

import json

import pytest

from pipeline.transforms.base import connect, gold_path, write_entity
from pipeline.transforms.gold import (
    null_findings,
    poi_clusters,
    power_plants_kanto,
    shinkansen_edges,
    shinkansen_stations,
    views,
)

RUN = "20261007T100000Z"
POI_COLUMNS = (
    "poi_id, source, source_id, category, name_ja, name_en, name_es, plant_source, plant_output_mw, "
    "address_ja, prefecture_code, prefecture_method, game_region, h3_r7, h3_r9, license, geometry"
)


@pytest.fixture
def con():
    connection = connect()
    yield connection
    connection.close()


def _poi_row(
    poi_id, category, lat, lon, *, source="osm", plant=None, mw=None, region="kanto", name="x"
):
    plant_sql = f"'{plant}'" if plant else "NULL"
    mw_sql = str(mw) if mw is not None else "NULL"
    return (
        f"('{poi_id}', '{source}', '{poi_id}', '{category}', '{name}', NULL, NULL, {plant_sql}, {mw_sql}, "
        f"NULL, 'JP-13', 'within', '{region}', h3_latlng_to_cell_string({lat}, {lon}, 7), "
        f"h3_latlng_to_cell_string({lat}, {lon}, 9), 'ODbL-1.0', ST_Point({lon}, {lat}))"
    )


def _relax_minimum(monkeypatch, module, entity):
    """Los datos sintéticos son chicos: se baja el mínimo del contrato de esa tabla."""
    import dataclasses

    from pipeline.quality.contracts import GOLD_CONTRACTS_DIR, load_contracts

    contracts = load_contracts(GOLD_CONTRACTS_DIR)
    contracts[entity] = dataclasses.replace(contracts[entity], count_min=0, count_max=None)
    original = module.write_entity
    monkeypatch.setattr(
        module,
        "write_entity",
        lambda c, e, q, **k: original(c, e, q, **{**k, "contracts": contracts}),
    )


def _write_gold_poi(con, root, rows):
    query = f"SELECT * FROM (VALUES {', '.join(rows)}) AS t({POI_COLUMNS})"
    write_entity(con, "poi", query, root=root)
    target = gold_path("poi", root)
    target.parent.mkdir(parents=True, exist_ok=True)
    (root / "silver" / "poi.parquet").replace(target)


# Día 4 ----------------------------------------------------------------------------


def test_connected_components_join_cells_through_neighbors():
    cells = ["a", "b", "c", "z"]
    neighbors = {"a": ["a", "b"], "b": ["b", "a", "c"], "c": ["c", "b"], "z": ["z"]}
    component = poi_clusters.connected_components(cells, neighbors)
    assert component["a"] == component["b"] == component["c"] == "a"
    assert component["z"] == "z"


def test_poke_lid_series_in_a_town_form_one_cluster(con, tmp_path, monkeypatch):
    rows = [_poi_row(f"osm:node/{i}", "poke_lids", 35.50 + i * 0.01, 139.40) for i in range(4)]
    rows.append(_poi_row("osm:node/9", "poke_lids", 43.0, 141.3))  # aislada en Sapporo
    rows += [
        _poi_row("osm:node/20", "pokemon_center", 35.68, 139.76),
        _poi_row("osm:node/21", "pokemon_store", 35.681, 139.765),
    ]
    _write_gold_poi(con, tmp_path, rows)
    _relax_minimum(monkeypatch, poi_clusters, "poi_clusters")
    summary = poi_clusters.build(con, RUN, root=tmp_path)
    assert summary["stats"]["poke_lids_clusters"] == 1
    assert summary["stats"]["poke_lids_isolated_points"] == 1
    assert summary["stats"]["pokemon_retail_clusters"] == 1
    path = gold_path("poi_clusters", tmp_path).as_posix()
    rows = con.execute(
        f"SELECT layer, member_count, ST_GeometryType(geometry)::VARCHAR FROM '{path}' ORDER BY 1"
    ).fetchall()
    assert rows == [("poke_lids", 4, "POLYGON"), ("pokemon_retail", 2, "POLYGON")]


# Día 12 ---------------------------------------------------------------------------


def test_power_plants_keep_big_or_non_solar_sources(con, tmp_path, monkeypatch):
    rows = [
        _poi_row("osm:way/1", "power_plant", 35.5, 139.5, plant="solar", mw=1.5),
        _poi_row("osm:way/2", "power_plant", 35.5, 139.6, plant="solar", mw=20.0),
        _poi_row("osm:way/3", "power_plant", 35.5, 139.7, plant="hydro"),
        _poi_row("osm:way/4", "power_plant", 35.5, 139.8, plant="coal;gas;oil", mw=2000.0),
        _poi_row("osm:way/5", "power_plant", 34.7, 135.5, plant="nuclear", region="johto"),
        _poi_row("osm:way/6", "power_plant", 35.5, 139.9, plant="biomass"),
    ]
    _write_gold_poi(con, tmp_path, rows)
    _relax_minimum(monkeypatch, power_plants_kanto, "power_plants_kanto")
    power_plants_kanto.build(con, RUN, root=tmp_path)
    path = gold_path("power_plants_kanto", tmp_path).as_posix()
    kept = dict(con.execute(f"SELECT poi_id, reason FROM '{path}'").fetchall())
    assert kept == {"osm:way/2": "capacity", "osm:way/3": "source", "osm:way/4": "source+capacity"}


# Día 24 ---------------------------------------------------------------------------


def test_seed_station_match_tiebreaks():
    from pipeline.transforms.silver.shinkansen_line_station import choose

    fukushima_city = ("osm:node/1", 140.459, 37.755, "JP-07", 3.0)
    fukushima_osaka = ("osm:node/2", 135.486, 34.697, "JP-27", None)
    assert choose([], "full", None) == (None, None)
    assert choose([fukushima_city], "full", None) == (fukushima_city, "unique")
    # Full: la cercanía a la vía del Shinkansen desempata.
    assert choose([fukushima_osaka, fukushima_city], "full", None) == (fukushima_city, "track")
    # Primera estación de una mini (sin anterior): también por la vía.
    assert choose([fukushima_osaka, fukushima_city], "mini", None) == (fukushima_city, "track")
    # Resto de una mini: la más cercana a la estación anterior de la línea.
    near_yamagata = ("osm:node/3", 140.33, 38.25, "JP-06", None)
    far = ("osm:node/4", 130.0, 33.0, "JP-40", None)
    assert choose([far, near_yamagata], "mini", (140.3, 38.2)) == (near_yamagata, "sequence")


def _line_stations(con, root, rows):
    values = ", ".join(
        f"('{line}', '{line}', '{kind}', 'JR', {seq}, '{name}', 'osm:node/{seq}{line[:1]}', 1, 'unique', "
        f"NULL, 'https://x', 'x', ST_Point({lon}, {lat}))"
        for line, kind, seq, name, lon, lat in rows
    )
    write_entity(
        con,
        "shinkansen_line_station",
        f"""
        SELECT * FROM (VALUES {values}) AS t(line_id, line_name_ja, kind, operator, seq, name_ja,
            station_id, candidates, match_method, prefecture_code, source_url, license, geometry)
    """,
        root=root,
    )
    gold = root / "gold"
    gold.mkdir(exist_ok=True)
    (root / "silver" / "shinkansen_line_station.parquet").replace(
        gold / "shinkansen_line_station.parquet"
    )


def test_stations_and_edges_from_the_official_list(con, tmp_path, monkeypatch):
    _line_stations(
        con,
        tmp_path,
        [
            ("tohoku", "full", 1, "東京", 139.767, 35.681),
            ("tohoku", "full", 2, "上野", 139.777, 35.713),
            ("tohoku", "full", 3, "福島", 140.459, 37.755),
            ("joetsu", "full", 1, "東京", 139.767, 35.681),
            ("joetsu", "full", 2, "上野", 139.777, 35.713),
            ("yamagata", "mini", 1, "福島", 140.459, 37.755),
            ("yamagata", "mini", 2, "米沢", 140.11, 37.91),
        ],
    )
    for module, table in (
        (shinkansen_stations, "shinkansen_stations"),
        (shinkansen_edges, "shinkansen_edges"),
    ):
        _relax_minimum(monkeypatch, module, table)
        module.build(con, RUN, root=tmp_path)
    stations = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT name_ja, kind, lines FROM '{gold_path('shinkansen_stations', tmp_path).as_posix()}'"
        ).fetchall()
    }
    assert stations["福島"] == ("full", ["tohoku", "yamagata"])
    assert stations["米沢"] == ("mini", ["yamagata"])
    edges = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT edge_id, lines, kind, schematic FROM '{gold_path('shinkansen_edges', tmp_path).as_posix()}'"
        ).fetchall()
    }
    # Tokio-Ueno lo comparten dos líneas: un solo tramo con las dos.
    assert edges["shinkansen:上野|shinkansen:東京"] == (["joetsu", "tohoku"], "full", False)
    assert edges["shinkansen:福島|shinkansen:米沢"] == (["yamagata"], "mini", True)
    assert len(edges) == 3


def test_repo_seed_has_every_line_and_the_control_list():
    import csv

    from pipeline.sources import seeds

    path = seeds.PIPELINE_DIR / "seeds" / "shinkansen_stations.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    lines = {r["line_id"]: r["kind"] for r in rows}
    assert lines["akita"] == lines["yamagata"] == "mini"
    assert {
        "tokaido",
        "sanyo",
        "kyushu",
        "nishikyushu",
        "tohoku",
        "hokkaido",
        "joetsu",
        "hokuriku",
    } <= set(lines)
    names = {r["station_name_ja"] for r in rows}
    assert {"新潟", "秋田", "山形"} <= names
    assert not {"野々市", "新白島", "上牧"} & names
    assert all(r["source_url"].startswith("https://") for r in rows)


# Día 18 ---------------------------------------------------------------------------


def test_null_findings_add_null_island_to_the_report_coverage(con, tmp_path, monkeypatch):
    publish = tmp_path / "publish" / RUN
    publish.mkdir(parents=True)
    coverage = [
        {
            "id": "osm_station_lines",
            "title": "t",
            "value": 4,
            "total": 9091,
            "share": 0.0004,
            "source": "osm_overpass",
            "detail": "",
        }
    ]
    (publish / "quality_report.json").write_text(
        json.dumps({"coverage": coverage}), encoding="utf-8"
    )
    runs = tmp_path / "silver" / "_runs"
    runs.mkdir(parents=True)
    lineage = {"entities": [{"entity": "basemap", "stats": {"null_island_excluded": 2}}]}
    (runs / f"run_id={RUN}.json").write_text(json.dumps(lineage), encoding="utf-8")
    _relax_minimum(monkeypatch, null_findings, "null_findings")
    null_findings.build(con, RUN, root=tmp_path, publish=tmp_path / "publish")
    path = gold_path("null_findings", tmp_path).as_posix()
    rows = dict(con.execute(f"SELECT finding_id, value FROM '{path}'").fetchall())
    assert rows == {"osm_station_lines": 4, "natural_earth_null_island": 2}


# Vistas ---------------------------------------------------------------------------


def test_every_catalog_day_has_a_view_or_a_documented_reason():
    assert set(views.VIEWS) | set(views.DAYS_WITHOUT_VIEW) == set(range(1, 31))
    assert not set(views.VIEWS) & set(views.DAYS_WITHOUT_VIEW)


def test_views_only_read_gold_by_relative_name():
    for day, sql in views.VIEWS.items():
        assert "silver" not in sql and "/opt/airflow" not in sql, day
