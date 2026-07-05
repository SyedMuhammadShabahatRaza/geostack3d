"""
geostack3d
==========
A Python package for 3D geological terrain visualization.

Combines DEM (elevation), orthophoto (satellite imagery),
vector GIS layers, and geochemical sample data into an
interactive 3D scene — directly from a Jupyter notebook.

Install
-------
pip install git+https://github.com/SyedMuhammadShabahatRaza/geostack3d.git

Quick Start
-----------
>>> from geostack3d import run_pipeline
>>> result = run_pipeline(
...     dem     = r"path/to/dem.tif",
...     samples = r"path/to/samples.csv",
... )
>>>
>>> from geostack3d.visualize_pyvista import make_3d_scene_pyvista
>>> plotter = make_3d_scene_pyvista(result["vectors"], result["rasters"])
>>> plotter.show()

Author
------
Syed M. S. Raza
RWTH Aachen University — Sustainable Computational Engineering
"""

__version__ = "0.1.0"
__author__ = "Syed M. S. Raza"
__email__ = "shabahatnaqvi786@gmail.com"


def run_pipeline(config_path=None, **kwargs):
    """Run the GeoStack3D pipeline."""
    from geostack3d.pipeline import run_pipeline as _run
    return _run(config_path=config_path, **kwargs)


def load_config(path):
    """Load and validate a YAML config file."""
    from geostack3d.config import load_config as _load
    return _load(path)


def make_3d_scene(vectors, rasters, **kwargs):
    """
    Build a 3D terrain scene with PyVista.

    Convenience wrapper — equivalent to:
        from geostack3d.visualize_pyvista import make_3d_scene_pyvista
        plotter = make_3d_scene_pyvista(vectors, rasters, ...)
        plotter.show()
    """
    try:
        from geostack3d.visualize_pyvista import make_3d_scene_pyvista
        return make_3d_scene_pyvista(vectors, rasters, **kwargs)
    except ImportError:
        raise ImportError(
            "PyVista is required for 3D visualization.\n"
            "Install it with:  pip install pyvista[jupyter]"
        )


__all__ = [
    "run_pipeline",
    "load_config",
    "make_3d_scene",
    "__version__",
    "__author__",
]