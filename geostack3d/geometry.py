# ============================================================
# geostack3d/geometry.py
# ============================================================
# PURPOSE:
#   Find broken/invalid geometries and fix them automatically.
#   Also fixes self-crossing LINES, which are a genuinely
#   different problem from invalid polygons (see below).
#
# WHAT IS AN "INVALID" GEOMETRY?
#   A geometry that breaks the mathematical rules of what a
#   shape is allowed to look like. Common real-world causes:
#     - A polygon ring that crosses itself (self-intersection)
#     - A polygon ring that isn't closed (start != end point)
#     - Duplicate points stacked on top of each other
#     - A "hole" in a polygon that pokes outside its boundary
#
#   You've probably hit these in QGIS: "Fix Geometries" tool,
#   or an error when running an overlay: "TopologyException".
#   This file automates exactly that fixing step.
#
# WHY DOES IT MATTER?
#   Running spatial operations (intersect, buffer, area calc)
#   on an invalid geometry can give WRONG results without any
#   error message. Sometimes it crashes. Either way — bad.
#
# GEOLOGY ANALOGY:
#   Like checking that every digitized fault polygon actually
#   closes properly before you calculate its area. A polygon
#   that doesn't close isn't really a polygon — it's a typo.
#
# ── A SEPARATE PROBLEM: SELF-CROSSING LINES ──────────────────
#   For a LineString, self-crossing is NOT a validity violation
#   under OGC rules — is_valid can report True even when a line
#   crosses itself (a line has no "inside/outside" concept, so
#   the rules that make self-crossing invalid for a Polygon
#   simply don't apply). BUT an un-noded self-crossing line can
#   still crash clip operations, because overlay algorithms
#   (used by gpd.clip()) require every crossing point to be
#   explicitly registered as a vertex — a requirement that
#   is_valid never checks.
#
#   Shapely's .is_simple property is the correct check for
#   this: a LineString is "simple" if it does NOT self-cross.
#   This file checks is_simple separately from is_valid, and
#   "nodes" any self-crossing line using unary_union() — which
#   splits it into a MultiLineString with an explicit vertex at
#   every crossing point, making it safe to clip.
# ============================================================

import geopandas as gpd

# shapely is the library that defines what a "point", "line"
# and "polygon" actually are, and the math rules they follow.
# make_valid() is shapely's built-in repair function.
from shapely import make_valid

# unary_union() is used here for a DIFFERENT purpose than a
# typical "merge multiple shapes" union — for a single
# self-crossing line, it nodes the geometry at every crossing
# point, splitting it into a MultiLineString with no unmarked
# intersections left.
from shapely.ops import unary_union

# explain_validity() tells us WHY a geometry is invalid —
# useful for logging/debugging, not for the fix itself.
from shapely.validation import explain_validity

from loguru import logger

from geostack3d.config import GeometryConfig


# ============================================================
# TEACHING NOTE: .apply() — running a function on every row
# ============================================================
# You'll see gdf["geometry"].apply(some_function) below.
# .apply() takes a function and runs it on EVERY value in a
# column, one at a time, and collects the results.
#
# It's the GeoDataFrame equivalent of a for-loop, but shorter:
#
#   for i, geom in enumerate(gdf["geometry"]):
#       gdf["geometry"][i] = some_function(geom)
#
# .apply() does the same thing in one line.
# ============================================================


def _repair_one_geometry(geom):
    """
    Attempt to fix a single invalid geometry.

    Parameters
    ----------
    geom : shapely geometry or None

    Returns
    -------
    A repaired shapely geometry.
    """
    try:
        # make_valid() restructures the geometry to follow
        # the rules properly. For a self-intersecting polygon
        # (a "bowtie" shape), it usually splits it into a
        # MultiPolygon of the two valid halves.
        return make_valid(geom)
    except Exception:
        # Fallback for older/edge-case geometries:
        # buffering by 0 distance is a classic trick that
        # forces shapely to rebuild the geometry cleanly.
        # (You may recognize this trick from ArcGIS forums too.)
        return geom.buffer(0)


def _node_line_if_self_crossing(geom):
    """
    Check a single geometry for self-crossing (only meaningful
    for LineString/MultiLineString) and "node" it if needed.

    This is checked INDEPENDENTLY of is_valid, since a
    self-crossing line can be perfectly valid under OGC rules
    while still being unsafe to clip. See module docstring for
    the full explanation.

    Parameters
    ----------
    geom : shapely geometry or None

    Returns
    -------
    The original geometry, unchanged, if it's not a line type
    or doesn't self-cross. A noded MultiLineString if it does.
    """
    if geom is None:
        return geom

    if geom.geom_type not in ("LineString", "MultiLineString"):
        return geom  # only lines can have this specific problem

    if geom.is_simple:
        return geom  # no self-crossing — nothing to do

    # unary_union() on a single self-crossing line finds every
    # crossing point and inserts an explicit vertex there,
    # splitting the result into a MultiLineString with no
    # unmarked intersections left.
    return unary_union(geom)


