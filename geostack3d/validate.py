# ============================================================
# geostack3d/validate.py
# ============================================================
# PURPOSE:
#   Check every input file BEFORE the pipeline starts loading
#   data. This is a "fail fast" approach — catch problems
#   immediately with clear messages rather than crashing
#   mid-process with cryptic library errors.
#
# WHAT IT CHECKS:
#   1. Does the file exist at the given path?
#   2. Is the file non-empty (not 0 bytes)?
#   3. Does the file extension match a supported format?
#   4. For rasters: can rasterio actually open the file?
#   5. For vectors: can geopandas actually read the file?
#   6. For tabular: does the file have the expected lat/lon columns?
#   7. Is the DEM present when 3D visualization is requested?
#
# WHY THIS MATTERS:
#   A DEM file can exist on disk but be corrupted, truncated,
#   or in an unsupported sub-format. Checking before loading
#   means the user sees a clear error in 1 second instead of
#   a confusing traceback after 30 seconds of processing.
# ============================================================

from pathlib import Path
from loguru import logger


# ── Supported formats ────────────────────────────────────────

VECTOR_EXTENSIONS = {".geojson", ".json", ".shp", ".gpkg", ".kml", ".gml"}
RASTER_EXTENSIONS = {".tif", ".tiff", ".geotiff", ".nc", ".img"}
TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xls"}


# ── Individual file checks ───────────────────────────────────

