"""
Tests for geostack3d.config

Covers the two custom validators on PipelineConfig, and default
values on the individual stage config classes.
"""

import pytest
from pydantic import ValidationError

from geostack3d.config import (
    PipelineConfig,
    VectorSourceConfig,
    RasterSourceConfig,
    SpatialConfig,
    GeometryConfig,
    QAConfig,
)


def test_pipeline_config_requires_at_least_one_source():
    """A PipelineConfig with zero sources should raise, not silently succeed."""
    with pytest.raises(ValidationError):
        PipelineConfig(
            spatial=SpatialConfig(study_area_path="dummy.geojson"),
        )


def test_pipeline_config_requires_study_area():
    """A PipelineConfig without a study_area_path should raise."""
    with pytest.raises(ValidationError):
        PipelineConfig(
            raster_sources=[
                RasterSourceConfig(name="dem", path="dem.tif", optional=False)
            ],
            spatial=SpatialConfig(study_area_path=None),
        )


def test_pipeline_config_valid_with_source_and_study_area():
    """A PipelineConfig with one source AND a study area should succeed."""
    config = PipelineConfig(
        raster_sources=[RasterSourceConfig(name="dem", path="dem.tif", optional=False)],
        spatial=SpatialConfig(study_area_path="study_area.geojson"),
    )
    assert config.spatial.study_area_path == "study_area.geojson"
    assert len(config.raster_sources) == 1


def test_geometry_config_defaults():
    """GeometryConfig should default to auto-repair enabled, 95% validity threshold."""
    config = GeometryConfig()
    assert config.auto_repair is True
    assert config.drop_null_geometries is True
    assert config.validity_threshold == 0.95


def test_qa_config_defaults():
    """QAConfig should default to halt_on_failure=True at the package level."""
    config = QAConfig()
    assert config.halt_on_failure is True
    assert config.min_row_count == 1
    assert config.max_row_count is None


def test_vector_source_config_optional_defaults_true():
    """VectorSourceConfig sources should be optional by default."""
    src = VectorSourceConfig(name="test", path="test.geojson")
    assert src.optional is True
    assert src.field_map == {}
