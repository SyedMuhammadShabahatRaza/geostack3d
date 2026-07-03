# ============================================================
# geostack3d/qa.py
# ============================================================
# PURPOSE:
#   Run a checklist of sanity checks on the data AFTER it has
#   been cleaned, and stop the pipeline if something still
#   looks wrong.
#
# WHY THIS MATTERS:
#   Every previous stage (CRS, geometry, schema) tries to FIX
#   problems. This stage is different — it doesn't fix anything.
#   It just VERIFIES the result is actually good enough to use,
#   the same way you'd review your own work before submitting
#   a report.
#
# GEOLOGY ANALOGY:
#   This is your QAQC checklist on geochemical samples:
#     - Are all sample IDs unique?
#     - Are there enough samples to be statistically meaningful?
#     - Are any values impossible (negative depth, etc.)?
#   You already do this by eye in a spreadsheet. This file
#   just automates the same kind of checking.
#
# HOW IT WORKS:
#   For each layer, we run several independent checks. Each
#   check produces a simple PASS or FAIL result with a message.
#   At the end we either raise an error (stop everything) or
#   just log a warning, depending on the config.
# ============================================================

import geopandas as gpd
from pyproj import CRS
from loguru import logger

from geostack3d.config import QAConfig


# ============================================================
# TEACHING NOTE: Why collect results instead of failing instantly?
# ============================================================
# We could write each check as:
#   if some_condition_is_bad:
#       raise ValueError("...")
#
# But that means the pipeline stops at the FIRST problem found,
# even if there are five other problems waiting right after it.
# You'd fix one, rerun, hit the next one, fix it, rerun again...
#
# Instead, we run EVERY check first, collect all the results,
# and only decide whether to stop at the very end. This way you
# see the full list of problems in one go — much faster to fix.
# ============================================================


def _check_row_count(name: str, gdf: gpd.GeoDataFrame, config: QAConfig) -> tuple[bool, str]:
    """
    Check the layer has a sensible number of rows.

    Returns
    -------
    tuple of (passed: bool, message: str)
        This pattern — returning both a True/False AND a
        human-readable message — repeats in every check function
        below. It's a simple way to report "what happened" without
        needing a whole class just for this.
    """
    count = len(gdf)

    if count < config.min_row_count:
        return False, f"row count {count} is below minimum {config.min_row_count}"

    if config.max_row_count is not None and count > config.max_row_count:
        return False, f"row count {count} exceeds maximum {config.max_row_count}"

    return True, f"row count {count} is within expected range"


def _check_required_fields(name: str, gdf: gpd.GeoDataFrame, config: QAConfig) -> tuple[bool, str]:
    """Check that every field listed in config.required_fields is present."""
    # This finds which required fields are MISSING by comparing
    # the list of required fields against the columns we actually have.
    missing = [f for f in config.required_fields if f not in gdf.columns]

    if missing:
        return False, f"missing required fields: {missing}"

    return True, "all required fields present"


def _check_geometry_validity(name: str, gdf: gpd.GeoDataFrame) -> tuple[bool, str]:
    """Check that geometries are still valid (should be, after Stage 3)."""
    if len(gdf) == 0:
        # Nothing to check on an empty layer — not a failure,
        # just nothing to say.
        return True, "empty layer, skipped"

    valid_rate = gdf.geometry.is_valid.mean()

    if valid_rate < 1.0:
        return False, f"{valid_rate:.1%} of geometries are valid (expected 100%)"

    return True, "all geometries valid"


def _check_no_empty_geometry_column(name: str, gdf: gpd.GeoDataFrame) -> tuple[bool, str]:
    """Check the geometry column isn't entirely null."""
    if len(gdf) == 0:
        return True, "empty layer, skipped"

    if gdf.geometry.isna().all():
        return False, "every geometry in this layer is null"

    return True, "geometry column has values"


def _check_crs_matches(
    name: str, gdf: gpd.GeoDataFrame, project_epsg: int
) -> tuple[bool, str]:
    """Check the layer's CRS matches the project CRS."""
    if gdf.crs is None:
        return False, "layer has no CRS set"

    expected = CRS.from_epsg(project_epsg)

    if gdf.crs != expected:
        actual_epsg = gdf.crs.to_epsg()
        return False, f"CRS is EPSG:{actual_epsg}, expected EPSG:{project_epsg}"

    return True, f"CRS matches project CRS (EPSG:{project_epsg})"


def run_qa(
    vectors: dict[str, gpd.GeoDataFrame],
    config: QAConfig,
    project_epsg: int,
) -> list[dict]:
    """
    Run all QA checks on every layer.

    Parameters
    ----------
    vectors : dict[str, GeoDataFrame]
    config : QAConfig
    project_epsg : int
        The expected CRS, used for the CRS check.

    Returns
    -------
    list[dict]
        One dict per check, each with keys:
        "layer", "check", "passed", "message".
        Useful if you want to inspect results programmatically
        instead of just reading the log.

    Raises
    ------
    ValueError
        If any check fails AND config.halt_on_failure is True.

    Examples
    --------
    >>> results = run_qa(vectors, config.qa, project_epsg=4326)
    >>> failed = [r for r in results if not r["passed"]]
    >>> print(failed)
    []
    """
    logger.info("Stage 5: Running QA checks...")

    # This list will hold one entry per check, across all layers.
    # Each entry is a small dictionary — think of it as one row
    # in a QAQC spreadsheet: layer name, which check, pass/fail, why.
    all_results: list[dict] = []

    for name, gdf in vectors.items():

        # Run every check for this layer. Each one returns
        # (passed, message) — we unpack that into two variables
        # at once using Python's tuple unpacking.
        checks_to_run = [
            ("row_count", _check_row_count(name, gdf, config)),
            ("required_fields", _check_required_fields(name, gdf, config)),
            ("geometry_validity", _check_geometry_validity(name, gdf)),
            ("geometry_not_null", _check_no_empty_geometry_column(name, gdf)),
            ("crs_match", _check_crs_matches(name, gdf, project_epsg)),
        ]

        for check_name, (passed, message) in checks_to_run:
            all_results.append({
                "layer": name,
                "check": check_name,
                "passed": passed,
                "message": message,
            })

            # Log immediately so you see progress in real time,
            # not just at the very end.
            if passed:
                logger.debug(f"  [PASS] {name} | {check_name}: {message}")
            else:
                logger.error(f"  [FAIL] {name} | {check_name}: {message}")

    # ── Decide what to do with the results ──────────────────
    # A list comprehension again, this time just to filter:
    # "give me only the dicts where passed is False."
    failures = [r for r in all_results if not r["passed"]]

    n_total = len(all_results)
    n_passed = n_total - len(failures)
    logger.info(f"  QA summary: {n_passed}/{n_total} checks passed.")

    if failures and config.halt_on_failure:
        # Build a readable summary of every failure for the
        # error message, instead of just saying "something failed".
        failure_lines = [
            f"  - {f['layer']} | {f['check']}: {f['message']}"
            for f in failures
        ]
        raise ValueError(
            f"QA gate failed with {len(failures)} problem(s):\n"
            + "\n".join(failure_lines)
        )

    elif failures:
        # halt_on_failure is False — we warn but don't stop.
        logger.warning(
            f"  {len(failures)} QA check(s) failed, but halt_on_failure "
            "is disabled — continuing anyway."
        )

    return all_results
