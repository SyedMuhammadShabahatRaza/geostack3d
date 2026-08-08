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
#   dem / orthophoto can also be a LIST of paths, in which case
#   the tiles are automatically merged into one seamless raster.
#
#   samples can now be a single path, a LIST of paths (each
#   auto-named samples_0, samples_1, ...), or a DICT of
#   {name: path} pairs (each keeping the name you give it) —
#   so multiple CSV/Excel sources can be loaded in one call.
#
# PIPELINE SEQUENCE:
#   1. Validate     check all files before loading anything
#   2. Ingest       load all data sources (merging DEM tiles if needed)
#   3. CRS          reproject everything to WGS84 (EPSG:4326)
#                   including study area (handles UTM input)
#   4. Geometry     detect and repair invalid geometries
#                   (including the study area's own boundary)
#   5. Clip         clip all layers to study area
#   6. Schema       standardize field names and data types
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
        # Handle both MemoryFile and open DatasetReader
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


def _build_tabular_sources(
    samples,
    lon_col: str,
    lat_col: str,
) -> list[TabularSourceConfig]:
    """
    Build the list of TabularSourceConfig objects from the
    `samples` argument, which can be:
      - a single path (string)      -> one source, named "samples"
      - a list of paths             -> auto-named samples_0, samples_1, ...
      - a dict of {name: path}      -> keeps the names you give it

    All sources share the same lon_col/lat_col — if your files
    use genuinely different column names, build a PipelineConfig
    manually instead (see README / Limitations).
    """
    tabular_sources = []

    if samples is None:
        return tabular_sources

    if isinstance(samples, dict):
        # e.g. {"team_a": "samples_teamA.csv", "team_b": "samples_teamB.csv"}
        for name, path in samples.items():
            tabular_sources.append(
                TabularSourceConfig(
                    name=name,
                    path=str(path),
                    lon_col=lon_col,
                    lat_col=lat_col,
                    optional=True,
                )
            )
    elif isinstance(samples, list):
        # e.g. ["file1.csv", "file2.csv"] — no names given, so we
        # generate simple ones: samples_0, samples_1, ...
        for i, path in enumerate(samples):
            tabular_sources.append(
                TabularSourceConfig(
                    name=f"samples_{i}",
                    path=str(path),
                    lon_col=lon_col,
                    lat_col=lat_col,
                    optional=True,
                )
            )
    else:
        # Original behavior: a single path, single source named "samples"
        tabular_sources.append(
            TabularSourceConfig(
                name="samples",
                path=str(samples),
                lon_col=lon_col,
                lat_col=lat_col,
                optional=True,
            )
        )

    return tabular_sources


