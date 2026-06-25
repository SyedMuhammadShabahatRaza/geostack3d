# ============================================================
# geostack3d/crs.py
# ============================================================
# PURPOSE:
#   Make sure every layer uses the SAME coordinate reference
#   system (CRS). This is the single most important step in
#   any GIS pipeline.
#
# WHY THIS MATTERS (you already know this as a geologist):
#   If layer A is in WGS84 (degrees) and layer B is in UTM
#   (metres), overlaying them directly is meaningless — the
#   numbers don't mean the same thing. A point at (500000, 5000000)
#   in UTM is NOT the same location as (500000, 5000000) in WGS84
#   (that would be impossible — WGS84 only goes to 180 degrees).
#
#   Worse: sometimes the mismatch is SMALL enough that nothing
#   crashes, but your spatial join or overlay is just... wrong.
#   No error message. No warning. Just bad results. That is the
#   exact failure mode this file prevents.
#
# WHAT THIS FILE DOES:
#   1. Look at each layer's current CRS
#   2. If it doesn't match the "project CRS", reproject it
#   3. Sanity-check the result (catch obviously wrong coordinates)
# ============================================================

# geopandas — our main GIS data structure (GeoDataFrame)
import geopandas as gpd

# rasterio — used for reprojecting raster (grid) data
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling

# pyproj — handles the actual coordinate system math
from pyproj import CRS

# loguru — nicer logging than print()
from loguru import logger

# Our config class — tells us which EPSG code to use as the target
from geostack3d.config import CRSConfig


# ============================================================
# TEACHING NOTE: What is an EPSG code?
# ============================================================
# EPSG codes are just ID numbers for coordinate systems, kept
# in a public registry (like a periodic table, but for map
# projections). You already use these in QGIS/ArcGIS:
#
#   EPSG:4326   = WGS84            (GPS standard, degrees)
#   EPSG:32632  = UTM Zone 32N     (metres, central Europe)
#   EPSG:3857   = Web Mercator     (used by Google Maps, OSM)
#
# Anywhere you see "EPSG:xxxx" in this code, just think
# "the ID number of a coordinate system".
# ============================================================


def _sanity_check_wgs84(name: str, gdf: gpd.GeoDataFrame) -> None:
    """
    Check that coordinates make sense for WGS84 (degrees).

    WGS84 longitude must be between -180 and 180.
    WGS84 latitude must be between -90 and 90.

    If a layer claims to be WGS84 but has coordinates like
    (500000, 5000000), something is wrong upstream — probably
    someone forgot to set the correct CRS on the original file.

    This function doesn't fix anything. It just stops the
    pipeline early with a clear message, instead of letting
    a silently-wrong map get all the way to the end.

    Parameters
    ----------
    name : str
        Layer name, just for the error message.
    gdf : gpd.GeoDataFrame
        The layer to check (assumed to be in WGS84 already).
    """
    # .total_bounds returns (minx, miny, maxx, maxy) — the
    # bounding box of ALL geometries in the layer.
    # Think of it like the four corners of your study area.
    minx, miny, maxx, maxy = gdf.total_bounds

    # Check if any value falls outside the valid WGS84 range
    out_of_range = (
        minx < -180 or maxx > 180
        or miny < -90 or maxy > 90
    )

    if out_of_range:
        # f-strings (the f"..." syntax) let us insert variables
        # directly into a string using {curly braces}
        raise ValueError(
            f"Layer '{name}' claims to be in WGS84 (EPSG:4326) but "
            f"has coordinates outside the valid range: "
            f"({minx:.2f}, {miny:.2f}, {maxx:.2f}, {maxy:.2f}).\n"
            "This usually means the original file has the WRONG CRS "
            "assigned. Check the source file's .prj or metadata."
        )


