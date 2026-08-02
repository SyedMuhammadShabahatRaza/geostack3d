"""
Tests for geostack3d.qa

Covers each of the 5 individual checks, and the
collect-all-then-decide / halt_on_failure behavior.
"""

import pytest

from geostack3d.config import QAConfig
from geostack3d.qa import run_qa


def test_valid_layer_passes_all_checks(valid_polygon_gdf):
    """A clean, valid, correctly-CRS'd layer should pass all 5 checks."""
    config = QAConfig(halt_on_failure=False)
    results = run_qa({"test": valid_polygon_gdf}, config, project_epsg=4326)

    assert len(results) == 5
    assert all(r["passed"] for r in results)


def test_empty_layer_fails_row_count_check():
    """A layer with 0 rows should fail the row_count check."""
    import geopandas as gpd
    empty_gdf = gpd.GeoDataFrame({"name": []}, geometry=[], crs="EPSG:4326")

    config = QAConfig(halt_on_failure=False, min_row_count=1)
    results = run_qa({"test": empty_gdf}, config, project_epsg=4326)

    row_count_result = next(r for r in results if r["check"] == "row_count")
    assert row_count_result["passed"] is False


def test_mismatched_crs_fails_crs_check(valid_polygon_gdf):
    """A layer in the wrong CRS should fail the crs_match check."""
    config = QAConfig(halt_on_failure=False)
    # valid_polygon_gdf is EPSG:4326, but we check against a different target
    results = run_qa({"test": valid_polygon_gdf}, config, project_epsg=32633)

    crs_result = next(r for r in results if r["check"] == "crs_match")
    assert crs_result["passed"] is False


def test_missing_required_field_fails_check(valid_polygon_gdf):
    """A layer missing a required field should fail the required_fields check."""
    config = QAConfig(halt_on_failure=False, required_fields=["population"])
    results = run_qa({"test": valid_polygon_gdf}, config, project_epsg=4326)

    field_result = next(r for r in results if r["check"] == "required_fields")
    assert field_result["passed"] is False


def test_halt_on_failure_true_raises(valid_polygon_gdf):
    """With halt_on_failure=True, a failing check should raise a ValueError."""
    config = QAConfig(halt_on_failure=True, required_fields=["population"])

    with pytest.raises(ValueError):
        run_qa({"test": valid_polygon_gdf}, config, project_epsg=4326)


def test_halt_on_failure_false_does_not_raise(valid_polygon_gdf):
    """With halt_on_failure=False, failures should be reported but not raised."""
    config = QAConfig(halt_on_failure=False, required_fields=["population"])

    # Should NOT raise, even though a check fails
    results = run_qa({"test": valid_polygon_gdf}, config, project_epsg=4326)
    assert any(not r["passed"] for r in results)
