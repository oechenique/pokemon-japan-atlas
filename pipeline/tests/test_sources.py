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
    assert summary["files"] == 1
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
