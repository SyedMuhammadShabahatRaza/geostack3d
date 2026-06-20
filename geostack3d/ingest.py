# ============================================================
# geostack3d/ingest.py
# ============================================================
# PURPOSE:
#   Load all data sources into Python objects the pipeline
#   can work with.
#
# SUPPORTED FORMATS:
#   Vector  : GeoJSON, Shapefile, GeoPackage, KML, GML
#   Raster  : GeoTIFF, NetCDF, IMG
#   Tabular : CSV, Excel (.xlsx, .xls)
#
# OPTIONAL SOURCES:
#   Each source has an 'optional' flag in the config.
#   optional: true  → skip gracefully if file is missing
#   optional: false → stop pipeline if file is missing
#
#   This means the user never needs to comment out sources
#   in the config — just leave them in and if the file is
#   not present and optional=true, it is silently skipped.
#
# WHAT IT RETURNS:
#   vectors  → dict of GeoDataFrames (polygons, lines, points)
#   rasters  → dict of open rasterio datasets
#   tabulars → dict of GeoDataFrames (points from lat/lon)
#
# GEOLOGY ANALOGY:
#   Like unpacking sample boxes from the field. Different
#   containers (shapefiles, GeoTIFFs, CSVs) need different
#   tools to open, but the goal is the same: get the data
#   into a usable format for processing.
# ============================================================

from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from loguru import logger

from geostack3d.config import (
    PipelineConfig,
    VectorSourceConfig,
    RasterSourceConfig,
    TabularSourceConfig,
)


def _enable_kml_driver() -> None:
    """
    Enable KML/LIBKML drivers in Fiona.

    These drivers are disabled by default in some Fiona
    installations. Calling this ensures KML files from
    Google Earth, total stations, and DGPS devices can
    be read without any manual setup by the user.
    """
    try:
        import fiona
        fiona.drvsupport.supported_drivers["KML"] = "rw"
        fiona.drvsupport.supported_drivers["LIBKML"] = "rw"
    except Exception:
        pass  # fiona not available — geopandas will handle it


# ── Vector loading ───────────────────────────────────────────

def _load_one_vector(src: VectorSourceConfig) -> gpd.GeoDataFrame | None:
    """
    Load a single vector source.

    Returns None if the source is optional and file is missing.
    Raises FileNotFoundError if required and file is missing.
    """
    path = Path(src.path)

    if not path.exists():
        if src.optional:
            logger.warning(
                f"  [ingest] '{src.name}': file not found — "
                f"skipping (optional).\n"
                f"  Path: {src.path}"
            )
            return None
        raise FileNotFoundError(
            f"\n[ingest] Required vector file not found: {src.path}\n"
            f"Source name: '{src.name}'\n"
            f"Check the path in your config."
        )

    logger.info(f"  [ingest] Loading vector '{src.name}' from {path.name}")

    _enable_kml_driver()

    try:
        kwargs = {}
        if src.layer:
            kwargs["layer"] = src.layer
        gdf = gpd.read_file(str(path), **kwargs)
    except Exception as e:
        raise RuntimeError(
            f"\n[ingest] Could not read vector '{src.name}': {e}\n"
            f"File: {src.path}"
        ) from e

    if src.filter_expr:
        try:
            gdf = gdf.query(src.filter_expr).reset_index(drop=True)
            logger.info(
                f"  [ingest] Applied filter to '{src.name}': "
                f"{src.filter_expr}"
            )
        except Exception as e:
            raise ValueError(
                f"\n[ingest] Filter failed for '{src.name}': {e}\n"
                f"Expression: {src.filter_expr}"
            ) from e

    logger.info(
        f"  [ingest] '{src.name}': {len(gdf):,} features, "
        f"CRS={gdf.crs}"
    )
    return gdf


# ── Raster loading ───────────────────────────────────────────

