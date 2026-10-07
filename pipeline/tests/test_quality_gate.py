"""DQ gate: cada check bloqueante detecta su violación; los informativos no bloquean."""

import json

import pytest

from pipeline.quality import gate
from pipeline.quality.contracts import load_contracts
from pipeline.transforms.base import connect, write_entity

GOOD_POI = """
    SELECT * FROM (VALUES
      ('osm:node/1', 'osm', 'node/1', 'pokemon_center', 'ポケモンセンター', 'Pokémon Center', NULL, NULL, NULL, NULL,
       'JP-13', 'within', 'kanto', h3_latlng_to_cell_string(35.68, 139.77, 7), h3_latlng_to_cell_string(35.68, 139.77, 9),
       'ODbL-1.0', ST_Point(139.77, 35.68)),
      ('osm:node/2', 'osm', 'node/2', 'onsen', '湯', NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, h3_latlng_to_cell_string(35.0, 139.0, 7), h3_latlng_to_cell_string(35.0, 139.0, 9),
       'ODbL-1.0', ST_Point(139.0, 35.0))
    ) AS t(poi_id, source, source_id, category, name_ja, name_en, name_es, plant_source, plant_output_mw, address_ja,
           prefecture_code, prefecture_method, game_region, h3_r7, h3_r9, license, geometry)
"""


@pytest.fixture
def con():
    connection = connect()
    yield connection
    connection.close()


@pytest.fixture
def poi_contract():
    return load_contracts()["poi"]


def _failed(checks):
    return {c["check"] for c in checks if not c["passed"]}


def _poi_table(con, tmp_path, query):
    write_entity(con, "poi", query, root=tmp_path)
    return f"'{(tmp_path / 'silver' / 'poi.parquet').as_posix()}'"


def test_clean_rows_only_fail_the_minimum_counts(con, tmp_path, poi_contract):
    table = _poi_table(con, tmp_path, GOOD_POI)
    failed = _failed(gate.entity_checks(con, poi_contract, table))
    # Dos filas no alcanzan los mínimos del contrato, y eso es lo único que falla.
    assert failed == {"count"} | {f"count_by.{c}" for c in poi_contract.count_by_min}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (("'osm:node/2'", "'osm:node/1'"), "primary_key_unique"),
        (("'ODbL-1.0', ST_Point(139.0", "NULL, ST_Point(139.0"), "not_null.license"),
        (("'osm:node/2', 'osm'", "'nodo-2', 'osm'"), "pattern.poi_id"),
        (("'onsen'", "'karaoke'"), "allowed.category"),
        (("ST_Point(139.0, 35.0)", "ST_Point(-58.4, -34.6)"), "inside_japan"),
        (
            ("ST_Point(139.0, 35.0)", "ST_GeomFromText('LINESTRING(139 35, 139.1 35.1)')"),
            "geometry_type",
        ),
        (
            (
                "ST_Point(139.0, 35.0)",
                "ST_GeomFromText('POLYGON((139 35, 139.1 35.1, 139.1 35, 139 35.1, 139 35))')",
            ),
            "geometry_valid",
        ),
    ],
)
def test_each_blocking_check_catches_its_violation(con, tmp_path, poi_contract, change, expected):
    table = _poi_table(con, tmp_path, GOOD_POI.replace(*change))
    assert expected in _failed(gate.entity_checks(con, poi_contract, table))


def test_null_report_by_prefecture(con, tmp_path, poi_contract):
    table = _poi_table(con, tmp_path, GOOD_POI)
    report = gate.null_report(con, poi_contract, table)
    assert report["name_en"]["nulls"] == 1 and report["name_en"]["rate"] == 0.5
    assert report["name_en"]["by"]["JP-13"]["rate"] == 0.0
    assert report["name_en"]["by"]["(sin prefecture_code)"]["nulls"] == 1


def test_count_variation_against_the_previous_report(tmp_path):
    old = tmp_path / "20261001T000000Z"
    old.mkdir()
    (old / gate.REPORT_NAME).write_text(
        json.dumps({"informative": {"rows": {"poi": 100}}}), encoding="utf-8"
    )
    result = gate.count_variation("20261007T000000Z", {"poi": 90, "rail": 5}, tmp_path)
    assert result["previous_run_id"] == "20261001T000000Z"
    assert result["entities"]["poi"]["change"] == -0.1
    assert result["entities"]["rail"]["previous"] is None


def test_finding_share():
    assert gate._finding("x", "t", 257, 400, "osm")["share"] == 0.6425
    assert gate._finding("x", "t", 3, None, "osm")["share"] is None


def test_run_gate_writes_the_report_and_fails_when_silver_is_missing(tmp_path, monkeypatch):
    run = "20261007T100000Z"
    (tmp_path / "bronze").mkdir()
    monkeypatch.setattr(gate, "cross_checks", lambda *a, **k: [])
    monkeypatch.setattr(gate, "coverage_findings", lambda *a, **k: [])
    monkeypatch.setattr(gate, "bronze_modes", lambda *a, **k: {})
    with pytest.raises(gate.QualityError):
        gate.run_gate(run, root=tmp_path, publish=tmp_path / "publish")
    report = json.loads((tmp_path / "publish" / run / gate.REPORT_NAME).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert {c["check"] for c in report["blocking"]["checks"]} == {"exists"}
