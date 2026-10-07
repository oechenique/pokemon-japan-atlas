"""Silver vectorial: poi, rail, station y building sobre respuestas de Overpass sintéticas."""

import json

import pytest

from pipeline.sources.base import METADATA
from pipeline.transforms import base as tbase
from pipeline.transforms.base import Bronze, connect, write_entity
from pipeline.transforms.silver import building, poi, rail, station

RUN = "20261007T100000Z"


def _write_bronze(root, source, files):
    run_dir = root / "bronze" / source / f"run_id={RUN}"
    for rel, content in files.items():
        path = run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            content if isinstance(content, str) else json.dumps(content), encoding="utf-8"
        )
    meta = {"files": [{"path": rel} for rel in files]}
    (run_dir / METADATA).write_text(json.dumps(meta), encoding="utf-8")


def _overpass(*elements):
    return {"version": 0.6, "elements": list(elements)}


def _node(id_, lat, lon, **tags):
    return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags}


def _way_center(id_, lat, lon, **tags):
    return {"type": "way", "id": id_, "center": {"lat": lat, "lon": lon}, "tags": tags}


def _way_geom(id_, coords, **tags):
    return {
        "type": "way",
        "id": id_,
        "geometry": [{"lat": la, "lon": lo} for la, lo in coords],
        "tags": tags,
    }


@pytest.fixture
def con():
    connection = connect()
    yield connection
    connection.close()


@pytest.fixture
def silver_base(tmp_path, con):
    """prefecture con dos cuadrados (JP-13 Kanto, JP-27 Kinki) y game_region de ambas."""
    write_entity(
        con,
        "prefecture",
        """
        SELECT * FROM (VALUES
          ('JP-13', '東京都', 'Tokyo', 'Tokio', 'Kanto', 'natural_earth', 'Q1490', 10000.0,
           'public-domain', ST_Multi(ST_GeomFromText('POLYGON((139 35, 140 35, 140 36, 139 36, 139 35))'))),
          ('JP-27', '大阪府', 'Osaka', NULL, 'Kinki', 'natural_earth', 'Q122723', 10000.0,
           'public-domain', ST_Multi(ST_GeomFromText('POLYGON((135 34, 136 34, 136 35, 135 35, 135 34))')))
        ) AS t(prefecture_code, name_ja, name_en, name_es, real_region, real_region_source,
               wikidata, area_km2, license, geometry)
    """,
        root=tmp_path,
    )
    write_entity(
        con,
        "game_region",
        """
        SELECT * FROM (VALUES
          ('kanto', 'Kanto', 'カントー地方', 'Kanto', 'Kanto', 'Kantō', 1, 1996, 'oficial',
           ['JP-13'], ['https://a'], 'x', ST_Multi(ST_GeomFromText('POLYGON((139 35, 140 35, 140 36, 139 36, 139 35))'))),
          ('johto', 'Johto', 'ジョウト地方', 'Johto', 'Johto', 'Kansai', 2, 1999, 'oficial',
           ['JP-27'], ['https://a'], 'x', ST_Multi(ST_GeomFromText('POLYGON((135 34, 136 34, 136 35, 135 35, 135 34))')))
        ) AS t(region_id, game_name, name_ja, name_en, name_es, real_region, generation, year,
               confidence, prefecture_codes, source_urls, license, geometry)
    """,
        root=tmp_path,
    )
    return tmp_path


def _poi_bronze(root):
    center = _node(1, 35.5, 139.5, name="ポケモンセンタートウキョーDX", brand="ポケモンセンター")
    _write_bronze(
        root,
        "osm_overpass",
        {
            # El mismo Center en dos bbox que se solapan.
            "pokemon_center/kanto_chubu.json": _overpass(
                center,
                # Tienda con el brand:wikidata de Center: tiene que quedar como store.
                _node(
                    2,
                    35.6,
                    139.6,
                    name="ポケモンストア 東京駅店",
                    **{"brand:wikidata": "Q89673816"},
                ),
            ),
            "pokemon_center/tohoku.json": _overpass(center),
            "pokemon_store/kanto_chubu.json": _overpass(),
            # El café de OSM que el seed reemplaza.
            "pokemon_cafe/kanto_chubu.json": _overpass(
                _node(3, 35.68, 139.77, name="ポケモンカフェ")
            ),
            "poke_lids/kanto_chubu.json": _overpass(),
            # Un onsen al mar a ~2 km de la costa (nearest) y otro lejos (sin prefectura).
            "onsen/kanto_chubu.json": _overpass(
                _node(4, 35.5, 140.02, name="海の湯"), _node(5, 30.0, 130.0, name="遠い湯")
            ),
            "power_plant/kanto_chubu.json": _overpass(
                _way_center(6, 34.5, 135.5, name="発電所", **{"plant:source": "solar"})
            ),
        },
    )
    _write_bronze(
        root,
        "seeds",
        {
            "pokemon_cafes.csv": (
                "cafe_id,name_ja,name_en,address_ja,prefecture_code,lat,lon,coords_osm,confidence,source_url\n"
                "pokemon_cafe_tokyo,ポケモンカフェ TOKYO,Pokémon Café TOKYO,東京都中央区,JP-13,35.68,139.77,"
                "osm:node/3,oficial,https://shop.pokemon.co.jp/ja/shop/pokemoncafe-tokyo/\n"
            )
        },
    )


