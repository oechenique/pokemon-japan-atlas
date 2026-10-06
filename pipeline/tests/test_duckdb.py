import duckdb


def test_spatial_and_h3_load_from_image():
    con = duckdb.connect()
    con.load_extension("spatial")
    con.load_extension("h3")
    area = con.sql("SELECT ST_Area(ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 1,0 0))'))")
    assert area.fetchone()[0] == 1.0
    cell = con.sql("SELECT h3_latlng_to_cell_string(35.6586, 139.7454, 9)").fetchone()[0]
    assert len(cell) == 15
