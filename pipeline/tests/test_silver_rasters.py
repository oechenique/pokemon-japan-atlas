"""Paso 5: relieve sombreado, cuenca visual (gdal_viewshed) y métricas H3."""

import gzip
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from pipeline.sources.base import METADATA
from pipeline.transforms import base as tbase
from pipeline.transforms import rasters
from pipeline.transforms.base import Bronze, connect, write_entity
from pipeline.transforms.silver import h3_metric

RUN = "20261007T100000Z"


def _write_tif(path, array, transform, crs, nodata=None):
    profile = {
        "driver": "GTiff",
        "dtype": array.dtype.name,
        "count": 1,
        "width": array.shape[1],
        "height": array.shape[0],
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as out:
        out.write(array, 1)


# Relieve sombreado ----------------------------------------------------------------


def test_hillshade_lights_slopes_facing_northwest():
    rows = np.arange(60, dtype="float64")[:, None]
    cols = np.arange(60, dtype="float64")[None, :]
    # Rampa que sube hacia el sureste (cara al noroeste) y su opuesta.
    facing_nw = (rows + cols) * 5.0
    facing_se = -(rows + cols) * 5.0
    lat = np.full(60, 35.0)
    kwargs = {"res_x_deg": 1 / 1200, "res_y_deg": 1 / 1200, "lat_center": lat, "nodata": None}
    bright = rasters.hillshade(facing_nw, **kwargs)[10:50, 10:50].mean()
    dark = rasters.hillshade(facing_se, **kwargs)[10:50, 10:50].mean()
    flat = rasters.hillshade(np.zeros((10, 10)), **{**kwargs, "lat_center": np.full(10, 35.0)})
    assert bright > dark + 20
    # Plano: cos(45°) → 1 + 254 × 0,707 ≈ 181.
    assert abs(int(flat[5, 5]) - 181) <= 1


def test_hillshade_marks_nodata_as_zero():
    dem = np.full((5, 5), 100.0)
    dem[2, 2] = -32767.0
    out = rasters.hillshade(
        dem, res_x_deg=1 / 1200, res_y_deg=1 / 1200, lat_center=np.full(5, 35.0), nodata=-32767.0
    )
    assert out[2, 2] == rasters.HILLSHADE_NODATA and out.dtype == np.uint8


# gdal_viewshed: caso chico de resultado conocido ------------------------------------


def test_gdal_viewshed_wall_hides_what_is_behind(tmp_path):
    """Llanura en UTM con un muro de 50 m: lo de detrás del muro no se ve."""
    dem = np.zeros((100, 100), dtype="float32")
    dem[:, 50] = 50.0  # muro norte-sur en la columna 50
    transform = from_origin(500_000, 4_000_000, 10, 10)
    src = tmp_path / "dem.tif"
    _write_tif(src, dem, transform, "EPSG:32654")
    out = tmp_path / "vs.tif"
    # Observador a ras del suelo en la columna 10, fila 50.
    rasters.run_viewshed(
        src,
        out,
        x=500_000 + 10 * 10 + 5,
        y=4_000_000 - 50 * 10 - 5,
        max_distance_m=5_000,
        observer_height_m=1.7,
        target_height_m=1.7,
    )
    with rasterio.open(out) as ds:
        vs = ds.read(1)
        r_front, c_front = ds.index(500_000 + 30 * 10 + 5, 4_000_000 - 50 * 10 - 5)
        r_back, c_back = ds.index(500_000 + 80 * 10 + 5, 4_000_000 - 50 * 10 - 5)
    assert vs[r_front, c_front] == 255
    assert vs[r_back, c_back] == 0


def test_highest_point_finds_the_summit_near_the_given_point(tmp_path):
    dem = np.zeros((50, 50), dtype="float32")
    dem[20, 23] = 3776.0
    transform = from_origin(0, 500, 10, 10)
    src = tmp_path / "dem.tif"
    _write_tif(src, dem, transform, "EPSG:32654")
    x, y, z = rasters.highest_point(src, 200.0, 300.0, radius_m=100)
    assert (x, y, z) == (235.0, 295.0, 3776.0)


def test_viewshed_ring_sees_down_a_flat_topped_mountain(tmp_path):
    """Meseta alta y plana: desde el centro no se ve el pie; con el anillo, sí."""
    size = 120
    rows, cols = np.indices((size, size))
    dist = np.hypot(rows - size / 2, cols - size / 2) * (1 / 1200)  # en grados
    # Cono de 3000 m con la cima recortada en una meseta de radio ~0,0125° (≈1,1 km).
    dem = np.clip(3000 - dist * 60_000, 0, 2250).astype("float32")
    transform = from_origin(138.70, 35.40, 1 / 1200, 1 / 1200)
    src = tmp_path / "dem.tif"
    _write_tif(src, dem, transform, "EPSG:4326")
    center_lon = 138.70 + (size / 2) / 1200
    center_lat = 35.40 - (size / 2) / 1200
    common = dict(
        lon=center_lon,
        lat=center_lat,
        max_distance_m=20_000,
        observer_height_m=1.7,
        target_height_m=1.7,
        utm_epsg=32654,
        resolution_m=90,
        summit_search_m=50,
    )
    single = rasters.viewshed(src, tmp_path / "single.tif", **common)
    ring = rasters.viewshed(src, tmp_path / "ring.tif", ring_radius_m=1500, ring_points=8, **common)
    assert ring["observers"] == 9
    assert ring["visible_share"] > single["visible_share"] + 0.2


# h3_metric -----------------------------------------------------------------------


def _bronze(root, source, files):
    run_dir = root / "bronze" / source / f"run_id={RUN}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (run_dir / rel).write_bytes(content)
    (run_dir / METADATA).write_text("{}", encoding="utf-8")
    return run_dir


@pytest.fixture
def h3_inputs(tmp_path):
    con = connect()
    square = "POLYGON((139 35, 139.042 35, 139.042 35.042, 139 35.042, 139 35))"
    write_entity(
        con,
        "prefecture",
        f"""
        SELECT 'JP-13', '東京都', 'Tokyo', 'Tokio', 'Kanto', 'natural_earth', 'Q1490', 4.0,
               'x', ST_Multi(ST_GeomFromText('{square}'))
    """.replace("SELECT", "SELECT * FROM (SELECT", 1)
        + ") AS t(prefecture_code, name_ja, name_en, name_es, real_region, real_region_source, wikidata, area_km2, license, geometry)",
        root=tmp_path,
    )
    write_entity(
        con,
        "poi",
        """
        SELECT * FROM (VALUES
          ('osm:node/1', 'osm', 'node/1', 'pokemon_center', NULL, NULL, NULL, NULL, NULL, 'JP-13', 'within', 'kanto',
           h3_latlng_to_cell_string(35.01, 139.01, 7), h3_latlng_to_cell_string(35.01, 139.01, 9), 'x', ST_Point(139.01, 35.01)),
          ('osm:node/2', 'osm', 'node/2', 'onsen', NULL, NULL, NULL, NULL, NULL, 'JP-13', 'within', 'kanto',
           h3_latlng_to_cell_string(35.01, 139.01, 7), h3_latlng_to_cell_string(35.01, 139.01, 9), 'x', ST_Point(139.01, 35.01))
        ) AS t(poi_id, source, source_id, category, name_ja, name_en, name_es, plant_source, address_ja,
               prefecture_code, prefecture_method, game_region, h3_r7, h3_r9, license, geometry)
    """,
        root=tmp_path,
    )
    write_entity(
        con,
        "rail",
        """
        SELECT 'osm:way/1', 'shinkansen', NULL, NULL, NULL, NULL, 100.0, 'x',
               ST_GeomFromText('LINESTRING(139.005 35.005, 139.006 35.006)')
    """.replace("SELECT", "SELECT * FROM (SELECT", 1)
        + ") AS t(rail_id, kind, name_ja, name_en, name_es, operator, length_m, license, geometry)",
        root=tmp_path,
    )
    # Kontur: dos celdas de resolución 8 con población, en un GPKG comprimido.
    gpkg = tmp_path / "kontur.gpkg"
    con.execute(f"""
        COPY (SELECT h3, pop AS population, ST_GeomFromText(h3_cell_to_boundary_wkt(h3)) AS geom
              FROM (VALUES (h3_latlng_to_cell_string(35.01, 139.01, 8), 100.0),
                           (h3_latlng_to_cell_string(35.005, 139.005, 8), 50.0)) AS t(h3, pop))
        TO '{gpkg.as_posix()}' (FORMAT GDAL, DRIVER 'GPKG')
    """)
    _bronze(
        tmp_path,
        "kontur_population",
        {"population_jp_20231101.gpkg.gz": gzip.compress(gpkg.read_bytes())},
    )
    # VIIRS: 0,04° × 0,04° a 15" (240 px/°): mitad oeste con dato, mitad este relleno.
    transform = from_origin(139.0, 35.04, 1 / 240, 1 / 240)
    radiance = np.full((10, 10), 20.0, dtype="float32")
    radiance[:, 5:] = -999.9
    quality = np.zeros((10, 10), dtype="uint8")
    quality[:, 5:] = 255
    quality[0:5, 0:5] = 1
    viirs = tmp_path / "viirs"
    viirs.mkdir()
    _write_tif(viirs / "r.tif", radiance, transform, "EPSG:4326", nodata=-999.9)
    _write_tif(viirs / "q.tif", quality, transform, "EPSG:4326", nodata=255)
    _bronze(
        tmp_path,
        "viirs_night",
        {
            "AllAngle_Composite_Snow_Free.tif": (viirs / "r.tif").read_bytes(),
            "AllAngle_Composite_Snow_Free_Quality.tif": (viirs / "q.tif").read_bytes(),
        },
    )
    yield con, tmp_path
    con.close()


def test_h3_metric_population_night_light_density_and_sound(h3_inputs):
    con, root = h3_inputs
    summary = h3_metric.build(con, Bronze(RUN, root), root=root)
    path = tbase.silver_path("h3_metric", root).as_posix()
    q = lambda sql: con.execute(sql.format(path=f"'{path}'")).fetchall()  # noqa: E731
    # Población: la resolución 7 suma la 8.
    totals = dict(
        q("SELECT resolution, sum(value) FROM {path} WHERE metric = 'population' GROUP BY 1")
    )
    assert totals == {8: 150.0, 7: 150.0}
    # Densidad: solo puntos Pokémon (el onsen no cuenta).
    assert q("SELECT sum(value) FROM {path} WHERE metric = 'poi_density'") == [(1.0,)]
    # Luz: hay celdas con dato y celdas solo de relleno, que quedan en NULL (no en 0).
    light = q(
        "SELECT value, coverage, poor_quality_share FROM {path} WHERE metric = 'night_light' AND resolution = 9 - 1"
    )
    assert any(v is None and c == 0 for v, c, _ in light)
    assert all(v is None or v == 20.0 for v, _, _ in light)
    assert any(p is not None and 0 < p <= 1 for _, _, p in light)
    assert summary["stats"]["night_light_cells_r8_null"] >= 1
    # Sonido: celdas a 0, 1 y 2 anillos de la vía, todas marcadas como proxy.
    rings = q(
        "SELECT DISTINCT value, is_proxy FROM {path} WHERE metric = 'shinkansen_sound_proxy' ORDER BY 1"
    )
    assert rings == [(0.0, True), (1.0, True), (2.0, True)]
    assert q("SELECT count(*) FROM {path} WHERE prefecture_code = 'JP-13'")[0][0] > 0
    assert json.dumps(summary["stats"])
