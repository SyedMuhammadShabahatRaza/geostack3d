# ============================================================
# geostack3d/config.py
# ============================================================
# PURPOSE:
#   Load settings from a YAML config file and validate them
#   using Pydantic v2.
#
# WHY A CONFIG FILE?
#   Without a config file, every setting (file paths, CRS,
#   field names) would be hardcoded in Python files. That means
#   changing a file path = editing Python code. Bad practice.
#   With a config file, you just edit the YAML and run again.
#
# WHY PYDANTIC?
#   Pydantic checks your config values have the right types
#   before any data is processed. If you put a word where a
#   number is expected, it tells you immediately with a clear
#   error message. Think of it as a spell-checker for your
#   configuration.
#
# STRUCTURE:
#   Each class below maps to one section in your YAML file.
#   PipelineConfig is the root object that wraps them all.
# ============================================================

from pathlib import Path
from typing import Any, Literal
import yaml
from pydantic import BaseModel, Field, model_validator


# ── Source configs ───────────────────────────────────────────

class VectorSourceConfig(BaseModel):
    """One entry under 'vector_sources:' in the YAML."""

    name: str
    path: str
    layer: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)
    filter_expr: str | None = None
    # If True, pipeline skips this source if the file is missing
    # instead of raising an error. Useful for optional layers
    # like faults or roads that you may not always have.
    optional: bool = True


class RasterSourceConfig(BaseModel):
    """One entry under 'raster_sources:' in the YAML."""

    name: str
    path: str
    band: int = 1
    nodata: float | None = None
    # DEM should be optional: false since 3D needs it
    # Orthophoto can be optional: true
    optional: bool = True


class TabularSourceConfig(BaseModel):
    """One entry under 'tabular_sources:' in the YAML."""

    name: str
    path: str
    lon_col: str = "longitude"
    lat_col: str = "latitude"
    crs_epsg: int = 4326
    field_map: dict[str, str] = Field(default_factory=dict)
    # CSV/Excel sample data is always optional
    optional: bool = True


# ── Stage configs ────────────────────────────────────────────

class CRSConfig(BaseModel):
    """Settings under 'crs:' in the YAML."""

    # All layers will be reprojected to this CRS.
    # 4326 = WGS84 (GPS standard, degrees) — the global standard

    project_epsg: int = 4326


class GeometryConfig(BaseModel):
    """Settings under 'geometry:' in the YAML."""

    auto_repair: bool = True
    drop_null_geometries: bool = True
    validity_threshold: float = 0.95


class SchemaConfig(BaseModel):
    """Settings under 'schema_config:' in the YAML."""

    canonical_fields: dict[str, str] = Field(default_factory=dict)
    drop_extra_fields: bool = False
    encoding: str = "utf-8"


class SpatialConfig(BaseModel):
    """Settings under 'spatial:' in the YAML."""

    # Path to a polygon file defining your study area boundary.
    # If provided, all layers are clipped to this boundary.
    # If not provided, layers are processed at their full extent.
    study_area_path: str | None = None

    # Should layers be clipped to the study area?
    clip_to_study_area: bool = True

    # Resampling method used when aligning raster grids.
    # bilinear = smooth interpolation, good for elevation/imagery.
    # nearest  = exact pixel values, good for classified data.
    raster_resampling: str = "bilinear"

    snap_rasters: bool = True


class QAConfig(BaseModel):
    """Settings under 'qa:' in the YAML."""

    min_row_count: int = 1
    max_row_count: int | None = None
    required_fields: list[str] = Field(default_factory=list)

    # True = stop pipeline when a QA check fails
    # False = log a warning but continue
    halt_on_failure: bool = True


class OutputConfig(BaseModel):
    """Settings under 'output:' in the YAML."""

    directory: str = "output"

    # Vector output format
    # gpkg    = GeoPackage (recommended, opens in ArcGIS + QGIS)
    # geojson = GeoJSON (human-readable, web-friendly)
    # shp     = Shapefile (legacy, widely compatible)
    # parquet = GeoParquet (fastest for large datasets)
    vector_format: Literal["gpkg", "geojson", "shp", "parquet"] = "gpkg"

    # Save processed rasters as GeoTIFF
    save_rasters: bool = True


class VisualizationConfig(BaseModel):
    """Settings under 'visualization:' in the YAML."""

    # Which 3D engine to use
    # pyvista = PyVista (recommended, best quality, needs pyvista[jupyter])
    # plotly  = Plotly (works without extra install, lower quality)
    engine: Literal["pyvista", "plotly"] = "pyvista"

    # Name of the raster source to use as terrain surface
    dem_name: str = "dem"

    # Name of the raster source to use as texture (optional)
    # If not provided, terrain is colored by elevation
    orthophoto_name: str | None = "orthophoto"

    # Vertical exaggeration of terrain
    # 1.0 = true scale, 2.0 = twice as tall, etc.
    # Useful when elevation differences are subtle
    z_exaggeration: float = 2.0

    # True = render inline in Jupyter notebook
    # False = open a separate desktop window
    notebook: bool = True


# ── Root config ──────────────────────────────────────────────

class PipelineConfig(BaseModel):
    """
    The complete pipeline configuration.

    Maps directly to the structure of your YAML config file.
    Each attribute corresponds to a top-level YAML key.
    """

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


# ── Public function ──────────────────────────────────────────

def load_config(path: str | Path) -> PipelineConfig:
    """
    Read a YAML config file and return a validated PipelineConfig.

    Parameters
    ----------
    path : str or Path
        Path to your .yaml config file.

    Returns
    -------
    PipelineConfig
        A fully validated config object.

    Raises
    ------
    FileNotFoundError
        If the config file does not exist.
    ValueError
        If the config contains invalid values.

    Examples
    --------
    >>> from geostack3d import load_config
    >>> config = load_config("configs/default.yaml")
    >>> print(config.crs.project_epsg)
    4326
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Check the path and try again."
        )

    with open(path, encoding="utf-8") as f:
        raw_dict = yaml.safe_load(f)

    config = PipelineConfig.model_validate(raw_dict)
    return config