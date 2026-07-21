# ============================================================
# geostack3d/validate.py
# ============================================================
from pathlib import Path
from loguru import logger


# ── Supported formats ────────────────────────────────────────

VECTOR_EXTENSIONS = {".geojson", ".json", ".shp", ".gpkg", ".kml", ".kmz", ".gml"}
RASTER_EXTENSIONS = {".tif", ".tiff", ".geotiff", ".nc", ".img"}
TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xls"}


# ── Individual file checks ───────────────────────────────────

def check_file_exists(path: str, source_name: str) -> None:
    """Check a file exists and is not empty."""
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
    """Check the file extension is a supported format."""
    suffix = Path(path).suffix.lower()

    if suffix not in expected:
        raise ValueError(
            f"\n[{source_name}] Unsupported file format: '{suffix}'\n"
            f"Supported formats: {sorted(expected)}\n"
            f"File: {path}"
        )


def check_raster_readable(path: str, source_name: str) -> dict:
    """Try to open a raster file with rasterio and read its metadata."""
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
    """Try to open a vector file with geopandas and read its metadata."""
    try:
        import geopandas as gpd
        import fiona

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
    """Try to read a CSV/Excel file and check coordinate columns exist."""
    try:
        import pandas as pd
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(path, nrows=5)
        else:
            df = pd.read_excel(path, nrows=5)

        info = {"columns": df.columns.tolist()}

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
    the pipeline immediately. The study area is always
    required — see PipelineConfig.study_area_required.
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
                return False
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
            return True
        except Exception as e:
            errors.append(str(e))
            return False

    for src in config.vector_sources:
        _validate_source(src, check_vector_readable, "vector")

    for src in config.raster_sources:
        _validate_source(src, check_raster_readable, "raster")

    for src in config.tabular_sources:
        def check_tabular(path, name):
            check_tabular_readable(path, name, src.lon_col, src.lat_col)
        _validate_source(src, check_tabular, "tabular")

    # ── Validate study area (REQUIRED, not optional) ─────────
    # PipelineConfig.study_area_required already guarantees
    # study_area_path is set by the time we get here — this
    # check confirms the file it points to actually exists and
    # is readable. Unlike other sources, a missing/broken study
    # area is a hard error, not a warning: without it, the
    # pipeline would fall back to processing a raster at full
    # extent, which is slow and memory-intensive.
    sa_path = Path(config.spatial.study_area_path)
    if not sa_path.exists():
        errors.append(
            f"[study_area] Required file not found: {config.spatial.study_area_path}"
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