# ============================================================
# geostack3d/pipeline.py
# ============================================================
# PURPOSE:
#   Orchestrates the pipeline stages built so far:
#     1. Validate     check all files before loading anything
#     2. Ingest       load all data sources
#     3. CRS          reproject everything to WGS84 (EPSG:4326)
#     4. Clip         clip all layers to study area
#     5. Schema       standardize field names and data types
#     6. Geometry     detect and repair invalid geometries
#     7. QA           run data quality checks
#     8. Save         export processed files
#
#   3D visualization (visualize_pyvista.py) is kept OUTSIDE
#   this pipeline on purpose, so run_pipeline() works even
#   without PyVista installed.
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
    SchemaConfig,
    GeometryConfig,
    QAConfig,
    OutputConfig,
    load_config,
)
from geostack3d.validate import validate_all_sources
from geostack3d.ingest import load_all_sources
from geostack3d.spatial import SpatialHarmonizer
from geostack3d.crs import harmonize_crs, harmonize_raster_crs
from geostack3d.schema import harmonize_schema
from geostack3d.geometry import repair_geometries
from geostack3d.qa import run_qa


def _save_vectors(vectors: dict, output_dir: str, vector_format: str) -> list[str]:
    """Save processed vector layers to disk."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved = []

    for name, gdf in vectors.items():
        if vector_format == "gpkg":
            path = out / f"{name}.gpkg"
            gdf.to_file(str(path), driver="GPKG")
        elif vector_format == "geojson":
            path = out / f"{name}.geojson"
            gdf.to_file(str(path), driver="GeoJSON")
        else:
            raise ValueError(f"Unsupported vector format: '{vector_format}'")

        logger.info(f"  Saved vector '{name}' → {path}")
        saved.append(str(path.resolve()))

    return saved


def _build_config_from_args(
    dem: str | None,
    orthophoto: str | None,
    samples: str | None,
    vectors: dict | None,
    study_area: str | None,
    lon_col: str,
    lat_col: str,
    project_crs: int,
    output_dir: str,
    vector_format: str,
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
        schema_config=SchemaConfig(),
        geometry=GeometryConfig(auto_repair=True),
        qa=QAConfig(halt_on_failure=False),
        output=OutputConfig(directory=output_dir, vector_format=vector_format),
        spatial=SpatialConfig(
            study_area_path=str(study_area) if study_area else None,
            clip_to_study_area=study_area is not None,
        ),
    )


def _run_pipeline_from_config(config: PipelineConfig) -> dict:
    """Run validate -> ingest -> CRS -> clip -> schema -> geometry -> QA -> save."""
    logger.info("GEOSTACK3D PIPELINE — starting")

    # Stage 1: Validate
    validate_all_sources(config)

    # Stage 2: Ingest
    all_vectors, all_rasters, tabulars = load_all_sources(config)
    all_vectors.update(tabulars)

    # Stage 3: CRS harmonization
    # Must happen BEFORE clipping — the study area and data layers
    # can be in different CRS, so clipping first was comparing
    # geometries in mismatched coordinate systems and silently
    # producing empty or wrong results.
    logger.info("Stage 3: CRS harmonization...")
    all_vectors = harmonize_crs(all_vectors, config.crs)
    if all_rasters:
        all_rasters = harmonize_raster_crs(all_rasters, config.crs)

    # Stage 4: Clip to study area
    logger.info("Stage 4: Clipping to study area...")
    spatial = SpatialHarmonizer(config.spatial)
    all_vectors = spatial.clip_vectors(all_vectors)
    if all_rasters:
        all_rasters = spatial.clip_rasters(all_rasters)

    # Stage 5: Schema harmonization
    logger.info("Stage 5: Harmonizing field names and types...")
    all_source_configs = list(config.vector_sources) + list(config.tabular_sources)
    all_vectors = harmonize_schema(all_vectors, config.schema_config, all_source_configs)

    # Stage 6: Geometry repair
    logger.info("Stage 6: Validating and repairing geometries...")
    all_vectors = repair_geometries(all_vectors, config.geometry)

    # Stage 7: QA checks
    logger.info("Stage 7: Running QA checks...")
    qa_results = run_qa(all_vectors, config.qa, config.crs.project_epsg)

    # Stage 8: Save outputs
    logger.info("Stage 8: Saving outputs...")
    saved = []
    if all_vectors:
        saved = _save_vectors(all_vectors, config.output.directory, config.output.vector_format)

    logger.info("PIPELINE COMPLETE")
    logger.info(
        "To view 3D model run:\n"
        "  from geostack3d.visualize_pyvista import make_3d_scene_pyvista\n"
        "  plotter = make_3d_scene_pyvista(result['vectors'], result['rasters'])\n"
        "  plotter.show()"
    )

    return {
        "vectors": all_vectors,
        "rasters": all_rasters,
        "qa": qa_results,
        "saved": saved,
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
    output_dir: str = "output",
    vector_format: str = "gpkg",
) -> dict:
    """
    Run the GeoStack3D pipeline.

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
            output_dir=output_dir,
            vector_format=vector_format,
        )

    return _run_pipeline_from_config(config)