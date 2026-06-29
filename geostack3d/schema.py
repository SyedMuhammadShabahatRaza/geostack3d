# ============================================================
# geostack3d/schema.py
# ============================================================
# PURPOSE:
#   Make every layer use the SAME field (column) names and
#   data types, even if the original sources used different
#   naming conventions.
#
# WHY THIS MATTERS:
#   Imagine 3 borehole datasets from 3 different contractors:
#     File A: "POP_2020"
#     File B: "population"
#     File C: "Pop"
#   These all mean the same thing, but if you try to join or
#   compare them as-is, Python sees three UNRELATED columns.
#   You'd get blank/NaN results with no warning — a silent bug.
#
#   This file solves that with a "field_map" — a dictionary
#   that says "rename THIS column to THAT canonical name."
#
# GEOLOGY ANALOGY:
#   Like standardizing lithology codes across 10 borehole logs
#   where one log says "Ss", another says "SANDSTONE", another
#   says "sand" — you map them all to one standard term so you
#   can actually query/compare across the whole dataset.
# ============================================================

import geopandas as gpd
import pandas as pd

from loguru import logger

from geostack3d.config import SchemaConfig, VectorSourceConfig, TabularSourceConfig


# ============================================================
# TEACHING NOTE: dict.get() with a default value
# ============================================================
# my_dict.get(key, default) looks up `key` in the dictionary.
# If the key exists, it returns the value. If the key does NOT
# exist, instead of crashing, it returns `default`.
#
#   ages = {"sandstone": 145}
#   ages.get("sandstone", 0)   -> 145  (found it)
#   ages.get("granite", 0)     -> 0    (not found, use default)
#
# This is much safer than ages["granite"], which would crash
# with a KeyError if "granite" isn't in the dictionary.
# We use this pattern below to safely look up field_maps.
# ============================================================


# Maps our config's simple type names ("int", "str", etc.)
# to the actual pandas dtype strings pandas understands.
# This is just a translation table — nothing clever happening.
_DTYPE_MAP = {
    "str": "object",          # text
    "int": "Int64",           # whole numbers (capital I allows missing values!)
    "float": "float64",       # decimal numbers
    "datetime": "datetime64[ns]",   # dates/times
}


def _rename_fields(
    gdf: gpd.GeoDataFrame,
    field_map: dict[str, str],
    layer_name: str,
) -> gpd.GeoDataFrame:
    """
    Rename columns according to the field_map.

    Parameters
    ----------
    gdf : GeoDataFrame
    field_map : dict
        {"old_name": "new_name", ...}
    layer_name : str
        Just used for logging.

    Returns
    -------
    GeoDataFrame with renamed columns.
    """
    if not field_map:
        # Nothing to rename — return unchanged.
        # (An empty dict {} is "falsy" in Python, so "if not field_map"
        # is True when the dict is empty.)
        return gdf

    # .rename(columns=...) is the standard pandas way to rename
    # columns. It only renames columns that exist — if a key in
    # field_map doesn't match any column, it's silently ignored
    # (not an error, just a no-op for that one entry).
    renamed = gdf.rename(columns=field_map)
    logger.info(f"  '{layer_name}': applied field rename {field_map}")
    return renamed


def _normalize_text_columns(gdf: gpd.GeoDataFrame, encoding: str) -> gpd.GeoDataFrame:
    """
    Clean up text columns: strip whitespace, fix encoding.

    Real-world data is messy — "Sandstone  " (trailing spaces)
    and "Sandstone" should be treated as the same value, but
    Python sees them as different strings until we clean them.

    Parameters
    ----------
    gdf : GeoDataFrame
    encoding : str
        Text encoding to normalize to (almost always "utf-8").

    Returns
    -------
    GeoDataFrame with cleaned text columns.
    """
    # select_dtypes picks out only the columns of a certain type.
    # "object" dtype in pandas usually means "text" (strings).
    text_columns = gdf.select_dtypes(include="object").columns

    for col in text_columns:
        # Never touch the geometry column even if pandas thinks
        # it's "object" dtype — geometry columns hold shapely
        # objects, not text, and .str operations would break them.
        if col == gdf.geometry.name:
            continue

        # .str lets us run string operations on an entire column
        # at once, instead of looping row by row.
        # .strip() removes leading/trailing whitespace
        gdf[col] = gdf[col].astype(str).str.strip()

    return gdf


