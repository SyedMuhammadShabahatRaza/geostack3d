# ============================================================
# Dockerfile for geostack3d
# ============================================================
# Build with:   docker build -t geostack3d .
# Run with:     docker run -it geostack3d
# ============================================================

# ── Step 1: Base image ──────────────────────────────────────
# Starts from an official, minimal Python 3.11 image (matches
# our project's "requires-python = >=3.10" in pyproject.toml).
# "slim" means a smaller image — fewer pre-installed extras.
FROM python:3.11-slim

# ── Step 2: System-level libraries ──────────────────────────
# geopandas/rasterio/fiona pip wheels already bundle GDAL/GEOS/
# PROJ internally on most platforms, so we don't need to
# install those separately. However, PyVista (via VTK) needs
# some system graphics libraries to render 3D scenes, even
# when running "headless" (no physical screen, as inside a
# container).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libxrender1 \
    libxext6 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*
    # "rm -rf /var/lib/apt/lists/*" cleans up temporary download
    # files afterward, keeping the final image smaller.

# ── Step 3: Working directory ───────────────────────────────
# All following commands run relative to this folder INSIDE
# the container (this is not your real F:\... folder — it's a
# fresh, isolated filesystem inside the image).
WORKDIR /app

# ── Step 4: Copy project files into the image ───────────────
# Copying pyproject.toml first (before the rest of the code)
# is a deliberate optimization: if only your .py files change
# later, Docker can reuse the cached dependency-install step
# from Step 5, instead of redoing it every single build.
COPY pyproject.toml .
COPY geostack3d/ ./geostack3d/
COPY README.md .

# ── Step 5: Install the package and its pinned dependencies ─
# This uses the exact same pyproject.toml dependencies you've
# already defined — so the image gets precisely the versions
# you've tested with, not whatever happens to be newest.
RUN pip install --no-cache-dir .

# ── Step 6: Environment variable for off-screen 3D rendering ─
# PyVista/VTK normally expects a real display to draw to.
# Setting this tells it to use a virtual, headless display
# instead (paired with the xvfb tool installed in Step 2).
ENV DISPLAY=:99

# ── Step 7: Default command when the container starts ──────
# Simply drops into a Python interpreter, ready to
# `from geostack3d import run_pipeline`. Replace this with a
# specific script path if you want the container to run a
# fixed task automatically instead.
CMD ["python"]