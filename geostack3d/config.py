# ============================================================
# geostack3d/config.py
# ============================================================
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


# ── Source configs ───────────────────────────────────────────

class VectorSourceConfig(BaseModel):
    """One entry for a vector source."""
    name: str
    path: str
    layer: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)
    filter_expr: str | None = None
    optional: bool = True


class RasterSourceConfig(BaseModel):
    """One entry for a raster source."""
    name: str
    path: str
    band: int = 1
    nodata: float | None = None
    optional: bool = True


class TabularSourceConfig(BaseModel):
    """One entry for a tabular (CSV/Excel) source."""
    name: str
    path: str
    lon_col: str = "longitude"
    lat_col: str = "latitude"
    crs_epsg: int = 4326
    field_map: dict[str, str] = Field(default_factory=dict)
    optional: bool = True


# ── Stage configs ────────────────────────────────────────────

class CRSConfig(BaseModel):
    """CRS harmonization settings."""
    project_epsg: int = 4326


class GeometryConfig(BaseModel):
    """Geometry repair settings."""
    auto_repair: bool = True
    drop_null_geometries: bool = True
    validity_threshold: float = 0.95


class SchemaConfig(BaseModel):
    """Schema harmonization settings."""
    canonical_fields: dict[str, str] = Field(default_factory=dict)
    drop_extra_fields: bool = False
    encoding: str = "utf-8"


class SpatialConfig(BaseModel):
    """Study area clipping settings."""
    # REQUIRED — without it, the pipeline would process a full
    # DEM/raster tile at full extent, which can be slow and
    # memory-intensive on smaller machines. See PipelineConfig's
    # study_area_required validator, which enforces this.
    study_area_path: str | None = None
    clip_to_study_area: bool = True
    raster_resampling: str = "bilinear"
    snap_rasters: bool = True


class QAConfig(BaseModel):
    """QA gate settings."""
    min_row_count: int = 1
    max_row_count: int | None = None
    required_fields: list[str] = Field(default_factory=list)
    halt_on_failure: bool = True


class OutputConfig(BaseModel):
    """Output saving settings."""
    directory: str = "output"
    vector_format: Literal["gpkg", "geojson", "shp", "parquet"] = "gpkg"
    save_rasters: bool = True


class VisualizationConfig(BaseModel):
    """3D visualization settings."""
    engine: Literal["pyvista"] = "pyvista"
    dem_name: str = "dem"
    orthophoto_name: str | None = "orthophoto"
    z_exaggeration: float = 2.0
    notebook: bool = True


# ── Root config ──────────────────────────────────────────────

class PipelineConfig(BaseModel):
    """The complete pipeline configuration."""
    name: str = "geostack3d_pipeline"
    description: str = ""

    vector_sources: list[VectorSourceConfig] = Field(default_factory=list)
    raster_sources: list[RasterSourceConfig] = Field(default_factory=list)
    tabular_sources: list[TabularSourceConfig] = Field(default_factory=list)

    crs: CRSConfig = Field(default_factory=CRSConfig)
    geometry: GeometryConfig = Field(default_factory=GeometryConfig)
    schema_config: SchemaConfig = Field(default_factory=SchemaConfig)
    spatial: SpatialConfig = Field(default_factory=SpatialConfig)
    qa: QAConfig = Field(default_factory=QAConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    visualization: VisualizationConfig = Field(default_factory=VisualizationConfig)

    @model_validator(mode="after")
    def must_have_at_least_one_source(self) -> "PipelineConfig":
        """Fail loudly if no data sources are configured."""
        total = (
            len(self.vector_sources)
            + len(self.raster_sources)
            + len(self.tabular_sources)
        )
        if total == 0:
            raise ValueError(
                "Your config has no data sources.\n"
                "Add at least one entry under vector_sources,\n"
                "raster_sources, or tabular_sources."
            )
        return self

    @model_validator(mode="after")
    def study_area_required(self) -> "PipelineConfig":
        """
        Fail loudly if no study area is provided.

        Without a study area, the pipeline would process a full
        raster tile at full extent — a full USGS DEM tile is
        3601x3601 pixels, which is slow and memory-intensive on
        smaller machines. Requiring a study area up front keeps
        the pipeline efficient by default rather than as an
        opt-in optimization.
        """
        if not self.spatial.study_area_path:
            raise ValueError(
                "A study area is required.\n"
                "Pass 'study_area' to run_pipeline() pointing to "
                "a boundary polygon file."
            )
        return self