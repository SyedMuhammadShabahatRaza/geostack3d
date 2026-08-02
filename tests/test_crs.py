"""
Tests for geostack3d.crs

Covers the "skip-if-already-correct" behavior, and genuine
reprojection when a layer's CRS doesn't match the target.
"""

from geostack3d.config import CRSConfig
from geostack3d.crs import harmonize_crs


def test_already_correct_crs_is_skipped_unchanged(wgs84_point_gdf):
    """A layer already in the target CRS should pass through with identical coordinates."""
    original_x = wgs84_point_gdf.geometry.iloc[0].x
    original_y = wgs84_point_gdf.geometry.iloc[0].y

    config = CRSConfig(project_epsg=4326)
    result = harmonize_crs({"test": wgs84_point_gdf}, config)

    assert result["test"].crs.to_epsg() == 4326
    # Coordinates should be EXACTLY unchanged (no reprojection math applied)
    assert result["test"].geometry.iloc[0].x == original_x
    assert result["test"].geometry.iloc[0].y == original_y


def test_mismatched_crs_gets_reprojected(utm_point_gdf):
    """A layer in a projected CRS should be reprojected to the target CRS."""
    assert utm_point_gdf.crs.to_epsg() == 32633  # sanity check

    config = CRSConfig(project_epsg=4326)
    result = harmonize_crs({"test": utm_point_gdf}, config)

    assert result["test"].crs.to_epsg() == 4326
    # After reprojection to WGS84, coordinates should be in valid lon/lat range
    x = result["test"].geometry.iloc[0].x
    y = result["test"].geometry.iloc[0].y
    assert -180 <= x <= 180
    assert -90 <= y <= 90


def test_layer_with_no_crs_raises():
    """A layer with no CRS set at all should raise a clear error, not silently proceed."""
    import geopandas as gpd
    from shapely.geometry import Point

    no_crs_gdf = gpd.GeoDataFrame({"name": ["test"]}, geometry=[Point(1, 1)], crs=None)
    config = CRSConfig(project_epsg=4326)

    try:
        harmonize_crs({"test": no_crs_gdf}, config)
        assert False, "Expected a ValueError for a layer with no CRS"
    except ValueError:
        pass  # expected
