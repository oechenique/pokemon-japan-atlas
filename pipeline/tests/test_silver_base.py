"""Silver base: prefecture, game_region, game_place y outside_region sobre un Bronze
sintético chico (los datos reales se prueban en atlas_run y en el DQ gate)."""

import json
import zipfile

import pytest

from pipeline.sources.base import METADATA
from pipeline.transforms import base as tbase
from pipeline.transforms.base import Bronze, TransformError, connect, sparql_rows, write_entity
from pipeline.transforms.silver import game_place, game_region, outside_region, prefecture

RUN = "20261007T100000Z"
SEEDS_DIR = tbase.Path(__file__).resolve().parents[1] / "seeds"


def _bronze(root, source, files):
    run_dir = root / "bronze" / source / f"run_id={RUN}"
    for rel, content in files.items():
        path = run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(
                content if isinstance(content, str) else json.dumps(content), encoding="utf-8"
            )
    (run_dir / METADATA).write_text("{}", encoding="utf-8")
    return run_dir


def _sparql(rows):
    bindings = []
    for row in rows:
        binding = {}
        for key, value in row.items():
            if value is None:
                continue
            kind = "uri" if str(value).startswith("Q") else "literal"
            text = f"http://www.wikidata.org/entity/{value}" if kind == "uri" else str(value)
            binding[key] = {"type": kind, "value": text}
        bindings.append(binding)
    return {"head": {"vars": []}, "results": {"bindings": bindings}}


def _square(west, south, size=1.0):
    e, n = west + size, south + size
    return {
        "type": "Polygon",
        "coordinates": [[[west, south], [e, south], [e, n], [west, n], [west, south]]],
    }


@pytest.fixture
def con():
    connection = connect()
    yield connection
    connection.close()


def test_sparql_rows_turns_entity_uris_into_qids_and_missing_into_null():
    data = _sparql([{"region": "Q1657833", "name_en": "Kanto"}])
    assert sparql_rows(data, ("region", "name_en", "name_es")) == [("Q1657833", "Kanto", None)]


def test_bronze_only_reads_complete_sources(tmp_path):
    (tmp_path / "bronze" / "seeds" / f"run_id={RUN}").mkdir(parents=True)
    with pytest.raises(TransformError, match="incompleto"):
        Bronze(RUN, tmp_path).path("seeds", "game_places.csv")


def test_game_place_from_repo_seed_is_deterministic(tmp_path, con):
    seed = (SEEDS_DIR / "game_places.csv").read_text(encoding="utf-8")
    _bronze(tmp_path, "seeds", {"game_places.csv": seed})
    first = game_place.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    again = game_place.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    assert first["rows"] == len(seed.strip().splitlines()) - 1
    assert first["sha256"] == again["sha256"]
    path = tbase.silver_path("game_place", tmp_path).as_posix()
    cells = con.execute(
        f"SELECT min(length(h3_r9)), count(*) FILTER (WHERE len(other_sources) > 0) FROM '{path}'"
    ).fetchone()
    assert cells[0] == 15 and cells[1] > 0


def test_write_entity_rejects_a_query_without_the_contract_columns(tmp_path, con):
    with pytest.raises(Exception, match="(?i)place_id|binder|not found"):
        write_entity(con, "game_place", "SELECT 1 AS x", root=tmp_path)
    assert not tbase.silver_path("game_place", tmp_path).exists()


def _prefecture_inputs(root, monkeypatch):
    monkeypatch.setattr(prefecture, "NE_ADMIN1", ("admin1.zip", "admin1.geojson"))
    features = []
    for code, region, west in [
        ("JP-13", "Kanto", 139.0),
        ("JP-27", "Kinki", 135.0),
        ("JP-41", None, 130.0),
    ]:
        props = {
            "iso_3166_2": code,
            "name": code,
            "name_ja": code,
            "region": region,
            "wikidataid": "Q1",
            "adm0_a3": "JPN",
        }
        features.append({"type": "Feature", "properties": props, "geometry": _square(west, 35.0)})
    geojson = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    archive = root / "admin1.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("admin1.geojson", geojson)
    _bronze(root, "natural_earth", {"admin1.zip": archive.read_bytes()})
    _bronze(
        root,
        "wikidata",
        {
            "prefectures.json": _sparql(
                [
                    {
                        "prefecture": "Q1490",
                        "iso": "JP-13",
                        "name_ja": "東京都",
                        "name_en": "Tokyo",
                        "name_es": "Tokio",
                    },
                    {
                        "prefecture": "Q122723",
                        "iso": "JP-27",
                        "name_ja": "大阪府",
                        "name_en": "Osaka",
                    },
                ]
            ),
            "game_regions.json": _sparql(
                [
                    {
                        "region": "Q1657833",
                        "name_ja": "カントー地方",
                        "name_en": "Kanto",
                        "name_es": "Kanto",
                    },
                    {
                        "region": "Q607459",
                        "name_ja": "ジョウト地方",
                        "name_en": "Johto",
                        "name_es": "Johto",
                    },
                ]
            ),
        },
    )