def _coerce_column_type(
    gdf: gpd.GeoDataFrame,
    column: str,
    target_type: str,
    layer_name: str,
) -> gpd.GeoDataFrame:
    """
    Convert one column to its canonical data type.

    Parameters
    ----------
    gdf : GeoDataFrame
    column : str
        Column name to convert.
    target_type : str
        One of: "str", "int", "float", "datetime"
    layer_name : str
        Just for error messages.

    Returns
    -------
    GeoDataFrame with the column converted.
    """
    try:
        if target_type == "datetime":
            # pd.to_datetime is smarter than a plain .astype()
            # for dates — it understands many date formats.
            # errors="coerce" means: if a value can't be parsed
            # as a date, turn it into NaT (pandas' "missing date")
            # instead of crashing the whole pipeline.
            gdf[column] = pd.to_datetime(gdf[column], errors="coerce")
        else:
            target_dtype = _DTYPE_MAP[target_type]
            gdf[column] = gdf[column].astype(target_dtype)

    except Exception as e:
        raise ValueError(
            f"Layer '{layer_name}': could not convert column "
            f"'{column}' to type '{target_type}': {e}\n"
            "Check for unexpected text values in a numeric column "
            "(e.g. 'N/A' instead of a blank cell)."
        ) from e

    return gdf


def harmonize_schema(
    vectors: dict[str, gpd.GeoDataFrame],
    config: SchemaConfig,
    source_configs: list[VectorSourceConfig | TabularSourceConfig],
) -> dict[str, gpd.GeoDataFrame]:
    """
    Rename fields and fix data types across all layers.

    Parameters
    ----------
    vectors : dict[str, GeoDataFrame]
    config : SchemaConfig
        canonical_fields, drop_extra_fields, encoding settings.
    source_configs : list
        The original source configs (vector_sources + tabular_sources)
        — we need these to look up each layer's field_map.

    Returns
    -------
    dict[str, GeoDataFrame]

    Examples
    --------
    >>> result = harmonize_schema(vectors, config.schema, all_sources)
    >>> result["formations"].columns
    Index(['formation', 'population', 'geometry'], dtype='object')
    """
    logger.info("Stage 4: Harmonizing field names and types...")

    # Build a quick lookup: layer name -> its field_map.
    # This dict comprehension loops through every source config
    # and pulls out just the name and field_map we need.
    field_maps = {src.name: src.field_map for src in source_configs}

    result: dict[str, gpd.GeoDataFrame] = {}

    for name, gdf in vectors.items():
        gdf = gdf.copy()   # never edit the caller's original data

        # ── Step 1: rename fields ────────────────────────────
        # .get(name, {}) looks up this layer's field_map, or
        # uses an empty dict {} if this layer has no field_map
        # defined (e.g. it came from a source with no renames needed).
        this_field_map = field_maps.get(name, {})
        gdf = _rename_fields(gdf, this_field_map, name)

        # ── Step 2: clean up text columns ────────────────────
        gdf = _normalize_text_columns(gdf, config.encoding)

        # ── Step 3: apply canonical field types ──────────────
        # config.canonical_fields is something like:
        #   {"population": "int", "formation": "str"}
        for field_name, target_type in config.canonical_fields.items():

            if field_name not in gdf.columns:
                # The field doesn't exist in this layer at all.
                # We create it, filled with missing values (None),
                # so every layer ends up with the SAME columns —
                # even if some layers never had that data.
                logger.warning(
                    f"  '{name}': field '{field_name}' not found — "
                    "creating it filled with empty values."
                )
                gdf[field_name] = None
                continue

            gdf = _coerce_column_type(gdf, field_name, target_type, name)

        # ── Step 4: optionally drop non-canonical fields ─────
        if config.drop_extra_fields and config.canonical_fields:
            # Build the list of columns we're ALLOWED to keep:
            # the canonical fields, plus the geometry column
            # (which must never be dropped).
            keep_columns = list(config.canonical_fields.keys()) + [gdf.geometry.name]

            # Find which columns exist but AREN'T in our keep list
            extra_columns = [c for c in gdf.columns if c not in keep_columns]

            if extra_columns:
                logger.info(f"  '{name}': dropping extra fields {extra_columns}")
                gdf = gdf.drop(columns=extra_columns)

        result[name] = gdf
        logger.info(f"  '{name}': schema harmonized — {len(gdf.columns)} columns.")

    logger.info(f"  Schema harmonization complete: {len(result)} layer(s) processed.")
    return result
