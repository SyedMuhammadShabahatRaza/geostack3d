# ============================================================
# geostack3d/pipeline.py
# ============================================================
# PURPOSE:
#   Orchestrates all pipeline stages in the correct sequence.
#   This is the only file most users ever need to interact
#   with directly.
#
# USAGE:
#      result = run_pipeline(
#          dem        = r"path/to/dem.tif",
#          orthophoto = r"path/to/satellite.tif",
#          samples    = r"path/to/samples.csv",
#          study_area = r"path/to/boundary.geojson",
#          output_dir = r"path/to/output",
#      )
#
# PIPELINE SEQUENCE:
#   1. Validate     check all files before loading anything
#   2. Ingest       load all data sources
#   3. CRS          reproject everything to WGS84 (EPSG:4326)
#                   including study area (handles UTM input)
#   4. Clip         clip all layers to study area
#   5. Schema       standardize field names and data types
#   6. Geometry     detect and repair invalid geometries
#   7. QA           run data quality checks
#   8. Save         export processed files
#   9. Visualize    build interactive 3D scene (PyVista)
#
# RETURN VALUE:
#   A dict with keys:
#     "vectors"  - processed GeoDataFrames
#     "rasters"  - processed raster datasets
#     "qa"       - QA check results
#     "saved"    - paths of saved output files
#     "config"   - the PipelineConfig used
# ============================================================

import time
from pathlib import Path

import geopandas as gpd
import rasterio
from loguru import logger

from geostack3d.config import (
    PipelineConfig,
    VectorSourceConfig,
    RasterSourceConfig,
    TabularSourceConfig,
    CRSConfig,
    GeometryConfig,
    SchemaConfig,
    SpatialConfig,
    QAConfig,
    OutputConfig,
    VisualizationConfig,
)
from geostack3d.validate import validate_all_sources
from geostack3d.ingest import load_all_sources
from geostack3d.crs import harmonize_crs, harmonize_raster_crs
from geostack3d.spatial import SpatialHarmonizer
from geostack3d.schema import harmonize_schema
from geostack3d.geometry import repair_geometries
from geostack3d.qa import run_qa


# ── Output helpers ───────────────────────────────────────────

def _save_vectors(
    vectors: dict,
    output_dir: str,
    vector_format: str,
) -> list[str]:
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
        elif vector_format == "shp":
            path = out / f"{name}.shp"
            gdf.to_file(str(path), driver="ESRI Shapefile")
        elif vector_format == "parquet":
            path = out / f"{name}.parquet"
            gdf.to_parquet(str(path))
        else:
            raise ValueError(f"Unsupported vector format: '{vector_format}'")

        logger.info(f"  Saved vector '{name}' → {path}")
        saved.append(str(path.resolve()))

    return saved


