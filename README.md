# geostack3d

A Python package for **3D geological terrain visualization**. It takes messy,
multi-source GIS data — a DEM, an orthophoto, vector layers (faults, geological
formations, KML/KMZ boundaries), and geochemical sample CSVs — and fuses them
into a single reproducible processing pipeline that outputs an interactive
3D scene built with [PyVista](https://docs.pyvista.org/).

Built as a course project for **Sustainable Computational Engineering**,
RWTH Aachen University.

---

## Why this exists

Geological fieldwork produces data in wildly inconsistent formats: a DEM in
one CRS, hand-digitized KML boundaries in another, geochemistry results in a
spreadsheet with lat/lon columns, fault traces in a Shapefile with a different
schema than the formation polygons next to them. Before you can look at any
of it together in 3D, it all has to be brought onto the same coordinate
system, clipped to the same area, cleaned of invalid geometries, and checked
for basic data quality. `geostack3d` automates that harmonization step so
the actual analysis — looking at the terrain — isn't blocked by GIS plumbing.

---

## Install

```bash
git clone https://github.com/SyedMuhammadShabahatRaza/geostack3d.git
cd geostack3d
pip install -e .
```

`-e` means "editable" — changes to the code take effect without reinstalling.

**Requires Python 3.10+**

> **Jupyter note:** for inline 3D rendering (rather than a separate desktop
> window), install PyVista's Jupyter extras: `pip install pyvista[jupyter]`

> **Editable-install + Jupyter note:** editable installs can silently fail
> to register in Jupyter under some Anaconda setups (`__file__` ends up
> `None`). If `import geostack3d` fails in a notebook but works from a
> terminal, add the package path to `sys.path` as your first notebook cell:
> ```python
> import sys
> sys.path.insert(0, r"path/to/geostack3d")
> ```

---

## Quick Start

```python
from geostack3d import run_pipeline

result = run_pipeline(
    dem        = r"path/to/dem.tif",
    orthophoto = r"path/to/orthophoto.tif",     # optional
    samples    = r"path/to/samples.csv",         # optional
    study_area = r"path/to/study_area.geojson",  # required
    output_dir = r"path/to/output",
)
```

**`study_area` is required, not optional.** Without it, the pipeline would
process a full raster tile at full extent — a USGS DEM tile can be
3601×3601 pixels, which is slow and memory-intensive on smaller machines.
Only `dem` and `study_area` are strictly required; `orthophoto`, `samples`,
and additional `vectors` are all optional and skipped gracefully if not
provided.

### View the 3D scene

3D visualization is intentionally kept separate from the pipeline so
`run_pipeline()` works even without PyVista installed.

```python
from geostack3d.visualize_pyvista import make_3d_scene_pyvista

plotter = make_3d_scene_pyvista(
    result["vectors"],
    result["rasters"],
    dem_name="dem",
    orthophoto_name="orthophoto",
)
plotter.show()
```

---

## What Happens, Step by Step

  S/no  | Stage   | File                   | What it does |
|-------|---------|------------------------|---------------
| 1.    |Validate | `validate.py`          | Checks every input file exists and is readable *before* loading anything, including the required study area |
| 2.    |Ingest   | `ingest.py`            | Loads vector, raster, and CSV/Excel sources (KMZ auto-extracts to KML) |
| 3.    |CRS      | `crs.py`               | Reprojects every layer — including the study area — to one target CRS |
| 4.    |Clip     | `spatial.py`           | Clips all layers to the study area boundary (runs *after* CRS harmonization, so no per-layer reprojection is needed at clip time) |
| 5.    |Schema   | `schema.py`            | Standardizes field names and data types across layers |
| 6.    |Geometry | `geometry.py`          | Detects and repairs invalid geometries (common with hand-digitized KML data) |
| 7.    |QA       | `qa.py`                | Runs data quality checks; halts or warns depending on config |
| 8.    |Save     | `pipeline.py`          | Writes processed vector/raster outputs to disk |
| 9.    |Visualize| `visualize_pyvista.py` | Builds the interactive 3D scene (called separately, not part of `run_pipeline()`) |

Every optional data source (`orthophoto`, `samples`, additional vector
layers) is skipped gracefully if missing, rather than stopping the run.
The DEM and study area are the only required inputs.

---

## Project Structure


geostack3d/
├── README.md
├── .gitignore
├── pyproject.toml
└── geostack3d/
    ├── __init__.py
    ├── config.py              
    ├── validate.py
    ├── ingest.py
    ├── crs.py
    ├── spatial.py
    ├── schema.py
    ├── geometry.py
    ├── qa.py
    ├── visualize_pyvista.py   
    └── pipeline.py           



## Running One Stage at a Time

Each stage is its own function, so you're not locked into running the whole
pipeline:

```python
from geostack3d.config import PipelineConfig, RasterSourceConfig, SpatialConfig
from geostack3d.validate import validate_all_sources
from geostack3d.ingest import load_all_sources
from geostack3d.crs import harmonize_crs

config = PipelineConfig(
    raster_sources=[RasterSourceConfig(name="dem", path="dem.tif", optional=False)],
    spatial=SpatialConfig(study_area_path="study_area.geojson"),
)
validate_all_sources(config)

vectors, rasters, tabulars = load_all_sources(config)
vectors.update(tabulars)

vectors = harmonize_crs(vectors, config.crs)
```

---

## Return value of `run_pipeline()`

```python
{
    "vectors": dict[str, GeoDataFrame],      # processed vector layers
    "rasters": dict[str, rasterio dataset],  # processed rasters
    "qa":      list[dict],                   # one entry per QA check
    "saved":   list[str],                    # paths of saved output files
    "config":  PipelineConfig,               # the config actually used
}
```

---

## Status

Core pipeline and 3D visualization are functional and tested against a
real USGS DEM tile (Hindu Kush region) and synthetic geochemistry sample
points at real field coordinates. A `tests/` directory covering config
validation, geometry repair, schema harmonization, QA, and full pipeline
integration is in progress.