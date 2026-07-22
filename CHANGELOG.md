# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - 2026-07-22

### Added
- Initial package structure (`pyproject.toml`, `.gitignore`)
- Pydantic-validated pipeline configuration (`config.py`)
- Pre-flight file validation before any data is loaded (`validate.py`)
- Data ingestion for vector, raster, and tabular sources, with KML/KMZ
  auto-extraction support (`ingest.py`)
- CRS harmonization across all layers, including the study area (`crs.py`)
- Study area clipping for vector and raster layers (`spatial.py`)
- Field name and type harmonization across layers (`schema.py`)
- Geometry validation and automatic repair for invalid shapes, common in
  hand-digitized KML data (`geometry.py`)
- Final QA gate with configurable halt-on-failure behavior (`qa.py`)
- Raster and vector output saving (`pipeline.py`)
- Interactive 3D terrain visualization using PyVista, with orthophoto
  draping and DEM resolution matching (`visualize_pyvista.py`)
- `optional` flag on every data source so missing files are skipped
  gracefully instead of stopping the pipeline

### Changed
- Reordered the pipeline so CRS harmonization runs before clipping — running
  clip first was comparing geometries in mismatched coordinate systems and
  silently producing empty or wrong results
- Made `study_area` a required input rather than optional — without it, the
  pipeline would process a full raster tile at full extent (a USGS DEM tile
  can be 3601×3601 pixels), which is slow and memory-intensive on smaller
  machines
- Removed the YAML config-file interface in favor of the simpler
  argument-based `run_pipeline()` interface, for a project of this scope
- Cleaned up package metadata: real author information, removed PyPI-only
  `keywords`, removed unused dependencies (`folium`, `matplotlib`,
  `contextily`, `rioxarray`, `xarray`, `rasterstats`)

### Fixed
- `visualize_pyvista.py` crashed with `ValueError: No labels input` on
  DEM-only runs, since `plotter.add_legend()` was called unconditionally even
  when no vector layers existed to label
- `.gitignore` had `.coverage` merged onto the same line as `.idea/`, so
  neither pattern was actually being applied correctly