def _save_rasters(
    rasters: dict,
    output_dir: str,
) -> list[str]:
    """Save processed raster datasets to GeoTIFF."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved = []

    for name, ds in rasters.items():
        if isinstance(ds, rasterio.io.MemoryFile):
            src = ds.open()
        else:
            src = ds

        path = out / f"{name}_processed.tif"
        profile = src.profile.copy()
        profile.update(driver="GTiff")

        try:
            with rasterio.open(str(path), "w", **profile) as dst:
                dst.write(src.read())
            logger.info(f"  Saved raster '{name}' → {path}")
            saved.append(str(path.resolve()))
        except Exception as e:
            logger.warning(f"  Could not save raster '{name}': {e}")

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
    z_exaggeration: float,
    dem_name: str,
    orthophoto_name: str | None,
) -> PipelineConfig:
    """Build a PipelineConfig from function arguments."""
    vector_sources = []
    if vectors:
        for name, path in vectors.items():
            vector_sources.append(
                VectorSourceConfig(name=name, path=str(path), optional=True)
            )

    raster_sources = []
    if dem:
        raster_sources.append(
            RasterSourceConfig(name=dem_name, path=str(dem), optional=False)
        )
    if orthophoto:
        raster_sources.append(
            RasterSourceConfig(name=orthophoto_name or "orthophoto",
                             path=str(orthophoto), optional=True)
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

    if not raster_sources and not vector_sources and not tabular_sources:
        raise ValueError(
            "No data provided. Pass at least one of:\n"
            "  dem, orthophoto, samples, or vectors."
        )

    return PipelineConfig(
        name="geostack3d_run",
        vector_sources=vector_sources,
        raster_sources=raster_sources,
        tabular_sources=tabular_sources,
        crs=CRSConfig(project_epsg=project_crs),
        geometry=GeometryConfig(auto_repair=True),
        schema_config=SchemaConfig(
            canonical_fields={},
            drop_extra_fields=False,
        ),
        spatial=SpatialConfig(
            study_area_path=str(study_area) if study_area else None,
            clip_to_study_area=study_area is not None,
        ),
        qa=QAConfig(halt_on_failure=False),
        output=OutputConfig(
            directory=output_dir,
            vector_format=vector_format,
        ),
        visualization=VisualizationConfig(
            dem_name=dem_name,
            orthophoto_name=orthophoto_name,
            z_exaggeration=z_exaggeration,
        ),
    )


# ── Core pipeline runner ─────────────────────────────────────

def _run_pipeline_from_config(config: PipelineConfig) -> dict:
    """
    Run all pipeline stages using a PipelineConfig object.

    Parameters
    ----------
    config : PipelineConfig

    Returns
    -------
    dict with keys: vectors, rasters, qa, saved, config
    """
    start = time.perf_counter()

    logger.info("=" * 60)
    logger.info("GEOSTACK3D PIPELINE — starting")
    logger.info("=" * 60)

    # ── Stage 1: Validate ────────────────────────────────────
    validate_all_sources(config)

    # ── Stage 2: Ingest ──────────────────────────────────────
    all_vectors, all_rasters, tabulars = load_all_sources(config)
    all_vectors.update(tabulars)  # tabular → point GeoDataFrames

    # ── Stage 3: CRS harmonization ───────────────────────────
    # Must happen BEFORE clipping — the study area and data
    # layers can be in different CRS, so clipping first was
    # comparing geometries in mismatched coordinate systems
    # and silently producing empty or wrong results.
    logger.info("Stage 3: CRS harmonization...")
    all_vectors = harmonize_crs(all_vectors, config.crs)
    if all_rasters:
        all_rasters = harmonize_raster_crs(all_rasters, config.crs)

    if config.spatial.study_area_path:
        try:
            sa_path = Path(config.spatial.study_area_path)
            if sa_path.exists():
                study_area_gdf = gpd.read_file(str(sa_path))
                original_epsg = study_area_gdf.crs.to_epsg() if study_area_gdf.crs else "unknown"
                if original_epsg != config.crs.project_epsg:
                    logger.info(
                        f"  Reprojecting study area: "
                        f"EPSG:{original_epsg} → EPSG:{config.crs.project_epsg}"
                    )
                    study_area_gdf = study_area_gdf.to_crs(
                        epsg=config.crs.project_epsg
                    )
                config.spatial._study_area_gdf = study_area_gdf
        except Exception as e:
            logger.warning(f"  Could not reproject study area: {e}")

    # ── Stage 4: Clip to study area ──────────────────────────
    logger.info("Stage 4: Clipping to study area...")
    spatial = SpatialHarmonizer(config.spatial)
    all_vectors = spatial.clip_vectors(all_vectors)
    if all_rasters:
        all_rasters = spatial.clip_rasters(all_rasters)

    # ── Stage 5: Schema harmonization ────────────────────────
    logger.info("Stage 5: Schema harmonization...")
    all_source_configs = (
        list(config.vector_sources) + list(config.tabular_sources)
    )
    all_vectors = harmonize_schema(
        all_vectors, config.schema_config, all_source_configs
    )

    # ── Stage 6: Geometry repair ──────────────────────────────
    logger.info("Stage 6: Geometry validation and repair...")
    all_vectors = repair_geometries(all_vectors, config.geometry)

    # ── Stage 7: QA checks ────────────────────────────────────
    logger.info("Stage 7: QA checks...")
    qa_results = run_qa(all_vectors, config.qa, config.crs.project_epsg)

    # ── Stage 8: Save outputs ─────────────────────────────────
    logger.info("Stage 8: Saving outputs...")
    saved = []
    if all_vectors:
        saved.extend(
            _save_vectors(all_vectors, config.output.directory,
                         config.output.vector_format)
        )
    if all_rasters and config.output.save_rasters:
        saved.extend(
            _save_rasters(all_rasters, config.output.directory)
        )

    elapsed = time.perf_counter() - start
    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE in {elapsed:.2f}s")
    logger.info(f"  Layers processed : {len(all_vectors)}")
    logger.info(f"  Rasters processed: {len(all_rasters)}")
    logger.info(f"  Files saved      : {len(saved)}")
    logger.info("=" * 60)
    logger.info(
        "To view 3D model run:\n"
        "  from geostack3d.visualize_pyvista import make_3d_scene_pyvista\n"
        f"  plotter = make_3d_scene_pyvista(result['vectors'], "
        f"result['rasters'], dem_name='{config.visualization.dem_name}')\n"
        "  plotter.show()"
    )

    return {
        "vectors": all_vectors,
        "rasters": all_rasters,
        "qa": qa_results,
        "saved": saved,
        "config": config,
    }


# ── Public interface ─────────────────────────────────────────

def run_pipeline(
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
    z_exaggeration: float = 2.0,
    dem_name: str = "dem",
    orthophoto_name: str | None = "orthophoto",
) -> dict:
    """
    Run the full GeoStack3D pipeline.

    result = run_pipeline(
        dem        = r"path/to/dem.tif",
        orthophoto = r"path/to/satellite.tif",
        samples    = r"path/to/samples.csv",
        study_area = r"path/to/boundary.geojson",
        output_dir = r"path/to/output",
    )

    Pipeline stages:
        1. Validate   check files before loading
        2. Ingest     load all data sources
        3. CRS        reproject everything to WGS84
        4. Clip       clip to study area (required)
        5. Schema     standardize field names
        6. Geometry   repair invalid geometries
        7. QA         data quality checks
        8. Save       export processed files

    Parameters
    ----------
    dem : str, optional
        Path to DEM/elevation raster (.tif).
        Required for 3D visualization.

    orthophoto : str, optional
        Path to satellite/aerial image (.tif).
        Textures the 3D terrain surface if provided.

    samples : str, optional
        Path to CSV/Excel with coordinate columns.

    vectors : dict[str, str], optional
        Additional vector layers as {name: path}.
        Example: {"faults": r"path/to/faults.geojson"}

    study_area : str
        REQUIRED. Path to a polygon file defining the area of
        interest. All layers are clipped to this boundary.
        Accepts any CRS — reprojected automatically. Without
        this, a full raster tile would be processed at full
        extent, which is slow and memory-intensive.

    lon_col : str
        Longitude column name in CSV. Default: "longitude"

    lat_col : str
        Latitude column name in CSV. Default: "latitude"

    project_crs : int
        Target EPSG code. Default: 4326 (WGS84)

    output_dir : str
        Folder to save outputs. Default: "output"

    vector_format : str
        Output format: gpkg | geojson | shp | parquet
        Default: "gpkg"

    z_exaggeration : float
        Vertical exaggeration for 3D terrain. Default: 2.0

    dem_name : str
        Internal name for the DEM layer. Default: "dem"

    orthophoto_name : str or None
        Internal name for the orthophoto layer.
        Default: "orthophoto"

    Returns
    -------
    dict
        {
            "vectors" : dict[str, GeoDataFrame],
            "rasters" : dict[str, rasterio dataset],
            "qa"      : list[dict],
            "saved"   : list[str],
            "config"  : PipelineConfig,
        }

    Examples
    --------
    >>> from geostack3d import run_pipeline
    >>> result = run_pipeline(
    ...     dem        = r"C:/data/dem.tif",
    ...     samples    = r"C:/data/samples.csv",
    ...     study_area = r"C:/data/boundary.geojson",
    ...     output_dir = r"C:/data/output",
    ... )

    Then view 3D:

    >>> from geostack3d.visualize_pyvista import make_3d_scene_pyvista
    >>> plotter = make_3d_scene_pyvista(
    ...     result["vectors"],
    ...     result["rasters"],
    ...     dem_name="dem",
    ... )
    >>> plotter.show()
    """

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
        z_exaggeration=z_exaggeration,
        dem_name=dem_name,
        orthophoto_name=orthophoto_name,
    )

    return _run_pipeline_from_config(config)