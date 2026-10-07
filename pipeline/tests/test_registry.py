import copy

import pytest
import yaml

from pipeline.sources.registry import (
    POKEAPI_ALLOWED_RESOURCES,
    REQUIRED_SOURCE_IDS,
    SOURCES_DIR,
    RegistryError,
    load_raw,
    load_registry,
    validate,
)


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.fixture
def raw():
    return copy.deepcopy(load_raw())


def _source(data, source_id):
    return next(s for s in data["sources"] if s["id"] == source_id)


def test_registry_is_valid_and_covers_rule_03(registry):
    assert set(registry.ids) >= REQUIRED_SOURCE_IDS


def test_every_source_declares_license_and_attribution(registry):
    for source in registry.sources:
        assert source.license["url"].startswith("https://"), source.id
        assert source.attribution, source.id


def test_pokeapi_only_requests_factual_resources(registry):
    assert set(registry.get("pokeapi").params["resources"]) <= POKEAPI_ALLOWED_RESOURCES


def test_overpass_queries_never_use_area(registry):
    selectors = [
        selector
        for category in registry.get("osm_overpass").params["categories"]
        for selector in category["selectors"]
    ] + registry.get("osm_buildings").params["selectors"]
    assert selectors
    assert not any("area" in selector for selector in selectors)


def test_overpass_snapshot_is_open_during_development(registry):
    # La fecha se fija solo para la corrida final de publicación.
    assert registry.overpass["snapshot_date"] is None


# Puntos que tienen que caer en alguna bbox: extremos y huecos posibles entre bboxes.
JAPAN_CHECKPOINTS = {
    "Tokio": (35.68, 139.77),
    "Sapporo": (43.06, 141.35),
    "Wakkanai": (45.42, 141.67),
    "Nemuro": (43.33, 145.58),
    "isla de Sado": (38.05, 138.40),
    "islas Oki": (36.20, 133.30),
    "cabo Shionomisaki (Kii)": (33.43, 135.76),
    "sur de Mie": (34.00, 136.70),
    "costa de Fukushima": (37.40, 141.03),
    "Fukuoka": (33.59, 130.40),
    "Yakushima": (30.35, 130.50),
    "Naha": (26.21, 127.68),
    "Yonaguni": (24.47, 123.00),
    "Hachijōjima": (33.11, 139.79),
    "Chichijima": (27.09, 142.19),
}


@pytest.mark.parametrize("place", sorted(JAPAN_CHECKPOINTS))
def test_japan_bboxes_have_no_gaps(registry, place):
    lat, lon = JAPAN_CHECKPOINTS[place]
    assert any(
        south <= lat <= north and west <= lon <= east
        for south, west, north, east in registry.japan_bboxes.values()
    ), place


def test_wikidata_query_files_are_select_queries(registry):
    for query in registry.get("wikidata").params["queries"]:
        text = (SOURCES_DIR / query["file"]).read_text(encoding="utf-8")
        assert "SELECT" in text, query["id"]


def test_mega_tokyo_center_matches_decision_d(registry):
    params = registry.get("osm_buildings").params
    assert params["center"]["osm"] == "node/3350332481"
    assert params["radius_m"] == 500


def _break_duplicate_id(data):
    data["sources"].append(copy.deepcopy(data["sources"][0]))


def _break_unknown_kind(data):
    data["sources"][0]["kind"] = "ftp"


def _break_license_url(data):
    del data["sources"][0]["license"]["url"]


def _break_pokeapi_sprites(data):
    _source(data, "pokeapi")["params"]["resources"].append("pokemon")


def _break_overpass_area(data):
    category = _source(data, "osm_overpass")["params"]["categories"][0]
    category["selectors"] = ['nwr(area.jp)["brand"="ポケモンセンター"]']


def _break_unknown_bbox_name(data):
    _source(data, "osm_overpass")["params"]["categories"][0]["bboxes"] = ["mars"]


def _break_inverted_bbox(data):
    data["japan_bboxes"]["hokkaido"] = [139.3, 41.3, 145.9, 45.6]


def _break_snapshot_date(data):
    data["overpass"]["snapshot_date"] = "31/10/2026"


def _break_missing_source(data):
    data["sources"] = [s for s in data["sources"] if s["id"] != "seeds"]


def _break_seed_without_source_url(data):
    _source(data, "seeds")["params"]["files"][0]["required_columns"].remove("source_url")


def _break_big_radius(data):
    _source(data, "osm_buildings")["params"]["radius_m"] = 50_000


def _break_missing_query_file(data):
    _source(data, "wikidata")["params"]["queries"][0]["file"] = "queries/no_existe.rq"


def _break_user_agent(data):
    data["user_agent"] = "python-requests"


@pytest.mark.parametrize(
    "breaker",
    [
        _break_duplicate_id,
        _break_unknown_kind,
        _break_license_url,
        _break_pokeapi_sprites,
        _break_overpass_area,
        _break_unknown_bbox_name,
        _break_inverted_bbox,
        _break_snapshot_date,
        _break_missing_source,
        _break_seed_without_source_url,
        _break_big_radius,
        _break_missing_query_file,
        _break_user_agent,
    ],
)
def test_validate_rejects_broken_registry(raw, breaker):
    breaker(raw)
    assert validate(raw, base_dir=SOURCES_DIR)


def test_fixed_snapshot_date_is_valid(raw):
    raw["overpass"]["snapshot_date"] = "2026-10-31T00:00:00Z"
    assert validate(raw, base_dir=SOURCES_DIR) == []


def test_load_registry_raises_with_all_errors(tmp_path, raw):
    _break_unknown_kind(raw)
    _break_user_agent(raw)
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        load_registry(path)
    message = str(excinfo.value)
    assert "kind desconocido" in message
    assert "user_agent" in message
