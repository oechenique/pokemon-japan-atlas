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


def test_minimum_spanning_tree_chains_stations_along_a_line():
    positions = {"a": (35.0, 139.0), "b": (35.0, 139.5), "c": (35.0, 140.0), "d": (35.0, 140.4)}
    tree = shinkansen_edges.minimum_spanning_tree(sorted(positions), positions.get)
    assert sorted(tuple(sorted(e)) for e in tree) == [("a", "b"), ("b", "c"), ("c", "d")]


def test_shinkansen_stations_use_routes_then_a_tight_distance(con, tmp_path, monkeypatch):
    gold = tmp_path / "gold"
    gold.mkdir()
    write_entity(
        con,
        "station",
        """
        SELECT * FROM (VALUES
          ('osm:node/1', '上野', NULL, NULL, 'JR東日本', NULL, 'JP-13', h3_latlng_to_cell_string(35.713, 139.777, 9), 'ODbL-1.0', ST_Point(139.777, 35.713)),
          ('osm:node/2', '新横浜', NULL, NULL, '東海旅客鉄道', NULL, 'JP-14', h3_latlng_to_cell_string(35.5075, 139.617, 9), 'ODbL-1.0', ST_Point(139.617, 35.5075)),
          ('osm:node/3', '有楽町', NULL, NULL, 'JR東日本', NULL, 'JP-13', h3_latlng_to_cell_string(35.675, 139.7633, 9), 'ODbL-1.0', ST_Point(139.7633, 35.675)),
          ('osm:node/4', '鉄道博物館', NULL, NULL, '埼玉新都市交通', NULL, 'JP-11', h3_latlng_to_cell_string(35.92, 139.62, 9), 'ODbL-1.0', ST_Point(139.62, 35.92))
        ) AS t(station_id, name_ja, name_en, name_es, operator, lines, prefecture_code, h3_r9, license, geometry)
    """,
        root=tmp_path,
    )
    write_entity(
        con,
        "rail",
        """
        SELECT * FROM (VALUES
          ('osm:way/10', 'shinkansen', '東海道新幹線', NULL, NULL, NULL, 1.0, 'ODbL-1.0',
           ST_GeomFromText('LINESTRING(139.617 35.50, 139.617 35.52, 139.7630 35.66, 139.7630 35.69)')),
          ('osm:way/11', 'shinkansen', '東北新幹線', NULL, NULL, NULL, 1.0, 'ODbL-1.0',
           ST_GeomFromText('LINESTRING(139.62 35.90, 139.62 35.95)'))
        ) AS t(rail_id, kind, name_ja, name_en, name_es, operator, length_m, license, geometry)
    """,
        root=tmp_path,
    )
    write_entity(
        con,
        "shinkansen_route_stop",
        """
        SELECT * FROM (VALUES
          ('osm:relation/1', '東北新幹線（下り）', 1, 'osm:node/100', 'osm:node/1', '上野', 'ODbL-1.0', ST_Point(139.777, 35.713))
        ) AS t(route_id, route_name, stop_order, stop_node, station_id, name_ja, license, geometry)
    """,
        root=tmp_path,
    )
    for entity in ("station", "rail", "shinkansen_route_stop"):
        (tmp_path / "silver" / f"{entity}.parquet").replace(gold / f"{entity}.parquet")
    _relax_minimum(monkeypatch, shinkansen_stations, "shinkansen_stations")
    shinkansen_stations.build(con, RUN, root=tmp_path)
    path = gold_path("shinkansen_stations", tmp_path).as_posix()
    rows = dict(con.execute(f"SELECT name_ja, method FROM '{path}'").fetchall())
    # Ueno por la ruta; Shin-Yokohama sobre la vía; Yūrakuchō a ~30 m y el New Shuttle, fuera.
    assert rows == {"上野": "route", "新横浜": "distance"}


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
