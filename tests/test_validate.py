"""
Tests for geostack3d.validate

Covers required vs. optional source handling, and the
collect-all-then-decide error aggregation pattern.
"""

import pytest

from geostack3d.config import (
    PipelineConfig,
    RasterSourceConfig,
    VectorSourceConfig,
    SpatialConfig,
)
from geostack3d.validate import validate_all_sources


def test_missing_required_raster_raises(tmp_path):
    """A missing REQUIRED raster source should cause validation to fail."""
    study_area = tmp_path / "study_area.geojson"
    study_area.write_text('{"type": "FeatureCollection", "features": []}')

    config = PipelineConfig(
        raster_sources=[
            RasterSourceConfig(
                name="dem", path=str(tmp_path / "does_not_exist.tif"), optional=False
            )
        ],
        spatial=SpatialConfig(study_area_path=str(study_area)),
    )

    with pytest.raises(ValueError):
        validate_all_sources(config)


def test_missing_optional_vector_does_not_raise(small_dem_geotiff, tmp_path):
    """A missing OPTIONAL vector source should be skipped, not raise."""
    study_area = tmp_path / "study_area.geojson"
    study_area.write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", '
        '"geometry": {"type": "Polygon", "coordinates": [[[10,45],[10.1,45],[10.1,45.1],[10,45.1],[10,45]]]}, '
        '"properties": {}}]}'
    )

    config = PipelineConfig(
        raster_sources=[
            RasterSourceConfig(name="dem", path=small_dem_geotiff, optional=False)
        ],
        vector_sources=[
            VectorSourceConfig(
                name="path", path=str(tmp_path / "missing.kml"), optional=True
            )
        ],
        spatial=SpatialConfig(study_area_path=str(study_area)),
    )

    # Should NOT raise — missing optional source is just skipped
    validate_all_sources(config)


def test_missing_study_area_always_raises(small_dem_geotiff, tmp_path):
    """
    The study area is always hard-required, regardless of its own
    optional flag — a missing study area file should always fail
    validation, since PipelineConfig itself requires the path to
    be set, and validate_all_sources confirms the file is real.
    """
    config = PipelineConfig(
        raster_sources=[
            RasterSourceConfig(name="dem", path=small_dem_geotiff, optional=False)
        ],
        spatial=SpatialConfig(
            study_area_path=str(tmp_path / "missing_study_area.geojson")
        ),
    )

    with pytest.raises(ValueError):
        validate_all_sources(config)
