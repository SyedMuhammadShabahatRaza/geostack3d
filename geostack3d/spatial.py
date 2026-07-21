# ============================================================
# geostack3d/spatial.py
# ============================================================
# PURPOSE:
#   Clip all data layers to a study area boundary, so the
#   pipeline only processes the area you actually care about.
#
# WHY THIS MATTERS:
#   Your USGS DEM is a full 1-degree tile (3601x3601 pixels)
#   covering a huge area. Your actual study area is tiny in
#   comparison. Processing the full tile wastes memory and
#   makes your 3D model hard to read. Clipping to the exact
#   study area boundary fixes both problems.
#
# GEOLOGY ANALOGY:
#   Like cutting out just your field area from a regional
#   geology map, rather than working with the entire sheet.
# ============================================================

from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.mask
from loguru import logger

from geostack3d.config import SpatialConfig

if TYPE_CHECKING:
    pass


class SpatialHarmonizer:
    """
    Clip vectors and rasters to a study area boundary.

    Parameters
    ----------
    config : SpatialConfig

    Examples
    --------
    >>> harmon = SpatialHarmonizer(config.spatial)
    >>> vectors = harmon.clip_vectors(vectors)
    >>> rasters = harmon.clip_rasters(rasters)
    """

    def __init__(self, config: SpatialConfig) -> None:
        self.config = config
        self._study_area: gpd.GeoDataFrame | None = None

        # Load study area immediately if path is set —
        # fail fast here rather than later mid-pipeline.
        if config.study_area_path:
            self._study_area = self._load_study_area(config.study_area_path)

    def _load_study_area(self, path: str) -> gpd.GeoDataFrame:
        """Load the study area polygon from a file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"Study area file not found: {path}\n"
                "Check 'spatial.study_area_path' in your config."
            )
        try:
            gdf = gpd.read_file(str(p))
            logger.info(
                f"[spatial] Loaded study area: {p.name} "
                f"({len(gdf)} feature(s))"
            )
            return gdf
        except Exception as e:
            raise RuntimeError(
                f"Failed to read study area file: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Vector clipping
    # ------------------------------------------------------------------

    def clip_vectors(
        self, vectors: dict[str, gpd.GeoDataFrame]
    ) -> dict[str, gpd.GeoDataFrame]:
        """
        Clip all vector layers to the study area boundary.

        If no study_area_path is set in config, layers are
        returned unchanged.

        Parameters
        ----------
        vectors : dict[str, GeoDataFrame]

        Returns
        -------
        dict[str, GeoDataFrame]
        """
        if not self.config.clip_to_study_area or self._study_area is None:
            logger.debug("[spatial] No study area set — skipping vector clip.")
            return vectors

        result = {}
        for name, gdf in vectors.items():
            result[name] = self._clip_one_vector(name, gdf)
        return result

    def _clip_one_vector(
        self, name: str, gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """Clip a single vector layer to the study area."""
        # Reproject study area to match the layer's CRS before
        # clipping — they must be in the same CRS for the spatial
        # operation to work correctly.
        study = self._study_area.to_crs(gdf.crs)

        before = len(gdf)
        try:
            clipped = gpd.clip(gdf, study)
            clipped = clipped.reset_index(drop=True)
        except Exception as e:
            raise RuntimeError(
                f"Failed to clip vector layer '{name}': {e}"
            ) from e

        after = len(clipped)
        logger.info(
            f"[spatial] Clipped vector '{name}': "
            f"{before:,} → {after:,} features."
        )
        return clipped

    # ------------------------------------------------------------------
    # Raster clipping
    # ------------------------------------------------------------------

    def clip_rasters(
        self, rasters: dict
    ) -> dict:
        """
        Clip all raster datasets to the study area boundary.

        Handles both open rasterio DatasetReader objects and
        rasterio.MemoryFile objects (produced by the CRS stage).

        Parameters
        ----------
        rasters : dict
            Layer name → rasterio dataset or MemoryFile.

        Returns
        -------
        dict
            Layer name → clipped rasterio.MemoryFile.
        """
        if not self.config.clip_to_study_area or self._study_area is None:
            logger.debug("[spatial] No study area set — skipping raster clip.")
            return rasters

        result = {}
        for name, ds in rasters.items():
            result[name] = self._clip_one_raster(name, ds)
        return result

    def _clip_one_raster(self, name: str, dataset) -> rasterio.MemoryFile:
        """Clip a single raster to the study area."""

        # Open MemoryFile if needed — same pattern as visualize_pyvista.py
        if isinstance(dataset, rasterio.io.MemoryFile):
            src = dataset.open()
        else:
            src = dataset

        # Reproject study area to match the raster's CRS
        study = self._study_area.to_crs(src.crs)

        # Convert GeoDataFrame geometries to the list-of-dicts
        # format that rasterio.mask.mask() expects
        shapes = [geom.__geo_interface__ for geom in study.geometry]

        before_size = f"{src.width}×{src.height}"

        try:
            # rasterio.mask.mask() clips the raster to the shapes.
            # crop=True shrinks the output to the bounding box of
            # the shapes — this is what actually reduces file size.
            out_image, out_transform = rasterio.mask.mask(
                src,
                shapes,
                crop=True,
                nodata=src.nodata if src.nodata is not None else 0,
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to clip raster '{name}': {e}"
            ) from e

        # Build the output profile — same as input but with
        # updated dimensions and transform for the clipped area
        profile = src.profile.copy()
        profile.update(
            height=out_image.shape[1],
            width=out_image.shape[2],
            transform=out_transform,
        )

        after_size = f"{out_image.shape[2]}×{out_image.shape[1]}"
        logger.info(
            f"[spatial] Clipped raster '{name}': "
            f"{before_size} px → {after_size} px."
        )

        # Write to MemoryFile — same approach as crs.py, keeps
        # everything in RAM without temporary files on disk
        memfile = rasterio.MemoryFile()
        with memfile.open(**profile) as dst:
            dst.write(out_image)

        return memfile