def test_poi_dedupes_reclassifies_and_assigns_prefecture(silver_base, con):
    _poi_bronze(silver_base)
    summary = poi.build(con, Bronze(RUN, silver_base), root=silver_base)
    stats = summary["stats"]
    assert stats["osm_duplicates_overlapping_bboxes"] == 1
    assert stats["reclassified_by_name"] == 1
    assert stats["seed_cafes_replacing_osm"] == 1
    assert (stats["prefecture_within"], stats["prefecture_nearest"], stats["prefecture_none"]) == (
        4,
        1,
        1,
    )
    path = tbase.silver_path("poi", silver_base).as_posix()
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT poi_id, category, prefecture_code, prefecture_method, game_region, plant_source, "
            f"license, address_ja FROM '{path}'"
        ).fetchall()
    }
    assert set(rows) == {
        "osm:node/1",
        "osm:node/2",
        "seed:pokemon_cafe_tokyo",
        "osm:node/4",
        "osm:node/5",
        "osm:way/6",
    }
    assert rows["osm:node/2"][0] == "pokemon_store"
    assert rows["osm:node/4"][1:3] == ("JP-13", "nearest")
    assert rows["osm:node/5"][1:4] == (None, None, None)
    assert rows["osm:way/6"][1:5] == ("JP-27", "within", "johto", "solar")
    assert rows["seed:pokemon_cafe_tokyo"][0] == "pokemon_cafe"
    assert rows["seed:pokemon_cafe_tokyo"][6] == "東京都中央区"
    assert rows["seed:pokemon_cafe_tokyo"][5].startswith("LicenseRef-seeds")


def test_rail_keeps_shinkansen_over_the_kanto_network(tmp_path, con):
    line = [(35.0, 139.0), (35.0, 139.1)]
    _write_bronze(
        tmp_path,
        "osm_overpass",
        {
            "shinkansen/kanto_chubu.json": _overpass(
                _way_geom(10, line, name="東海道新幹線", highspeed="yes")
            ),
            "shinkansen/tohoku.json": _overpass(
                _way_geom(10, line, name="東海道新幹線", highspeed="yes")
            ),
            "rail_kanto/kanto_chubu.json": _overpass(
                _way_geom(10, line, name="東海道新幹線"),
                _way_geom(11, [(35.1, 139.0), (35.1, 139.2)], operator="JR東日本"),
            ),
        },
    )
    summary = rail.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    assert summary["rows"] == 2
    assert summary["stats"]["osm_duplicates_across_categories"] == 1
    path = tbase.silver_path("rail", tmp_path).as_posix()
    rows = dict(con.execute(f"SELECT rail_id, kind FROM '{path}'").fetchall())
    assert rows == {"osm:way/10": "shinkansen", "osm:way/11": "line"}
    # 0,1° de longitud a 35° N son unos 9,1 km.
    length = con.execute(f"SELECT length_m FROM '{path}' WHERE rail_id = 'osm:way/10'").fetchone()[
        0
    ]
    assert 9_000 < length < 9_300


def test_station_lines_only_when_tagged(silver_base, con):
    _write_bronze(
        silver_base,
        "osm_overpass",
        {
            "station/kanto_chubu.json": _overpass(
                _node(
                    20, 35.68, 139.76, name="東京", **{"name:en": "Tokyo", "line": "山手線; 中央線"}
                ),
                _node(21, 35.69, 139.70, name="新宿"),
            )
        },
    )
    summary = station.build(con, Bronze(RUN, silver_base), root=silver_base)
    assert summary["rows"] == 2
    path = tbase.silver_path("station", silver_base).as_posix()
    rows = dict(con.execute(f"SELECT station_id, lines FROM '{path}'").fetchall())
    assert rows == {"osm:node/20": ["山手線", "中央線"], "osm:node/21": None}


def test_building_ways_and_multipolygon_with_hole(tmp_path, con):
    square = [(35.0, 139.0), (35.0, 139.001), (35.001, 139.001), (35.001, 139.0), (35.0, 139.0)]
    hole = [
        (35.0004, 139.0004),
        (35.0004, 139.0006),
        (35.0006, 139.0006),
        (35.0006, 139.0004),
        (35.0004, 139.0004),
    ]
    relation = {
        "type": "relation",
        "id": 30,
        "tags": {"building": "apartments", "height": "187", "building:levels": "52"},
        "members": [
            {
                "type": "way",
                "ref": 1,
                "role": "outer",
                "geometry": [{"lat": a, "lon": b} for a, b in square],
            },
            {
                "type": "way",
                "ref": 2,
                "role": "inner",
                "geometry": [{"lat": a, "lon": b} for a, b in hole],
            },
        ],
    }
    open_way = _way_geom(32, square[:3], building="yes")
    _write_bronze(
        tmp_path,
        "osm_buildings",
        {
            "buildings.json": _overpass(
                _way_geom(31, square, building="yes", height="12 m"), relation, open_way
            )
        },
    )
    summary = building.build(con, Bronze(RUN, tmp_path), root=tmp_path)
    assert summary["rows"] == 2
    assert summary["stats"]["buildings_dropped_invalid"] == 1
    path = tbase.silver_path("building", tmp_path).as_posix()
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT building_id, height_m, levels, ST_Area_Spheroid(ST_FlipCoordinates(geometry)) FROM '{path}'"
        ).fetchall()
    }
    assert rows["osm:way/31"][0] == 12.0
    assert rows["osm:relation/30"][:2] == (187.0, 52)
    assert rows["osm:relation/30"][2] < 0.97 * rows["osm:way/31"][2]