def _build_config_from_args(
    dem,
    orthophoto,
    samples,
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
    """
    Build a PipelineConfig from simple function arguments.

    This allows run_pipeline() to be called with file paths
    directly instead of requiring a YAML config file.

    dem and orthophoto can each be a single path or a list of
    paths (multiple tiles to be merged into one raster).

    samples can be a single path, a list of paths, or a dict of
    {name: path} — see _build_tabular_sources() for details.
    """
    vector_sources = []
    if vectors:
        for name, path in vectors.items():
            vector_sources.append(
                VectorSourceConfig(name=name, path=str(path), optional=True)
            )

    raster_sources = []
    if dem:
        dem_path = [str(p) for p in dem] if isinstance(dem, list) else str(dem)
        raster_sources.append(
            RasterSourceConfig(name=dem_name, path=dem_path, optional=False)
        )
    if orthophoto:
        ortho_path = [str(p) for p in orthophoto] if isinstance(orthophoto, list) else str(orthophoto)
        raster_sources.append(
            RasterSourceConfig(name=orthophoto_name or "orthophoto",
                             path=ortho_path, optional=True)
        )

    tabular_sources = _build_tabular_sources(samples, lon_col, lat_col)

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
    # DEM/orthophoto tiles (if multiple were given) are merged
    # into one seamless raster here, before anything downstream
    # ever sees them. Multiple tabular sources are each loaded
    # and converted to point GeoDataFrames independently.
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

    # ── Stage 4: Geometry repair ──────────────────────────────
    # Must happen BEFORE clipping — clipping needs valid geometry
    # to work correctly. An invalid (self-crossing) layer would
    # crash gpd.clip() with a TopologyException before it ever
    # got a chance to be repaired.
    logger.info("Stage 4: Geometry validation and repair...")
    all_vectors = repair_geometries(all_vectors, config.geometry)

    # ── Stage 5: Clip to study area ──────────────────────────
    # SpatialHarmonizer also receives config.geometry, so the
    # study area's OWN boundary geometry is checked/repaired the
    # moment it's loaded — closing a gap discovered during
    # testing, where the study area could crash clipping with a
    # TopologyException, since it never went through
    # repair_geometries() like every other vector layer did.
    logger.info("Stage 5: Clipping to study area...")
    spatial = SpatialHarmonizer(config.spatial, config.geometry)
    all_vectors = spatial.clip_vectors(all_vectors)
    if all_rasters:
        all_rasters = spatial.clip_rasters(all_rasters)

    # ── Stage 6: Schema harmonization ────────────────────────
    logger.info("Stage 6: Schema harmonization...")
    all_source_configs = (
        list(config.vector_sources) + list(config.tabular_sources)
    )
    all_vectors = harmonize_schema(
        all_vectors, config.schema_config, all_source_configs
    )

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

    # ── Done ──────────────────────────────────────────────────
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
    dem: str | list[str] | None = None,
    orthophoto: str | list[str] | None = None,
    samples: str | list[str] | dict[str, str] | None = None,
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

    dem and orthophoto can each be a single path OR a list of
    paths. If a list is given, the tiles are merged into one
    seamless raster automatically.

    samples can now be:
      - a single path (string)  -> one source, named "samples"
      - a list of paths         -> auto-named samples_0, samples_1, ...
      - a dict of {name: path}  -> keeps the names you give it

    result = run_pipeline(
        dem     = r"path/to/dem.tif",
        samples = {
            "team_a": r"path/to/samples_teamA.csv",
            "team_b": r"path/to/samples_teamB.csv",
        },
        study_area = r"path/to/boundary.geojson",
    )

    Note: all tabular sources share the same lon_col/lat_col.
    If your files use genuinely different column names, build a
    PipelineConfig manually with per-source TabularSourceConfig
    objects instead.

    Pipeline stages:
        1. Validate   check files before loading
        2. Ingest     load all data sources (merge tiles if needed)
        3. CRS        reproject everything to WGS84
        4. Geometry   repair invalid geometries (incl. study area)
        5. Clip       clip to study area (required)
        6. Schema     standardize field names
        7. QA         data quality checks
        8. Save       export processed files

    Parameters
    ----------
    dem : str, list[str], optional
        Path (or list of tile paths) to DEM/elevation raster(s).
        Required for 3D visualization.

    orthophoto : str, list[str], optional
        Path (or list of tile paths) to satellite/aerial image(s).
        Textures the 3D terrain surface if provided.

    samples : str, list[str], dict[str, str], optional
        One or more CSV/Excel files with coordinate columns.
        See examples above.

    vectors : dict[str, str], optional
        Additional vector layers as {name: path}.
        Example: {"faults": r"path/to/faults.geojson"}

    study_area : str
        REQUIRED. Path to a polygon file defining the area of
        interest. All layers are clipped to this boundary.
        Accepts any CRS — reprojected automatically. The study
        area's own geometry is also validated/repaired
        automatically, using the same rules as every other
        vector layer.

    lon_col : str
        Longitude column name, shared across all tabular
        sources. Default: "longitude"

    lat_col : str
        Latitude column name, shared across all tabular
        sources. Default: "latitude"

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
    Single DEM tile, single sample file:

    >>> from geostack3d import run_pipeline
    >>> result = run_pipeline(
    ...     dem        = r"C:/data/dem.tif",
    ...     samples    = r"C:/data/samples.csv",
    ...     study_area = r"C:/data/boundary.geojson",
    ...     output_dir = r"C:/data/output",
    ... )

    Multiple DEM tiles AND multiple sample files:

    >>> result = run_pipeline(
    ...     dem     = [r"C:/data/dem_tile1.tif", r"C:/data/dem_tile2.tif"],
    ...     samples = {"team_a": r"C:/data/teamA.csv", "team_b": r"C:/data/teamB.csv"},
    ...     study_area = r"C:/data/boundary.geojson",
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
