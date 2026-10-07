import copy

import pytest
import yaml

from pipeline.quality.contracts import (
    CONTRACTS_DIR,
    ContractError,
    check_registry_consistency,
    load_contracts,
    validate_contract,
)

# Las 7 de reglas/03 más building, basemap, game_place y outside_region.
EXPECTED = {
    "poi",
    "rail",
    "station",
    "prefecture",
    "game_region",
    "h3_metric",
    "raster_product",
    "building",
    "basemap",
    "game_place",
    "outside_region",
}


@pytest.fixture(scope="module")
def contracts():
    return load_contracts()


@pytest.fixture
def raw():
    return yaml.safe_load((CONTRACTS_DIR / "poi.yaml").read_text(encoding="utf-8"))


def test_every_entity_has_a_valid_contract(contracts):
    assert set(contracts) == EXPECTED


def test_contracts_match_registry_feeds_both_ways(contracts, registry):
    assert check_registry_consistency(contracts, registry) == []


def test_every_contract_requires_license(contracts):
    for contract in contracts.values():
        assert contract.column("license").nullable is False, contract.entity


def test_rule_03_minimums(contracts):
    assert contracts["game_region"].count_min == 4
    assert contracts["prefecture"].count_min == contracts["prefecture"].count_max == 47
    assert contracts["outside_region"].count_min == 5


def test_only_global_layers_skip_the_japan_bbox(contracts):
    outside = {c.entity for c in contracts.values() if not c.inside_japan}
    assert outside == {"basemap", "outside_region"}


def test_night_light_nulls_are_reported_by_prefecture(contracts):
    h3 = contracts["h3_metric"]
    assert h3.column("value").nullable is True
    assert h3.null_report_columns == ("value",) and h3.null_report_by == "prefecture_code"


def test_contract_parses_columns(contracts):
    poi = contracts["poi"]
    assert poi.primary_key == ("poi_id",)
    assert poi.count_by_column == "category"
    assert poi.count_by_min["pokemon_store"] == 7
    assert poi.column("category").allowed[0] == "pokemon_center"
    assert poi.has_geometry and not contracts["h3_metric"].has_geometry


def _drop_column(name):
    def breaker(data):
        data["columns"] = [c for c in data["columns"] if c["name"] != name]

    return breaker


def _set(path, value):
    def breaker(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return breaker


def _column(name, **changes):
    def breaker(data):
        for column in data["columns"]:
            if column["name"] == name:
                column.update(changes)

    return breaker


@pytest.mark.parametrize(
    ("breaker", "message"),
    [
        (_drop_column("license"), "license"),
        (_set(["entity"], "otra"), "nombre del archivo"),
        (_set(["primary_key"], ["no_existe"]), "no existe"),
        (_set(["primary_key"], ["name_en"]), "nulable"),
        (_drop_column("geometry"), "geometry"),
        (_set(["geometry", "types"], ["CIRCLE"]), "geometry.types"),
        (_set(["count", "min"], -1), "count.min"),
        (_set(["count_by", "min"], {"museo": 3}), "fuera de allowed"),
        (_column("poi_id", type="TEXT"), "tipo"),
        (_column("poi_id", pattern="(sin cerrar"), "pattern"),
        (_column("h3_r7", range=[0, 1]), "range"),
        (_column("name_en", colour="rojo"), "claves desconocidas"),
        (_set(["null_report", "columns"], ["poi_id"]), "no es nulable"),
    ],
)
def test_validate_rejects_broken_contracts(raw, breaker, message):
    data = copy.deepcopy(raw)
    breaker(data)
    errors = validate_contract(data, "poi")
    assert any(message in e for e in errors), errors


def test_load_contracts_reports_every_broken_file(tmp_path, raw):
    broken = copy.deepcopy(raw)
    _drop_column("license")(broken)
    (tmp_path / "poi.yaml").write_text(yaml.safe_dump(broken, allow_unicode=True), encoding="utf-8")
    other = copy.deepcopy(raw)
    other["entity"] = "rail"
    (tmp_path / "rail.yaml").write_text(yaml.safe_dump(other, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ContractError) as excinfo:
        load_contracts(tmp_path)
    assert "poi.yaml" in str(excinfo.value)
    assert "rail.yaml" not in str(excinfo.value)


def test_consistency_detects_missing_feed_and_missing_contract(contracts, registry):
    import dataclasses

    sources = []
    for source in registry.sources:
        if source.id == "osm_buildings":
            source = dataclasses.replace(source, feeds=("building", "rail"))
        sources.append(source)
    broken = dataclasses.replace(registry, sources=tuple(sources))
    without_poi = {k: v for k, v in contracts.items() if k != "poi"}
    errors = check_registry_consistency(without_poi, broken)
    assert any("osm_buildings alimenta rail" in e for e in errors)
    assert any("alimenta poi, que no tiene contrato" in e for e in errors)
