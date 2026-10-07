"""Cobertura del registro y controles de las fuentes sin red."""

import pytest

from pipeline.sources import seeds
from pipeline.sources.base import INFRA_MODULES, BronzeRun, source_module
from pipeline.sources.registry import SOURCES_DIR

RUN_1 = "20261007T100000Z"


def _source_module_names():
    return {
        path.stem
        for path in SOURCES_DIR.glob("*.py")
        if path.stem not in INFRA_MODULES and not path.stem.startswith("_")
    }


def test_every_registered_source_has_a_module(registry):
    for source_id in registry.ids:
        assert callable(getattr(source_module(source_id), "ingest", None)), source_id


def test_no_module_without_a_registry_entry(registry):
    assert _source_module_names() == set(registry.ids)


# Seeds -----------------------------------------------------------------------

COLUMNS = [
    "region_id",
    "game_name",
    "real_region",
    "prefecture_code",
    "generation",
    "year",
    "confidence",
    "source_url",
]
HEADER = ",".join(COLUMNS) + "\n"
GOOD_ROW = "kanto,Kanto,Kantō,JP-13,1,1996,ampliamente aceptada,https://www.wikidata.org/wiki/Q1657833#P144\n"


def test_repo_seed_is_valid(registry):
    params = registry.get("seeds").params
    for item in params["files"]:
        data = (seeds.PIPELINE_DIR / params["dir"] / item["file"]).read_bytes()
        assert seeds.validate_seed(data, item["required_columns"]) == [], item["name"]


def test_game_places_are_in_japan_and_in_a_known_region(registry):
    import csv

    from pipeline.sources.registry import JAPAN_EXTENT

    regions = {"kanto", "johto", "hoenn", "sinnoh"}
    path = seeds.PIPELINE_DIR / "seeds" / "game_places.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows
    south, west, north, east = JAPAN_EXTENT
    for row in rows:
        assert row["region_id"] in regions, row["place_id"]
        assert south <= float(row["lat"]) <= north and west <= float(row["lon"]) <= east
        assert row["real_place_wikidata"].startswith("Q")
        assert row["confidence"] in seeds.CONFIDENCE
    # Ninguna fila cita wikis de fans; las de prensa nunca pasan de "ampliamente aceptada".
    press = ("thegamer.com", "gamerant.com", "cbr.com")
    for row in rows:
        if row["source_url"].split("/")[2].removeprefix("www.") in press:
            assert row["confidence"] != "oficial", row["place_id"]


def test_repo_seed_covers_the_four_japanese_regions(registry):
    data = (seeds.PIPELINE_DIR / "seeds" / "game_regions.csv").read_text(encoding="utf-8")
    regions = {line.split(",")[0] for line in data.splitlines()[1:]}
    assert regions == {"kanto", "johto", "hoenn", "sinnoh"}


@pytest.mark.parametrize(
    ("row", "error"),
    [
        (GOOD_ROW.replace("https://www.wikidata.org", "http://www.wikidata.org"), "https"),
        (
            GOOD_ROW.replace(
                "www.wikidata.org/wiki/Q1657833", "bulbapedia.bulbagarden.net/wiki/Kanto"
            ),
            "Bulbapedia",
        ),
        (GOOD_ROW.replace("ampliamente aceptada", "segurísimo"), "confidence"),
        (GOOD_ROW.replace("JP-13", ""), "vacías"),
    ],
)
def test_bad_seed_rows_are_rejected(row, error):
    errors = seeds.validate_seed((HEADER + row).encode(), COLUMNS)
    assert any(error in e for e in errors), errors


def test_seed_without_rows_or_columns_is_rejected():
    assert seeds.validate_seed(HEADER.encode(), COLUMNS)
    assert seeds.validate_seed(b"region_id\nkanto\n", COLUMNS)


def test_seeds_ingest_copies_the_csv(registry, tmp_path):
    run = BronzeRun(registry, registry.get("seeds"), RUN_1, tmp_path)
    seeds.ingest(run)
    summary = run.finish()
    assert summary["files"] == len(registry.get("seeds").params["files"])
    assert (run.dir / "game_regions.csv").read_bytes() == (
        seeds.PIPELINE_DIR / "seeds" / "game_regions.csv"
    ).read_bytes()


# PokeAPI ---------------------------------------------------------------------


def test_pokeapi_rejects_responses_with_images(tmp_path):
    from pipeline.sources import pokeapi
    from pipeline.sources.base import IngestError

    part = tmp_path / "x.json.part"
    part.write_bytes(b'{"sprites": {"front_default": "https://x/1.png"}}')
    with pytest.raises(IngestError, match="imágenes"):
        pokeapi._no_images(part, None)


def test_other_sources_follow_the_same_rules():
    header = HEADER.rstrip("\n") + ",other_sources\n"
    row = GOOD_ROW.rstrip("\n") + ",https://bulbapedia.bulbagarden.net/wiki/Kanto\n"
    errors = seeds.validate_seed((header + row).encode(), COLUMNS)
    assert any("Bulbapedia" in e for e in errors), errors


GROUPED_HEADER = HEADER.rstrip("\n") + ",other_sources,source_groups\n"
TG = "https://www.thegamer.com/x/"
GR = "https://gamerant.com/y/"
WD = "https://www.wikidata.org/wiki/Q1#P144"


def _grouped_row(confidence, source, others, groups):
    row = GOOD_ROW.replace("ampliamente aceptada", confidence)
    row = row.replace("https://www.wikidata.org/wiki/Q1657833#P144", source)
    return row.rstrip("\n") + f",{others},{groups}\n"


def test_publisher_groups():
    assert seeds.publisher_group(TG) == seeds.publisher_group(GR) == "valnet"
    assert (
        seeds.publisher_group("https://web.archive.org/web/2019/https://www.pokemon.com/x")
        == "oficial"
    )
    assert seeds.publisher_group("https://example.com/") is None


@pytest.mark.parametrize(
    ("row", "error"),
    [
        # Dos medios de Valnet son un solo grupo.
        (_grouped_row("ampliamente aceptada", TG, GR, "valnet"), "dos grupos"),
        (_grouped_row("ampliamente aceptada", TG, WD, "valnet"), "no coincide"),
        (
            _grouped_row("teoría de fans", "https://example.com/a", "", "otro"),
            "sin grupo editorial",
        ),
    ],
)
def test_publisher_group_rule(row, error):
    errors = seeds.validate_seed((GROUPED_HEADER + row).encode(), COLUMNS)
    assert any(error in e for e in errors), errors


def test_publisher_group_rule_accepts_two_groups():
    row = _grouped_row("ampliamente aceptada", TG, WD, "valnet wikidata")
    assert seeds.validate_seed((GROUPED_HEADER + row).encode(), COLUMNS) == []


def test_repo_game_places_follow_the_group_rule():
    import csv

    path = seeds.PIPELINE_DIR / "seeds" / "game_places.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for row in rows:
        if row["confidence"] == "ampliamente aceptada":
            assert len(row["source_groups"].split()) >= 2, row["place_id"]


def test_pokemon_cafes_seed_has_both_cafes_with_official_source():
    import csv

    path = seeds.PIPELINE_DIR / "seeds" / "pokemon_cafes.csv"
    rows = {r["cafe_id"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}
    assert set(rows) == {"pokemon_cafe_tokyo", "pokemon_cafe_osaka"}
    for row in rows.values():
        assert row["source_url"].startswith("https://shop.pokemon.co.jp/")
        assert row["confidence"] == "oficial"
        assert row["coords_osm"].startswith("osm:node/")
