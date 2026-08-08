# Data Lifecycle Documentation

This document records the origin, collection date, and processing history of
every real input dataset used in the development and testing of `geostack3d`.
It exists to support reproducibility and transparency — anyone using this
package's outputs should be able to trace exactly where the underlying data
came from and what has been done to it.

---

## DEM (Digital Elevation Model)

| Field | Detail |
|---|---|
| **File(s)** | `dem1.tif`, `dem2.tif` |
| **Source** | USGS EarthExplorer (`earthexplorer.usgs.gov`) |
| **Underlying dataset** | SRTM (Shuttle Radar Topography Mission), 1 arc-second |
| **Collection date** | February 11–22, 2000 (Space Shuttle Endeavour mission) |
| **Native resolution** | ~30 meters per pixel |
| **Tile size (as downloaded)** | 3601×3601 pixels (standard 1° SRTM tile) |
| **CRS (as downloaded)** | EPSG:4326 (WGS84) |
| **Processing applied by this pipeline** | CRS harmonization (skipped — already WGS84), clipped to study area, geometry unaffected (rasters have no geometry stage) |

**Known caveat:** this elevation data is now over 25 years old. For terrain that
changes slowly (mountains, natural slopes), this is not a significant concern.
For areas with active human modification — most notably the `Open_pit` mining
boundary used in testing — the real ground elevation may now differ materially
from what this DEM records. This is a genuine, documented limitation, not an
oversight: **elevation values shown for the open-pit area reflect year-2000
terrain, not current conditions.**

---

## Orthophoto (satellite/aerial imagery)

Two separate orthophoto sources were used at different points in this project.

### Original orthophoto

| Field | Detail |
|---|---|
| **File** | `orthophotoUSGS.tif` |
| **Source** | USGS EarthExplorer |
| **Native resolution** | ~28–33 meters per pixel (confirmed via direct measurement; resolution characteristics are consistent with Landsat-derived imagery rather than true high-resolution aerial orthophotography) |
| **Collection date** | Not explicitly recorded at time of download — a genuine gap, noted here rather than assumed |

### Improved orthophoto (used in later testing)

| Field | Detail |
|---|---|
| **File** | `orthophoto_10m.tif` |
| **Source** | Copernicus Data Space Ecosystem, European Union (`dataspace.copernicus.eu`) |
| **Underlying dataset** | Sentinel-2, Level-2A (atmospherically corrected) |
| **Native resolution** | 10 meters per pixel (true visual bands B02/B03/B04) |
| **Collection date** | Downloaded July 2026; exact scene acquisition date not separately logged — noted as a gap for future improvement |
| **CRS (as downloaded)** | EPSG:32642 (UTM Zone 42N) |
| **Processing applied by this pipeline** | Reprojected to EPSG:4326 (genuine reprojection, ~25 seconds for the full tile), clipped to study area |

**Known caveat:** even the improved 10m Sentinel-2 imagery is substantially
coarser than commercial sub-meter sources. This was verified directly by
comparing 2D and 3D renders side-by-side (see Bugs Found & Fixed / Limitations)
— the resolution limit is a genuine property of the source data, not a
processing artifact.

---

## Vector Layers (boundaries, paths)

| Field | Detail |
|---|---|
| **Files** | `path.kml` / `VELLEY.kml`, `Open_pit.kmz` / `POLYGON.kml`, `track.kmz` |
| **Source** | Hand-digitized in Google Earth / Google Earth Pro, by the author |
| **Collection date** | Created during this project (2026), not sourced from an external survey |
| **CRS (as created)** | EPSG:4326 (WGS84) — Google Earth's native export CRS |
| **Processing applied by this pipeline** | CRS harmonization (typically skipped, already WGS84), geometry validation/repair, schema harmonization, clipped to study area |

**Known caveat:** these are illustrative/test boundaries created for
development and demonstration purposes, not surveyed or field-verified
geological features.

---

## Study Area Boundary

| Field | Detail |
|---|---|
| **File** | `study_area2.kmz` |
| **Source** | Hand-digitized in Google Earth, by the author |
| **Collection date** | Created during this project (2026) |
| **CRS (as created)** | EPSG:4326 (WGS84) |
| **Processing applied by this pipeline** | CRS harmonization (per-run, defensively reprojected even if already correct), used to define clip extent for all other layers |

**Known caveat:** as documented in Limitations, the study area boundary
currently bypasses `geometry.py`'s validity repair step — a genuinely broken
study area file can still cause the pipeline to fail. This is planned to be
fixed (see Outlook).

---

## Why This Document Exists

This directly addresses a real gap identified during development: prior to
this document, dataset provenance existed only in project discussion, not in
the repository itself. Recording it here means anyone — including the author,
months from now — can answer "where did this number actually come from?"
without having to reconstruct the history from memory.