def check_file_exists(path: str, source_name: str) -> None:
    """
    Check a file exists and is not empty.

    Parameters
    ----------
    path : str
        File path from the config.
    source_name : str
        Layer name — used in the error message so the user
        knows exactly which config entry is wrong.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file exists but is empty (0 bytes).
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(
            f"\n[{source_name}] File not found: {path}\n"
            f"Check the path in your config. Make sure the file\n"
            f"is in the correct folder and the filename matches exactly."
        )

    if p.stat().st_size == 0:
        raise ValueError(
            f"\n[{source_name}] File is empty (0 bytes): {path}\n"
            f"The file exists but contains no data. It may be\n"
            f"corrupted or failed to download completely."
        )

    logger.debug(f"  [validate] '{source_name}': file exists ({p.stat().st_size / 1024:.1f} KB)")


def check_extension(path: str, source_name: str, expected: set) -> None:
    """
    Check the file extension is a supported format.

    Parameters
    ----------
    path : str
    source_name : str
    expected : set
        Set of allowed extensions (e.g. {".tif", ".tiff"}).

    Raises
    ------
    ValueError
        If the extension is not in the supported set.
    """
    suffix = Path(path).suffix.lower()

    if suffix not in expected:
        raise ValueError(
            f"\n[{source_name}] Unsupported file format: '{suffix}'\n"
            f"Supported formats: {sorted(expected)}\n"
            f"File: {path}"
        )


def check_raster_readable(path: str, source_name: str) -> dict:
    """
    Try to open a raster file with rasterio and read its metadata.

    This catches corrupted files, wrong formats, and missing
    projection information — all without loading the actual
    pixel data (which could be gigabytes).

    Parameters
    ----------
    path : str
    source_name : str

    Returns
    -------
    dict
        Basic metadata: width, height, band count, CRS, nodata.

    Raises
    ------
    RuntimeError
        If rasterio cannot open the file.
    """
    try:
        import rasterio
        with rasterio.open(path) as src:
            info = {
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "crs": str(src.crs),
                "nodata": src.nodata,
            }
        logger.debug(
            f"  [validate] '{source_name}': raster OK "
            f"({info['width']}×{info['height']} px, "
            f"{info['bands']} band(s), CRS={info['crs']})"
        )
        return info
    except Exception as e:
        raise RuntimeError(
            f"\n[{source_name}] Cannot open raster file: {path}\n"
            f"Reason: {e}\n"
            f"The file may be corrupted or in an unsupported format."
        ) from e


def check_vector_readable(path: str, source_name: str) -> dict:
    """
    Try to open a vector file with geopandas and read its metadata.

    Parameters
    ----------
    path : str
    source_name : str

    Returns
    -------
    dict
        Basic metadata: feature count, geometry type, CRS, columns.

    Raises
    ------
    RuntimeError
        If geopandas cannot read the file.
    """
    try:
        import geopandas as gpd
        import fiona

        # Enable KML driver if needed
        fiona.drvsupport.supported_drivers["KML"] = "rw"
        fiona.drvsupport.supported_drivers["LIBKML"] = "rw"

        gdf = gpd.read_file(path)
        info = {
            "features": len(gdf),
            "geometry_type": gdf.geom_type.unique().tolist() if len(gdf) > 0 else ["empty"],
            "crs": str(gdf.crs),
            "columns": gdf.columns.tolist(),
        }
        logger.debug(
            f"  [validate] '{source_name}': vector OK "
            f"({info['features']} features, "
            f"type={info['geometry_type']}, CRS={info['crs']})"
        )
        return info
    except Exception as e:
        raise RuntimeError(
            f"\n[{source_name}] Cannot read vector file: {path}\n"
            f"Reason: {e}\n"
            f"The file may be corrupted or in an unsupported format."
        ) from e


def check_tabular_readable(
    path: str,
    source_name: str,
    lon_col: str,
    lat_col: str,
) -> dict:
    """
    Try to read a CSV/Excel file and check coordinate columns exist.

    Parameters
    ----------
    path : str
    source_name : str
    lon_col : str
        Expected longitude column name.
    lat_col : str
        Expected latitude column name.

    Returns
    -------
    dict
        Basic metadata: row count, column names.

    Raises
    ------
    RuntimeError
        If the file cannot be read.
    ValueError
        If coordinate columns are missing.
    """
    try:
        import pandas as pd
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(path, nrows=5)  # only read first 5 rows for validation
        else:
            df = pd.read_excel(path, nrows=5)

        info = {
            "columns": df.columns.tolist(),
        }

        # Check coordinate columns exist
        missing = []
        if lon_col not in df.columns:
            missing.append(f"longitude column '{lon_col}'")
        if lat_col not in df.columns:
            missing.append(f"latitude column '{lat_col}'")

        if missing:
            raise ValueError(
                f"\n[{source_name}] Missing coordinate columns: {', '.join(missing)}\n"
                f"Available columns: {df.columns.tolist()}\n"
                f"Check 'lon_col' and 'lat_col' in your config."
            )

        logger.debug(
            f"  [validate] '{source_name}': tabular OK "
            f"(columns: {info['columns']})"
        )
        return info

    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"\n[{source_name}] Cannot read tabular file: {path}\n"
            f"Reason: {e}"
        ) from e


# ── Main validation function ─────────────────────────────────

def validate_all_sources(config) -> None:
    """
    Validate every source file defined in the config before
    the pipeline attempts to load any of them.

    Optional sources (optional: true) that are missing are
    skipped with a warning instead of raising an error.
    Required sources (optional: false) that are missing stop
    the pipeline immediately.

    Parameters
    ----------
    config : PipelineConfig

    Raises
    ------
    ValueError
        If any required source file has a problem.
    """
    logger.info("Pre-flight: Validating all source files...")

    errors = []
    skipped = []

    def _validate_source(src, check_fn, source_type):
        """Helper: validate one source, respecting optional flag."""
        path = Path(src.path)
        if not path.exists():
            if src.optional:
                skipped.append(src.name)
                logger.warning(
                    f"  [validate] '{src.name}': file not found — "
                    f"skipping (optional=true).\n"
                    f"  Path: {src.path}"
                )
                return False  # signal: skip this source
            else:
                errors.append(
                    f"[{src.name}] Required file not found: {src.path}"
                )
                return False
        try:
            check_file_exists(src.path, src.name)
            check_extension(src.path, src.name,
                          VECTOR_EXTENSIONS if source_type == "vector"
                          else RASTER_EXTENSIONS if source_type == "raster"
                          else TABULAR_EXTENSIONS)
            check_fn(src.path, src.name)
            return True  # signal: load this source
        except Exception as e:
            errors.append(str(e))
            return False

    # ── Validate vector sources ──────────────────────────────
    for src in config.vector_sources:
        _validate_source(src, check_vector_readable, "vector")

    # ── Validate raster sources ──────────────────────────────
    for src in config.raster_sources:
        _validate_source(src, check_raster_readable, "raster")

    # ── Validate tabular sources ─────────────────────────────
    for src in config.tabular_sources:
        def check_tabular(path, name):
            check_tabular_readable(path, name, src.lon_col, src.lat_col)
        _validate_source(src, check_tabular, "tabular")

    # ── Validate study area (always optional) ────────────────
    if config.spatial.study_area_path:
        sa_path = Path(config.spatial.study_area_path)
        if not sa_path.exists():
            logger.warning(
                f"  [validate] 'study_area': file not found — "
                f"skipping clipping.\n"
                f"  Path: {config.spatial.study_area_path}\n"
                f"  Note: without a study area, the full extent\n"
                f"  of each dataset will be processed."
            )
        else:
            try:
                check_file_exists(config.spatial.study_area_path, "study_area")
                check_extension(config.spatial.study_area_path, "study_area", VECTOR_EXTENSIONS)
                check_vector_readable(config.spatial.study_area_path, "study_area")
            except Exception as e:
                errors.append(str(e))

    # ── Warn if DEM missing (3D won't work) ──────────────────
    raster_names = [src.name for src in config.raster_sources]
    dem_name = config.visualization.dem_name
    if dem_name not in raster_names:
        logger.warning(
            f"\n[WARNING] No raster source named '{dem_name}' found.\n"
            f"3D visualization requires elevation data.\n"
            f"Add a raster source with name: '{dem_name}' to enable 3D output.\n"
            f"Pipeline will continue but 3D scene cannot be generated."
        )

    # ── Summary ──────────────────────────────────────────────
    if skipped:
        logger.info(f"  Skipped {len(skipped)} optional source(s): {skipped}")

    if errors:
        error_summary = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(errors))
        raise ValueError(
            f"\nValidation failed — {len(errors)} problem(s) found:\n"
            f"{error_summary}\n\n"
            f"Fix the above issues and try again."
        )

    logger.info("  Pre-flight complete: all required sources validated.")