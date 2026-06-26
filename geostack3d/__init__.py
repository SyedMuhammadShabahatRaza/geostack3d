"""
geostack3d
==========
A Python package for 3D geological terrain visualization.

Work in progress — module implementations to follow.
"""

__version__ = "0.1.0"
__author__ = "Syed M. S. Raza"
__email__ = "syed.muhammad.shabahat.raza@rwth-aachen.de"


def run_pipeline(config_path=None, **kwargs):
    """Run the GeoStack3D pipeline."""
    from geostack3d.pipeline import run_pipeline as _run
    return _run(config_path=config_path, **kwargs)


def load_config(path):
    """Load and validate a YAML config file."""
    from geostack3d.config import load_config as _load
    return _load(path)


__all__ = ["run_pipeline", "load_config", "__version__", "__author__"]