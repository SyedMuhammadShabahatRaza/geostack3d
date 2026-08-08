# Changelog

All notable changes to this project are documented in this file.

## [0.2.0] - 2026-08-05

### Added
- Automated test suite (27 tests) covering config validation, geometry
  repair, CRS harmonization, schema harmonization, and QA checks
  (`tests/`)
- `Dockerfile` for a fully reproducible, containerized environment —
  built and verified to install and import successfully in a clean
  container
- `DATA_LIFECYCLE.md`, documenting the source, collection date, and
  processing history of every real input dataset used during
  development (including the DEM's February 2000 SRTM origin vs. the
  orthophoto's much more recent capture date)
- Multi-tabular source support — `samples` can now be a single path, a
  list of paths, or a `{name: path}` dict, so multiple CSV/Excel
  sample sheets can be loaded in one call
- Automatic line-noding for self-crossing lines — a `LineString` that
  is OGC-valid but self-intersects (`is_valid=True`, `is_simple=False`)
  is now automatically noded with `unary_union()`, preventing a
  `TopologyException` at clip time without requiring manual
  intervention
- `field_map`, `canonical_fields`, and `drop_extra_fields` are now
  exposed directly as `run_pipeline()` parameters — previously only
  accessible by building a `PipelineConfig` manually

### Changed
- Dependency versions in `pyproject.toml` are now pinned to exact,
  tested versions (`==`) instead of minimums (`>=`), guaranteeing a
  reproducible install
- The study area boundary now passes through the same geometry
  repair (`repair_geometries()`) as every other vector layer —
  previously it was the one layer that bypassed this check entirely,
  since it's loaded separately by `spatial.py` rather than through
  the normal ingest flow
- `SpatialHarmonizer` now accepts an optional `GeometryConfig`, used
  to repair the study area's own geometry immediately after loading it
- Draped feature elevation sampling (`_sample_elevation_at_points`)
  switched from nearest-neighbor to bilinear interpolation, matching
  exactly how the terrain mesh itself interpolates between grid
  points
- 3D vector rendering now handles `MultiLineString` geometries, not
  just `LineString` — necessary since a noded, self-crossing line
  becomes a `MultiLineString`

### Fixed
- `README.md` content, which had been accidentally overwritten with
  `pyproject.toml` content during a dependency-pinning edit, restored
  to its correct content
- Draped vector features (e.g. a path) appearing submerged in terrain
  dips — caused by nearest-neighbor point sampling disagreeing with
  the mesh's own bilinear interpolation at any point not exactly on a
  pixel center
- Orthophoto texture rendering upside-down (north-south flipped) for
  a newer orthophoto source, by removing an unconditional vertical
  flip that didn't match this file's row ordering
- 3D legend crash (`ValueError: No labels input`) when the only vector
  layer present was a `MultiLineString` — the rendering loop
  previously only matched `LineString` and silently skipped
  `MultiLineString` layers entirely, leaving no labeled mesh for
  `add_legend()` to find
- Visual depth conflict ("z-fighting") on draped vectors sitting at
  the same height as the terrain mesh, using tube rendering and depth
  peeling

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