# ============================================================
# geostack3d/pipeline.py
# ============================================================
# PURPOSE:
#   Orchestrates the pipeline stages built so far:
#     1. Validate   check all files before loading anything
#     2. Ingest     load all data sources
#     3. Clip       clip all layers to study area
#     4. CRS        reproject everything to WGS84 (EPSG:4326)
#
# More stages (schema, geometry, QA, visualization) to follow.
# ============================================================

from pathlib import Path

from loguru import logger

from geostack3d.config import (
    PipelineConfig,
    VectorSourceConfig,
    RasterSourceConfig,
    TabularSourceConfig,
    CRSConfig,
    SpatialConfig,
    load_config,
)
from geostack3d.validate import validate_all_sources
from geostack3d.ingest import load_all_sources
from geostack3d.spatial import SpatialHarmonizer
from geostack3d.crs import harmonize_crs, harmonize_raster_crs


def _build_config_from_args(
    dem: str | None,
    orthophoto: str | None,
    samples: str | None,
    vectors: dict | None,
    study_area: str | None,
    lon_col: str,
    lat_col: str,
    project_crs: int,
) -> PipelineConfig:
    """Build a PipelineConfig from simple function arguments."""
    vector_sources = []
    if vectors:
        for name, path in vectors.items():
            vector_sources.append(
                VectorSourceConfig(name=name, path=str(path), optional=True)
            )

    raster_sources = []
    if dem:
        raster_sources.append(
            RasterSourceConfig(name="dem", path=str(dem), optional=False)
        )
    if orthophoto:
        raster_sources.append(
            RasterSourceConfig(name="orthophoto", path=str(orthophoto), optional=True)
        )

    tabular_sources = []
    if samples:
        tabular_sources.append(
            TabularSourceConfig(
                name="samples",
                path=str(samples),
                lon_col=lon_col,
                lat_col=lat_col,
                optional=True,
            )
        )

    return PipelineConfig(
        name="geostack3d_run",
        vector_sources=vector_sources,
        raster_sources=raster_sources,
        tabular_sources=tabular_sources,
        crs=CRSConfig(project_epsg=project_crs),
        spatial=SpatialConfig(
            study_area_path=str(study_area) if study_area else None,
            clip_to_study_area=study_area is not None,
        ),
    )


def _run_pipeline_from_config(config: PipelineConfig) -> dict:
    """Run validate -> ingest -> clip -> CRS harmonization."""
    logger.info("GEOSTACK3D PIPELINE — starting")

    # Stage 1: Validate
    validate_all_sources(config)

    # Stage 2: Ingest
    all_vectors, all_rasters, tabulars = load_all_sources(config)
    all_vectors.update(tabulars)

    # Stage 3: Clip to study area
    logger.info("Stage 3: Clipping to study area...")
    spatial = SpatialHarmonizer(config.spatial)
    all_vectors = spatial.clip_vectors(all_vectors)
    if all_rasters:
        all_rasters = spatial.clip_rasters(all_rasters)

    # Stage 4: CRS harmonization
    logger.info("Stage 4: CRS harmonization...")
    all_vectors = harmonize_crs(all_vectors, config.crs)
    if all_rasters:
        all_rasters = harmonize_raster_crs(all_rasters, config.crs)

    logger.info("PIPELINE COMPLETE")

    return {
        "vectors": all_vectors,
        "rasters": all_rasters,
        "config": config,
    }


def run_pipeline(
    config_path: str | Path | None = None,
    dem: str | None = None,
    orthophoto: str | None = None,
    samples: str | None = None,
    vectors: dict[str, str] | None = None,
    study_area: str | None = None,
    lon_col: str = "longitude",
    lat_col: str = "latitude",
    project_crs: int = 4326,
) -> dict:
    """
    Run the GeoStack3D pipeline (early version).

    Supports either a YAML config file or direct file path arguments.
    """
    if config_path is not None:
        config = load_config(config_path)
    else:
        config = _build_config_from_args(
            dem=dem,
            orthophoto=orthophoto,
            samples=samples,
            vectors=vectors,
            study_area=study_area,
            lon_col=lon_col,
            lat_col=lat_col,
            project_crs=project_crs,
        )

    return _run_pipeline_from_config(config)