def repair_geometries(
    vectors: dict[str, gpd.GeoDataFrame],
    config: GeometryConfig,
) -> dict[str, gpd.GeoDataFrame]:
    """
    Check every vector layer for invalid/null geometries and
    fix what can be fixed. Also checks lines for self-crossing
    (a separate concern from validity — see module docstring)
    and automatically nodes them so they're safe to clip.

    Parameters
    ----------
    vectors : dict[str, GeoDataFrame]
    config : GeometryConfig
        Settings: auto_repair, drop_null_geometries, validity_threshold.

    Returns
    -------
    dict[str, GeoDataFrame]
        Same layer names, with geometries cleaned.

    Raises
    ------
    ValueError
        If a layer's validity rate is still below the configured
        threshold after attempting repairs (or if auto_repair is
        off and invalid geometries are found at all).

    Examples
    --------
    >>> result = repair_geometries(vectors, config.geometry)
    >>> result["formations"].geometry.is_valid.all()
    True
    """
    logger.info("Stage 4: Validating and repairing geometries...")

    result: dict[str, gpd.GeoDataFrame] = {}

    for name, gdf in vectors.items():

        # Work on a COPY, not the original.
        # Without .copy(), changes below would also silently
        # modify the GeoDataFrame the caller passed in — a classic
        # Python "gotcha" with mutable objects. Always copy before
        # editing data you didn't create yourself.
        gdf = gdf.copy()
        rows_before = len(gdf)

        # ── Step 1: drop null/empty geometries ───────────────
        # A null geometry is a row where .geometry is None —
        # e.g. a CSV row where the coordinate parsing failed.
        if config.drop_null_geometries:
            # .isna() returns True/False for each row.
            # .is_empty also catches "empty" geometries
            # (technically not None, but containing no points).
            is_missing = gdf.geometry.isna() | gdf.geometry.is_empty
            n_missing = is_missing.sum()   # True counts as 1, sums them up

            if n_missing > 0:
                logger.warning(f"  '{name}': dropping {n_missing} null/empty geometries.")
                # The ~ symbol means "NOT" — so this keeps only
                # rows where is_missing is False.
                gdf = gdf[~is_missing].copy()

        # ── Step 2: find invalid geometries ──────────────────
        # .is_valid checks EVERY geometry against shapely's rules
        # and returns True/False for each row.
        is_invalid = ~gdf.geometry.is_valid
        n_invalid = is_invalid.sum()

        if n_invalid > 0:
            if config.auto_repair:
                logger.warning(
                    f"  '{name}': found {n_invalid} invalid geometries — repairing."
                )

                # Log WHY a couple of them are broken — helpful
                # for understanding your own data over time.
                examples = gdf.loc[is_invalid, "geometry"].head(2)
                for geom in examples:
                    logger.debug(f"    Reason: {explain_validity(geom)}")

                # Apply the repair function only to the broken rows.
                # .loc[is_invalid, "geometry"] selects just those rows'
                # geometry column, and we overwrite them with the
                # repaired versions.
                gdf.loc[is_invalid, "geometry"] = (
                    gdf.loc[is_invalid, "geometry"].apply(_repair_one_geometry)
                )
            else:
                # If auto_repair is turned off in the config, we
                # stop here instead of silently continuing with
                # broken data.
                raise ValueError(
                    f"Layer '{name}' has {n_invalid} invalid geometries "
                    "and auto_repair is disabled in config.\n"
                    "Either fix the source data, or set "
                    "geometry.auto_repair: true in your YAML config."
                )

        # ── Step 3: node self-crossing lines ─────────────────
        # This is a SEPARATE check from is_valid (Step 2 above).
        # A self-crossing LineString can be perfectly valid under
        # OGC rules, but still crash clip operations later if its
        # crossing point isn't explicitly registered as a vertex.
        # See module docstring for the full explanation.
        is_line_type = gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])
        if is_line_type.any():
            is_non_simple = ~gdf.loc[is_line_type, "geometry"].is_simple
            n_self_crossing = is_non_simple.sum()

            if n_self_crossing > 0:
                logger.warning(
                    f"  '{name}': found {n_self_crossing} self-crossing "
                    "line(s) — noding to make clip-safe."
                )
                crossing_idx = is_non_simple[is_non_simple].index
                gdf.loc[crossing_idx, "geometry"] = (
                    gdf.loc[crossing_idx, "geometry"].apply(_node_line_if_self_crossing)
                )

        # ── Step 4: final validity check ──────────────────────
        # Even after repair, double-check the result. Sometimes
        # repair can't fully fix extremely broken geometries.
        valid_rate = gdf.geometry.is_valid.mean()  # mean of True/False = % valid
        logger.info(
            f"  '{name}': validity rate = {valid_rate:.1%} "
            f"(threshold {config.validity_threshold:.1%})"
        )

        if valid_rate < config.validity_threshold:
            raise ValueError(
                f"Layer '{name}' validity rate ({valid_rate:.1%}) is below "
                f"the required threshold ({config.validity_threshold:.1%}) "
                "even after repair attempts.\n"
                "This usually means the source data has serious problems "
                "— inspect it manually in QGIS."
            )

        rows_after = len(gdf)
        if rows_after < rows_before:
            logger.info(f"  '{name}': {rows_before} → {rows_after} rows after cleanup.")

        result[name] = gdf

    logger.info(f"  Geometry repair complete: {len(result)} layer(s) processed.")
    return result