def test_prefecture_fills_names_region_and_area(tmp_path, con, monkeypatch):
    _prefecture_inputs(tmp_path, monkeypatch)
    _bronze(
        tmp_path,
        "seeds",
        {
            "prefecture_regions.csv": "prefecture_code,real_region,source_url\nJP-41,Kyushu,https://x\n"
        },
    )
    summary = prefecture.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    assert summary["rows"] == 3
    path = tbase.silver_path("prefecture", tmp_path).as_posix()
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT prefecture_code, name_en, name_es, real_region, real_region_source, area_km2, "
            f"ST_GeometryType(geometry) FROM '{path}'"
        ).fetchall()
    }
    assert rows["JP-13"][:4] == ("Tokyo", "Tokio", "Kanto", "natural_earth")
    assert rows["JP-41"][2:4] == ("Kyushu", "seed")
    # Un cuadrado de 1° a 35° N mide unos 111 km × 91 km.
    assert 9_500 < rows["JP-13"][4] < 10_500
    assert rows["JP-13"][5] == "MULTIPOLYGON"


def test_game_region_unions_prefectures_and_keeps_the_lowest_confidence(tmp_path, con, monkeypatch):
    _prefecture_inputs(tmp_path, monkeypatch)
    _bronze(
        tmp_path,
        "seeds",
        {
            "prefecture_regions.csv": "prefecture_code,real_region,source_url\nJP-41,Kyushu,https://x\n",
            "game_regions.csv": (
                "region_id,game_name,real_region,prefecture_code,generation,year,confidence,source_url\n"
                "kanto,Kanto,Kantō,JP-13,1,1996,oficial,https://a\n"
                "johto,Johto,Kansai,JP-27,2,1999,oficial,https://a\n"
                "johto,Johto,Chūbu (Tōkai),JP-41,2,1999,ampliamente aceptada,https://b\n"
            ),
        },
    )
    prefecture.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    summary = game_region.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    assert summary["rows"] == 2
    path = tbase.silver_path("game_region", tmp_path).as_posix()
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT region_id, confidence, prefecture_codes, source_urls, name_ja, real_region, "
            f"ST_Area_Spheroid(ST_FlipCoordinates(geometry)) / 1e6 FROM '{path}'"
        ).fetchall()
    }
    assert rows["kanto"][0] == "oficial"
    assert rows["johto"][0] == "ampliamente aceptada"
    assert rows["johto"][1] == ["JP-27", "JP-41"]
    assert rows["johto"][2] == ["https://a", "https://b"]
    assert rows["johto"][3] == "ジョウト地方"
    assert rows["johto"][4] == "Chūbu (Tōkai) + Kansai"
    assert rows["johto"][5] > 1.9 * rows["kanto"][5]


def test_outside_region_mixes_wikidata_and_seed(tmp_path, con):
    regions = {"unova": "v", "kalos": "vi", "alola": "vii", "galar": "viii", "paldea": "ix"}
    _bronze(
        tmp_path,
        "pokeapi",
        {
            f"region/{name}.json": {"main_generation": {"name": f"generation-{numeral}"}}
            for name, numeral in regions.items()
        },
    )
    _bronze(
        tmp_path,
        "wikidata",
        {
            "game_regions.json": _sparql(
                [
                    {"region": "Q4843341", "name_en": "Unova"},
                    {"region": "Q15132899", "name_en": "Kalos"},
                    {"region": "Q25594375", "name_en": "Alola"},
                    {"region": "Q61951161", "name_en": "Galar"},
                ]
            ),
            "game_regions_based_on.json": _sparql(
                [
                    {
                        "region": "Q4843341",
                        "based_on": "Q683705",
                        "based_on_en": "New York",
                        "coord": "Point(-74.02 40.81)",
                    },
                    {
                        "region": "Q15132899",
                        "based_on": "Q212429",
                        "based_on_en": "France",
                        "based_on_es": "Francia",
                        "coord": "Point(2.0 46.0)",
                    },
                    {
                        "region": "Q25594375",
                        "based_on": "Q782",
                        "based_on_en": "Hawaii",
                        "coord": "Point(-158.0 21.5)",
                    },
                ]
            ),
            "generation_games.json": _sparql(
                [
                    {"generation": 5, "game": "Q816034", "first_release": "2010-09-18T00:00:00Z"},
                    {"generation": 6, "game": "Q2769164", "first_release": "2013-10-12T00:00:00Z"},
                    {"generation": 7, "game": "Q22954794", "first_release": "2016-11-18T00:00:00Z"},
                    {"generation": 8, "game": "Q61897498", "first_release": "2019-11-15T00:00:00Z"},
                    {
                        "generation": 9,
                        "game": "Q111028839",
                        "first_release": "2022-11-18T00:00:00Z",
                    },
                ]
            ),
        },
    )
    # Sin Alola en el seed: tiene que entrar por el respaldo de Wikidata P144.
    seed_lines = (SEEDS_DIR / "regions_outside_japan.csv").read_text(encoding="utf-8").splitlines()
    seed = "\n".join(line for line in seed_lines if not line.startswith("alola,")) + "\n"
    _bronze(tmp_path, "seeds", {"regions_outside_japan.csv": seed})
    summary = outside_region.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    assert summary["rows"] == 5
    path = tbase.silver_path("outside_region", tmp_path).as_posix()
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT region_id, generation, year, confidence, real_place, ST_X(geometry) "
            f"FROM '{path}'"
        ).fetchall()
    }
    assert rows["galar"][:3] == (8, 2019, "oficial")
    # El seed tiene las 5 con su fuente; Wikidata P144 queda de respaldo.
    assert rows["unova"][:3] == (5, 2010, "oficial")
    assert rows["paldea"][2] == "ampliamente aceptada"
    assert rows["kalos"][3] == "Francia metropolitana"
    assert rows["alola"][2] == "teoría de fans"
    assert rows["alola"][3] == "Hawaii"
    assert rows["alola"][4] == -158.0
