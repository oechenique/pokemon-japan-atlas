import numpy as np
import pytest
from test_registry import JAPAN_CHECKPOINTS

from pipeline.sources.base import IngestError
from pipeline.sources.copernicus_dem import tiles_for_bbox
from pipeline.sources.viirs_night import paste, select_tiles, tile_bounds

DEM_TEMPLATE = "Copernicus_DSM_COG_30_{lat}_00_{lon}_00_DEM"


def test_dem_tiles_for_the_fuji_tile():
    assert tiles_for_bbox([35.2, 138.1, 35.8, 138.9], DEM_TEMPLATE) == [
        "Copernicus_DSM_COG_30_N35_00_E138_00_DEM"
    ]


def test_dem_tiles_cover_every_degree_of_an_aoi():
    tiles = tiles_for_bbox([33.56, 136.52, 37.16, 140.93], DEM_TEMPLATE)
    assert len(tiles) == 5 * 5
    assert tiles[0] == "Copernicus_DSM_COG_30_N33_00_E136_00_DEM"
    assert tiles[-1] == "Copernicus_DSM_COG_30_N37_00_E140_00_DEM"


def test_dem_tile_names_in_the_southern_and_western_hemispheres():
    assert tiles_for_bbox([-1.5, -0.5, -1.2, -0.2], DEM_TEMPLATE) == [
        "Copernicus_DSM_COG_30_S02_00_W001_00_DEM"
    ]


@pytest.mark.parametrize(
    ("tile", "bounds"),
    [
        ("h31v05", (30, 130, 40, 140)),
        ("h32v06", (20, 140, 30, 150)),
        ("h30v04", (40, 120, 50, 130)),
    ],
)
def test_black_marble_tile_bounds(tile, bounds):
    assert tile_bounds(tile) == bounds


@pytest.mark.parametrize("place", sorted(JAPAN_CHECKPOINTS))
def test_registry_tiles_cover_japan(registry, place):
    # El recorte es un rectángulo con mar y continente: lo que tiene que estar cubierto
    # es Japón, incluida Ogasawara (h32v06).
    lat, lon = JAPAN_CHECKPOINTS[place]
    params = registry.get("viirs_night").params
    south, west, north, east = params["crop_bbox"]
    assert south <= lat <= north and west <= lon <= east
    boxes = [tile_bounds(t) for t in params["tiles"]]
    assert any(s <= lat < n and w <= lon < e for s, w, n, e in boxes), place


def test_paste_puts_each_tile_in_place():
    # Mosaico de 2x3 grados a 2 px/grado; teselas de 2 grados.
    crop = [10.0, 20.0, 12.0, 23.0]
    mosaic = np.zeros((4, 6), dtype=np.int16)
    paste(mosaic, crop, np.full((4, 4), 1, np.int16), (10, 18, 12, 20), 2)  # al oeste: no toca
    paste(mosaic, crop, np.arange(16, dtype=np.int16).reshape(4, 4) + 10, (10, 20, 12, 22), 2)
    paste(mosaic, crop, np.full((4, 4), 7, np.int16), (10, 22, 12, 24), 2)
    assert mosaic[:, :4].tolist() == (np.arange(16).reshape(4, 4) + 10).tolist()
    assert (mosaic[:, 4:] == 7).all()


def test_paste_clips_rows_outside_the_crop():
    crop = [10.0, 20.0, 11.0, 21.0]
    mosaic = np.zeros((2, 2), dtype=np.int16)
    tile = np.arange(16, dtype=np.int16).reshape(4, 4)
    paste(mosaic, crop, tile, (10, 20, 12, 22), 2)  # la tesela sobra 1 grado al norte y al este
    assert mosaic.tolist() == [[8, 9], [12, 13]]


LISTING = {
    "content": [
        {"name": "VNP46A4.A2025001.h31v05.002.2026077022316.h5", "size": 1, "mtime": 1},
        {"name": "VNP46A4.A2025001.h31v04.002.2026077022152.h5", "size": 2, "mtime": 2},
        {"name": "VNP46A4.A2025001.h10v05.002.2026077022152.h5", "size": 3, "mtime": 3},
    ]
}


def test_select_tiles_keeps_only_registered_tiles_sorted():
    tiles = select_tiles(LISTING, "VNP46A4", 2025, ["h31v05", "h31v04"])
    assert [t["size"] for t in tiles] == [2, 1]


def test_select_tiles_fails_when_a_tile_is_missing():
    with pytest.raises(IngestError, match="h32v06"):
        select_tiles(LISTING, "VNP46A4", 2025, ["h31v05", "h32v06"])


def test_listing_directory_mtime_is_moved_out():
    from pipeline.sources.viirs_night import strip_directory_mtime

    listing = {"mtime": 1791380215, "content": [{"name": "a.h5", "mtime": 1}]}
    stripped, mtime = strip_directory_mtime(listing)
    assert mtime == 1791380215
    assert stripped == {"content": [{"name": "a.h5", "mtime": 1}]}
    assert "mtime" in listing  # no modifica el original
    assert strip_directory_mtime([1, 2]) == ([1, 2], None)
