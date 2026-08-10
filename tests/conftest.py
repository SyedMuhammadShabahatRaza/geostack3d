"""
Shared pytest fixtures for geostack3d test suite.

These fixtures build small, synthetic data in-memory — no
dependency on large real DEM/orthophoto files, so tests run
fast and are fully reproducible on any machine.
"""

import numpy as np
import geopandas as gpd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, LineString, Polygon


@pytest.fixture
def valid_polygon_gdf():
    """A small, valid GeoDataFrame with one clean polygon."""
    poly = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    return gpd.GeoDataFrame({"name": ["clean_area"]}, geometry=[poly], crs="EPSG:4326")


@pytest.fixture
def invalid_bowtie_gdf():
    """A GeoDataFrame with one deliberately self-intersecting (bowtie) polygon."""
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    return gpd.GeoDataFrame({"name": ["bowtie"]}, geometry=[bowtie], crs="EPSG:4326")


@pytest.fixture
def null_geometry_gdf():
    """A GeoDataFrame with one valid feature and one null geometry."""
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    return gpd.GeoDataFrame(
        {"name": ["valid", "missing"]},
        geometry=[poly, None],
        crs="EPSG:4326",
    )


@pytest.fixture
def utm_point_gdf():
    """A point layer in a projected CRS (UTM), for CRS harmonization tests."""
    pt = Point(500000, 4649776)  # a typical UTM easting/northing
    return gpd.GeoDataFrame({"name": ["utm_point"]}, geometry=[pt], crs="EPSG:32633")


@pytest.fixture
def wgs84_point_gdf():
    """A point layer already in WGS84 — should be skipped by CRS harmonization."""
    pt = Point(10.0, 45.0)
    return gpd.GeoDataFrame({"name": ["wgs84_point"]}, geometry=[pt], crs="EPSG:4326")


@pytest.fixture
def messy_schema_gdf():
    """A GeoDataFrame mimicking a raw KML export with boilerplate columns."""
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    return gpd.GeoDataFrame(
        {
            "id": [None],
            "Name": ["TEST_AREA"],
            "description": [None],
            "timestamp": [None],
        },
        geometry=[poly],
        crs="EPSG:4326",
    )


@pytest.fixture
def small_dem_geotiff(tmp_path):
    """
    Writes a small, synthetic DEM GeoTIFF to a temp file and
    returns its path. 10x10 pixels, simple elevation gradient.
    """
    path = tmp_path / "small_dem.tif"
    data = np.linspace(100, 200, 100).reshape(10, 10).astype("float32")
    transform = from_origin(west=10.0, north=45.0, xsize=0.01, ysize=0.01)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)

    return str(path)


@pytest.fixture
def small_dem_wrong_crs_geotiff(tmp_path):
    """Same small DEM, but saved in a projected CRS (needs reprojection)."""
    path = tmp_path / "small_dem_utm.tif"
    data = np.linspace(100, 200, 100).reshape(10, 10).astype("float32")
    transform = from_origin(west=500000.0, north=4649776.0, xsize=10, ysize=10)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs="EPSG:32633",
        transform=transform,
    ) as dst:
        dst.write(data, 1)

    return str(path)
