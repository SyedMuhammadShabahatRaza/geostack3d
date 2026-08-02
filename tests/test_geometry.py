"""
Tests for geostack3d.geometry

Covers the core discoveries from real testing during this
project: valid data passes through untouched, invalid geometry
gets repaired (and may split into a MultiPolygon), and null
geometries get dropped.
"""

from geostack3d.config import GeometryConfig
from geostack3d.geometry import repair_geometries


def test_valid_geometry_passes_through_unchanged(valid_polygon_gdf):
    """A layer that's already 100% valid should report validity_rate=1.0."""
    config = GeometryConfig(auto_repair=True, validity_threshold=0.0)
    result = repair_geometries({"test": valid_polygon_gdf}, config)

    assert result["test"].geometry.is_valid.all()
    assert len(result["test"]) == 1


def test_invalid_bowtie_gets_repaired(invalid_bowtie_gdf):
    """
    A deliberately broken bowtie polygon should be invalid before
    repair, and fully valid after — this is the exact behavior
    verified manually during the project (splits into MultiPolygon).
    """
    assert not invalid_bowtie_gdf.geometry.is_valid.all()  # sanity check: really is invalid

    config = GeometryConfig(auto_repair=True, validity_threshold=0.0)
    result = repair_geometries({"test": invalid_bowtie_gdf}, config)

    assert result["test"].geometry.is_valid.all()


def test_geometry_repair_raises_when_auto_repair_disabled(invalid_bowtie_gdf):
    """If auto_repair is False, invalid geometry should raise, not silently pass."""
    config = GeometryConfig(auto_repair=False, validity_threshold=0.0)
    try:
        repair_geometries({"test": invalid_bowtie_gdf}, config)
        assert False, "Expected a ValueError when auto_repair=False and geometry is invalid"
    except ValueError:
        pass  # expected


def test_null_geometry_gets_dropped(null_geometry_gdf):
    """A row with a null geometry should be removed when drop_null_geometries=True."""
    assert len(null_geometry_gdf) == 2  # sanity check: starts with 2 rows

    config = GeometryConfig(auto_repair=True, drop_null_geometries=True, validity_threshold=0.0)
    result = repair_geometries({"test": null_geometry_gdf}, config)

    assert len(result["test"]) == 1  # the null row should be gone
    assert result["test"].geometry.is_valid.all()


def test_repair_geometries_processes_multiple_layers(valid_polygon_gdf, invalid_bowtie_gdf):
    """repair_geometries should handle multiple layers in one call, independently."""
    config = GeometryConfig(auto_repair=True, validity_threshold=0.0)
    result = repair_geometries(
        {"clean": valid_polygon_gdf, "broken": invalid_bowtie_gdf}, config
    )

    assert set(result.keys()) == {"clean", "broken"}
    assert result["clean"].geometry.is_valid.all()
    assert result["broken"].geometry.is_valid.all()