def _load_one_raster(src: RasterSourceConfig) -> rasterio.DatasetReader | None:
    """
    Open a single raster file.

    Returns an open file handle — does NOT read all pixel data
    into memory. This is intentional: rasters can be gigabytes.
    Only the metadata is read here; pixel data is read on demand
    by later pipeline stages.

    Returns None if the source is optional and file is missing.
    """
    path = Path(src.path)

    if not path.exists():
        if src.optional:
            logger.warning(
                f"  [ingest] '{src.name}': file not found — "
                f"skipping (optional).\n"
                f"  Path: {src.path}"
            )
            return None
        raise FileNotFoundError(
            f"\n[ingest] Required raster file not found: {src.path}\n"
            f"Source name: '{src.name}'\n"
            f"Check the path in your config."
        )

    logger.info(f"  [ingest] Opening raster '{src.name}' from {path.name}")

    try:
        dataset = rasterio.open(str(path))
    except Exception as e:
        raise RuntimeError(
            f"\n[ingest] Could not open raster '{src.name}': {e}\n"
            f"File: {src.path}"
        ) from e

    logger.info(
        f"  [ingest] '{src.name}': {dataset.width}×{dataset.height} px, "
        f"{dataset.count} band(s), CRS={dataset.crs}"
    )
    return dataset


# ── Tabular loading ──────────────────────────────────────────

def _load_one_tabular(src: TabularSourceConfig) -> gpd.GeoDataFrame | None:
    """
    Load a CSV or Excel file with coordinate columns and convert
    to a GeoDataFrame of point geometries.

    Returns None if the source is optional and file is missing.
    """
    path = Path(src.path)

    if not path.exists():
        if src.optional:
            logger.warning(
                f"  [ingest] '{src.name}': file not found — "
                f"skipping (optional).\n"
                f"  Path: {src.path}"
            )
            return None
        raise FileNotFoundError(
            f"\n[ingest] Required tabular file not found: {src.path}\n"
            f"Source name: '{src.name}'\n"
            f"Check the path in your config."
        )

    logger.info(
        f"  [ingest] Loading tabular '{src.name}' from {path.name}"
    )

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(str(path))
        elif suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(str(path))
        else:
            raise ValueError(
                f"Unsupported tabular format: '{suffix}'\n"
                f"Supported: .csv, .xlsx, .xls"
            )
    except Exception as e:
        raise RuntimeError(
            f"\n[ingest] Could not read tabular '{src.name}': {e}"
        ) from e

    # Verify coordinate columns exist
    missing_cols = []
    if src.lon_col not in df.columns:
        missing_cols.append(f"longitude column '{src.lon_col}'")
    if src.lat_col not in df.columns:
        missing_cols.append(f"latitude column '{src.lat_col}'")

    if missing_cols:
        raise ValueError(
            f"\n[ingest] Missing columns in '{src.name}': "
            f"{', '.join(missing_cols)}\n"
            f"Available columns: {df.columns.tolist()}\n"
            f"Check 'lon_col' and 'lat_col' in your config."
        )

    try:
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df[src.lon_col], df[src.lat_col]),
            crs=f"EPSG:{src.crs_epsg}",
        )
    except Exception as e:
        raise RuntimeError(
            f"\n[ingest] Could not create geometry for '{src.name}': {e}"
        ) from e

    logger.info(
        f"  [ingest] '{src.name}': {len(gdf):,} point features, "
        f"CRS=EPSG:{src.crs_epsg}"
    )
    return gdf


# ── Public function ──────────────────────────────────────────

def load_all_sources(config: PipelineConfig) -> tuple[dict, dict, dict]:
    """
    Load all data sources defined in the pipeline config.

    Optional sources that are missing are skipped with a
    warning. Required sources that are missing raise an error.

    Parameters
    ----------
    config : PipelineConfig

    Returns
    -------
    tuple of three dicts:
        vectors  : name → GeoDataFrame
        rasters  : name → open rasterio dataset
        tabulars : name → GeoDataFrame (point geometries)

    Examples
    --------
    >>> vectors, rasters, tabulars = load_all_sources(config)
    >>> dem = rasters["dem"]
    >>> samples = tabulars["samples"]
    """
    logger.info("Stage 2: Ingesting data sources...")

    # Load each source type, filtering out None returns
    # (None means optional source was skipped)
    vectors = {}
    for src in config.vector_sources:
        result = _load_one_vector(src)
        if result is not None:
            vectors[src.name] = result

    rasters = {}
    for src in config.raster_sources:
        result = _load_one_raster(src)
        if result is not None:
            rasters[src.name] = result

    tabulars = {}
    for src in config.tabular_sources:
        result = _load_one_tabular(src)
        if result is not None:
            tabulars[src.name] = result

    total = len(vectors) + len(rasters) + len(tabulars)
    logger.info(
        f"  Ingestion complete: "
        f"{len(vectors)} vector, "
        f"{len(rasters)} raster, "
        f"{len(tabulars)} tabular "
        f"({total} total)"
    )

    return vectors, rasters, tabulars