def harmonize_crs(
    vectors: dict[str, gpd.GeoDataFrame],
    config: CRSConfig,
) -> dict[str, gpd.GeoDataFrame]:
    """
    Reproject every vector layer to the project CRS.

    Parameters
    ----------
    vectors : dict[str, GeoDataFrame]
        Layer name → GeoDataFrame, as returned by load_all_sources().
    config : CRSConfig
        Tells us which EPSG code to reproject everything to.

    Returns
    -------
    dict[str, GeoDataFrame]
        Same layer names, but all now in the same CRS.

    Examples
    --------
    >>> vectors = {"formations": gdf1, "boreholes": gdf2}
    >>> result = harmonize_crs(vectors, config.crs)
    >>> result["formations"].crs
    <Geographic 2D CRS: EPSG:4326>
    """
    logger.info("Stage 2: Harmonizing coordinate systems...")

    # Build a CRS object from the target EPSG code in the config.
    # We do this ONCE outside the loop — no need to rebuild it
    # for every layer.
    target_crs = CRS.from_epsg(config.project_epsg)

    # This dictionary will hold our reprojected layers.
    # We build it up one layer at a time inside the loop below.
    result: dict[str, gpd.GeoDataFrame] = {}

    # .items() lets us loop through a dictionary and get
    # BOTH the key (name) and value (gdf) at once.
    for name, gdf in vectors.items():

        # ── Check 1: does this layer even have a CRS? ───────
        # Some files (especially CSVs converted to points) might
        # not have a CRS set. We can't reproject "nothing" — we
        # need to know the STARTING point first.
        if gdf.crs is None:
            raise ValueError(
                f"Layer '{name}' has no CRS defined.\n"
                "Set 'crs_epsg' in the config for this source."
            )

        # ── Check 2: is it already in the target CRS? ───────
        # No point doing expensive reprojection math if the
        # layer is already correct. This also avoids tiny
        # floating-point rounding differences from creeping in
        # for no reason.
        if gdf.crs == target_crs:
            logger.info(f"  '{name}' already in EPSG:{config.project_epsg} — skipping.")
            result[name] = gdf
            continue   # 'continue' skips to the next loop iteration

        # ── Do the actual reprojection ───────────────────────
        # .to_crs() is a geopandas method that transforms every
        # coordinate in the GeoDataFrame to the new CRS.
        # This is the same operation as "Reproject Layer" in QGIS.
        original_epsg = gdf.crs.to_epsg()
        logger.info(
            f"  Reprojecting '{name}': "
            f"EPSG:{original_epsg} → EPSG:{config.project_epsg}"
        )

        try:
            reprojected = gdf.to_crs(target_crs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to reproject layer '{name}': {e}"
            ) from e

        # ── Sanity check (only meaningful for WGS84) ─────────
        # If we just reprojected INTO WGS84, double check the
        # numbers actually look like degrees.
        if config.project_epsg == 4326:
            _sanity_check_wgs84(name, reprojected)

        result[name] = reprojected

    logger.info(f"  CRS harmonization complete: {len(result)} layer(s) processed.")
    return result


def harmonize_raster_crs(
    rasters: dict[str, rasterio.DatasetReader],
    config: CRSConfig,
) -> dict[str, rasterio.MemoryFile]:
    """
    Reproject every raster dataset to the project CRS.

    Unlike vectors, rasters store data as a grid of pixels.
    Reprojecting a raster means recalculating the VALUE of every
    pixel in the new grid — this is more expensive than vector
    reprojection (which just moves coordinate numbers).

    We use rasterio.MemoryFile to hold the reprojected raster
    IN MEMORY rather than writing a temporary file to disk —
    faster, and avoids leftover files cluttering your folders.

    Parameters
    ----------
    rasters : dict[str, rasterio.DatasetReader]
        Layer name → open raster dataset.
    config : CRSConfig

    Returns
    -------
    dict[str, rasterio.MemoryFile]
        Reprojected rasters, held in memory.
        Caller is responsible for closing these when done
        (or use them inside a `with` block).
    """
    target_crs = rasterio.crs.CRS.from_epsg(config.project_epsg)
    result: dict[str, rasterio.MemoryFile] = {}

    for name, src in rasters.items():

        if src.crs == target_crs:
            logger.info(f"  Raster '{name}' already in EPSG:{config.project_epsg} — skipping.")
            # Even when skipping, we still wrap it in a MemoryFile
            # so the OUTPUT TYPE is always consistent (always a
            # MemoryFile, never sometimes-this sometimes-that).
            memfile = rasterio.MemoryFile()
            with memfile.open(**src.profile) as dst:
                dst.write(src.read())
            result[name] = memfile
            continue

        original_epsg = src.crs.to_epsg() if src.crs else "unknown"
        logger.info(
            f"  Reprojecting raster '{name}': "
            f"EPSG:{original_epsg} → EPSG:{config.project_epsg}"
        )

        # calculate_default_transform works out the new grid size
        # and transform (the math that converts pixel row/col to
        # real-world coordinates) needed for the new CRS.
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds
        )

        # .profile is a dictionary of all the raster's metadata
        # (size, datatype, number of bands, etc.) — we copy it
        # and update only the parts that change with reprojection.
        new_profile = src.profile.copy()
        new_profile.update(
            crs=target_crs,
            transform=transform,
            width=width,
            height=height,
        )

        memfile = rasterio.MemoryFile()
        with memfile.open(**new_profile) as dst:
            # Rasters can have multiple bands (e.g. RGB has 3).
            # We loop through each band and reproject it separately.
            for band_index in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band_index),
                    destination=rasterio.band(dst, band_index),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    # bilinear = smooth interpolation, good default
                    # for continuous data like elevation
                    resampling=Resampling.bilinear,
                )

        result[name] = memfile
        logger.info(f"  Raster '{name}' reprojected successfully.")

    return result
