# ============================================================
# gis_harmonizer/visualize_pyvista.py
# ============================================================
# PURPOSE:
#   Same goal as visualize_3d.py (DEM as a 3D terrain surface,
#   with formations/faults/boreholes draped on top) — but built
#   with PyVista instead of Plotly.
#
# WHY A SEPARATE FILE (AGAIN)?
#   Same reasoning as before: this is new, less-tested code.
#   Keeping it separate means your working Plotly version in
#   visualize_3d.py stays untouched and usable no matter what
#   happens here.
#
# WHAT IS PYVISTA?
#   PyVista is a Python wrapper around VTK (the Visualization
#   Toolkit) — the same underlying engine used by ParaView and
#   many real scientific/geological 3D tools. It's built
#   specifically for mesh-based 3D scientific visualization,
#   which is a better conceptual fit for terrain + draped
#   geology data than a general-purpose charting library.
#
# KEY DIFFERENCE FROM PLOTLY IN PRACTICE:
#   PyVista works with actual 3D MESH objects (StructuredGrid,
#   PolyData) rather than just "a surface trace" and "a line
#   trace". This is closer to how real geological modelling
#   software thinks about terrain and geological surfaces.
#
# JUPYTER NOTE:
#   PyVista needs an extra package to render INSIDE a notebook
#   cell: `pip install pyvista[jupyter]` (specifically the
#   'trame' backend). Without it, PyVista still works, but
#   opens a separate desktop window instead of rendering inline.
# ============================================================

import numpy as np
import rasterio

import pyvista as pv


def _open_if_memoryfile(dataset):
    """Same MemoryFile-vs-open-dataset handling as our other files."""
    if isinstance(dataset, rasterio.io.MemoryFile):
        return dataset.open()
    return dataset


def _get_dem_grid(dataset):
    """
    Extract the DEM as three 2D numpy arrays: longitude grid,
    latitude grid, elevation grid. Identical logic to
    visualize_3d.py's version — PyVista needs the same raw
    coordinate information, just packaged differently below.
    """
    elevation = dataset.read(1).astype(float)

    if dataset.nodata is not None:
        elevation = np.where(elevation == dataset.nodata, np.nan, elevation)

    height, width = elevation.shape

    cols = np.arange(width)
    rows = np.arange(height)

    lons, _ = rasterio.transform.xy(dataset.transform, [0] * width, cols)
    _, lats = rasterio.transform.xy(dataset.transform, rows, [0] * height)

    lon_grid = np.array(lons)
    lat_grid = np.array(lats)

    return lon_grid, lat_grid, elevation


def _sample_elevation_at_points(dataset, lons: list[float], lats: list[float]) -> list[float]:
    """
    Sample elevation using BILINEAR interpolation, matching how
    the terrain mesh itself interpolates between grid points.
    Nearest-neighbor sampling (the old approach) could disagree
    with the mesh surface at any point not exactly on a pixel
    center, causing draped features to appear above or below
    the actual visible terrain.
    """
    from scipy.ndimage import map_coordinates

    elevation_array = dataset.read(1).astype(float)
    if dataset.nodata is not None:
        elevation_array = np.where(elevation_array == dataset.nodata, np.nan, elevation_array)

    # Convert real-world (lon, lat) coordinates into fractional
    # pixel row/col positions using the raster's inverse transform.
    inv_transform = ~dataset.transform
    cols, rows = [], []
    for lon, lat in zip(lons, lats):
        col, row = inv_transform * (lon, lat)
        cols.append(col)
        rows.append(row)

    # order=1 = bilinear interpolation, matching the mesh's own
    # interpolation between grid points.
    elevations = map_coordinates(elevation_array, [rows, cols], order=1, mode="nearest")
    return elevations.tolist()


def _orthophoto_to_texture(dataset) -> np.ndarray:
    """
    Read an orthophoto raster and prepare it as an RGB image array
    PyVista can use as a texture.

    WHAT IS A "TEXTURE" HERE?
        Instead of coloring the terrain mesh by elevation (a single
        number per pixel, mapped through a colormap like "terrain"),
        we want to paint the ACTUAL photo onto the mesh surface —
        the same way wrapping a printed photo around a 3D-printed
        landscape model would work. PyVista calls this "texture
        mapping", and it needs the image as a plain RGB array.

    Parameters
    ----------
    dataset : rasterio dataset (already in WGS84)
        Expected to have 3 bands (Red, Green, Blue), the standard
        orthophoto format. If it only has 1 band (grayscale aerial
        photo), we duplicate it across R/G/B so it still displays
        correctly as a (greyscale-looking) texture.

    Returns
    -------
    np.ndarray
        Shape (height, width, 3), dtype uint8 — a standard RGB
        image array, oriented top-to-bottom to match how the
        terrain mesh rows are built elsewhere in this file.
    """
    band_count = dataset.count

    if band_count >= 3:
        # Read the first 3 bands as Red, Green, Blue.
        # rasterio's .read() with a list of band indices returns
        # shape (bands, height, width); we reorder to the more
        # standard image shape (height, width, bands) that PyVista
        # and most image tools expect.
        rgb = dataset.read([1, 2, 3])
        rgb = np.transpose(rgb, (1, 2, 0))
    else:
        # Single-band (greyscale) orthophoto: duplicate the one
        # band 3 times so it still displays as a normal-looking
        # (if colourless) texture instead of erroring out.
        single_band = dataset.read(1)
        rgb = np.stack([single_band, single_band, single_band], axis=-1)

    # Orthophotos are sometimes stored as float or 16-bit data;
    # textures need standard 8-bit (0-255) values. We normalise
    # whatever range the data is in down to 0-255.
    rgb = rgb.astype(float)
    rgb_min, rgb_max = rgb.min(), rgb.max()
    if rgb_max > rgb_min:
        rgb = (rgb - rgb_min) / (rgb_max - rgb_min) * 255.0
    rgb = rgb.astype(np.uint8)

    return rgb


def _normalize_for_display(lon_grid, lat_grid, lon_range, lat_range, horizontal_range):
    """
    Convert real-world degrees into a normalised, roughly-square
    coordinate space for DISPLAY only.

    WHY THIS IS NEEDED (same root problem as the Plotly version):
        Longitude/latitude are in degrees (tiny numbers like
        7.00-7.30), elevation is in metres (hundreds). Plotting
        them on the same literal numeric scale makes the terrain
        look like a paper-thin sliver — exactly what you saw with
        the first Plotly attempt.

    THE FIX, PYVISTA STYLE:
        Instead of an "aspect ratio" setting (Plotly's approach),
        we rescale the X/Y coordinates themselves into a 0-1-ish
        range, then later choose a sensible Z scale relative to
        that. This is a more manual, lower-level approach — typical
        of PyVista, which expects you to manage real mesh
        coordinates yourself rather than auto-adjusting display
        ratios for you.

    Returns
    -------
    Rescaled lon_grid and lat_grid (elevation handled separately).
    """
    lon_normalized = (lon_grid - lon_grid.min()) / horizontal_range
    lat_normalized = (lat_grid - lat_grid.min()) / horizontal_range
    return lon_normalized, lat_normalized


def make_3d_scene_pyvista(
    vectors: dict,
    rasters: dict,
    dem_name: str = "dem",
    orthophoto_name: str | None = None,
    z_exaggeration: float = 1.0,
    notebook: bool = True,
):
    """
    Build a rotatable 3D PyVista scene: DEM as terrain mesh, with
    formations/faults/boreholes draped on top at their correct
    elevation. Optionally textures the terrain with a real
    orthophoto instead of coloring it by elevation.

    Parameters
    ----------
    vectors : dict[str, GeoDataFrame]
        Your harmonised vector layers (already in WGS84).
    rasters : dict[str, rasterio dataset or MemoryFile]
        Must contain a layer matching `dem_name`. May also
        contain a layer matching `orthophoto_name`.
    dem_name : str
        Which key in `rasters` is the elevation surface.
    orthophoto_name : str, optional
        Which key in `rasters` is an orthophoto (aerial/satellite
        photo) to texture the terrain with, instead of coloring
        it by elevation. Must cover the same area as the DEM —
        if it doesn't fully overlap, parts of the terrain outside
        the photo's coverage will look blank/black.
        Pass None (default) to color by elevation as before.
    z_exaggeration : float
        Multiplies elevation values before plotting (changes
        the terrain's actual bumpiness, not just the display).
    notebook : bool
        True = render inline in Jupyter (needs pyvista[jupyter]
        installed). False = open a separate desktop window instead.

    Returns
    -------
    pyvista.Plotter
        Call .show() on this to render it (done automatically
        if you just use the returned object directly).

    Examples
    --------
    Colour by elevation (original behaviour):
    >>> plotter = make_3d_scene_pyvista(result["vectors"], result["rasters"])
    >>> plotter.show()

    Texture with a real orthophoto instead:
    >>> plotter = make_3d_scene_pyvista(
    ...     result["vectors"], result["rasters"],
    ...     orthophoto_name="orthophoto",
    ... )
    >>> plotter.show()
    """
    if dem_name not in rasters:
        raise ValueError(
            f"No raster named '{dem_name}' found. "
            f"Available rasters: {list(rasters.keys())}"
        )

    dem = _open_if_memoryfile(rasters[dem_name])

    if dem.crs.to_epsg() != 4326:
        raise ValueError(
            f"DEM '{dem_name}' is in EPSG:{dem.crs.to_epsg()}, not WGS84. "
            "Run it through your pipeline's CRS harmonization stage first."
        )

    # If an orthophoto was requested, validate and prepare it now,
    # before doing any of the (more expensive) mesh-building work
    # below — fail fast on a bad orthophoto name rather than after
    # building the whole terrain mesh.
    orthophoto_texture = None
    if orthophoto_name is not None:
        if orthophoto_name not in rasters:
            raise ValueError(
                f"No raster named '{orthophoto_name}' found. "
                f"Available rasters: {list(rasters.keys())}"
            )

        orthophoto = _open_if_memoryfile(rasters[orthophoto_name])

        if orthophoto.crs.to_epsg() != 4326:
            raise ValueError(
                f"Orthophoto '{orthophoto_name}' is in EPSG:"
                f"{orthophoto.crs.to_epsg()}, not WGS84. "
                "Run it through your pipeline's CRS harmonization stage first."
            )

        orthophoto_texture = _orthophoto_to_texture(orthophoto)

    lon_grid, lat_grid, elevation_grid = _get_dem_grid(dem)

    lon_range = lon_grid.max() - lon_grid.min()
    lat_range = lat_grid.max() - lat_grid.min()
    horizontal_range = max(lon_range, lat_range)

    # Rescale X/Y into a comparable 0-1-ish space (see docstring
    # of _normalize_for_display for why this matters).
    lon_norm, lat_norm = _normalize_for_display(
        lon_grid, lat_grid, lon_range, lat_range, horizontal_range
    )

    # Choose a Z scale that's sensible relative to the now-normalised
    # X/Y range. Elevation differences (a few hundred metres) need
    # to be scaled down to roughly the same 0-1-ish range, then we
    # apply z_exaggeration on top for visual emphasis if wanted.
    elevation_range = np.nanmax(elevation_grid) - np.nanmin(elevation_grid)
    z_scale_factor = (1.0 / elevation_range) if elevation_range > 0 else 1.0
    elevation_norm = (
        (elevation_grid - np.nanmin(elevation_grid))
        * z_scale_factor
        * z_exaggeration
    )

    # ── Build the terrain mesh ───────────────────────────────
    # PyVista's StructuredGrid wants full 3D coordinate arrays
    # (X, Y, Z all the same shape) — meshgrid expands our 1D
    # lon/lat arrays into the matching 2D grids elevation_grid
    # already has.
    x_mesh, y_mesh = np.meshgrid(lon_norm, lat_norm)

    terrain = pv.StructuredGrid(x_mesh, y_mesh, elevation_norm)
    # Attach the REAL elevation values (not the normalised ones)
    # as a data array, purely so the colour scale and any hover/
    # picking labels show true metres, not the 0-1 display number.
    terrain["Elevation (m)"] = elevation_grid.flatten(order="F")

    plotter = pv.Plotter(notebook=notebook)
    plotter.enable_depth_peeling()  # helps resolve overlapping/coincident surfaces correctly

    if orthophoto_texture is not None:
        # Compute each point's texture coordinate directly from its
        # real longitude/latitude, relative to the orthophoto's own
        # true bounds — more robust than assuming a simple linear
        # correspondence, since the orthophoto's exact extent can
        # differ slightly from the DEM's.
        ortho_left, ortho_bottom = orthophoto.bounds.left, orthophoto.bounds.bottom
        ortho_right, ortho_top = orthophoto.bounds.right, orthophoto.bounds.top

        u_coords = (lon_grid - ortho_left) / (ortho_right - ortho_left)
        # v is flipped: image row 0 is the TOP of the photo, but
        # latitude increases upward — without this flip the texture
        # renders upside down.
        v_coords = (lat_grid - ortho_bottom) / (ortho_top - ortho_bottom)

        u_grid, v_grid = np.meshgrid(u_coords, v_coords)
        texture_coords = np.column_stack([
            u_grid.flatten(order="F"),
            v_grid.flatten(order="F"),
        ])
        terrain.active_texture_coordinates = texture_coords

        texture = pv.numpy_to_texture(orthophoto_texture)
        
        plotter.add_mesh(terrain, texture=texture, opacity=0.95)
    else:
        plotter.add_mesh(
            terrain,
            scalars="Elevation (m)",
            cmap="terrain",
            show_scalar_bar=True,
            opacity=0.95,
        )

    # Helper: convert a list of real-world (lon, lat, elevation)
    # values into the SAME normalised display space the terrain
    # mesh uses, so draped features land in the correct place.
    def _to_display_space(lons, lats, elevations):
        lons = np.array(lons)
        lats = np.array(lats)
        elevations = np.array(elevations)

        x = (lons - lon_grid.min()) / horizontal_range
        y = (lats - lat_grid.min()) / horizontal_range

        # No artificial lift needed — _sample_elevation_at_points()
        # now uses bilinear interpolation, matching exactly how the
        # mesh itself interpolates between grid points. This keeps
        # draped features sitting precisely on the visible terrain
        # surface, without the z-fighting/submersion issues a
        # nearest-neighbor vs. bilinear mismatch used to cause.
        z = (elevations - np.nanmin(elevation_grid)) * z_scale_factor * z_exaggeration
        
        return x, y, z

    # ── Draped boreholes (points) ─────────────────────────────
    for name, gdf in vectors.items():
        if gdf.geometry.geom_type.iloc[0] != "Point":
            continue

        lons = gdf.geometry.x.tolist()
        lats = gdf.geometry.y.tolist()
        elevations = _sample_elevation_at_points(dem, lons, lats)

        x, y, z = _to_display_space(lons, lats, elevations)
        points = np.column_stack([x, y, z])

        point_cloud = pv.PolyData(points)
        plotter.add_mesh(
            point_cloud,
            color="red",
            point_size=12,
            render_points_as_spheres=True,
            label=name,
        )

    # ── Draped faults (lines) ─────────────────────────────────
    for name, gdf in vectors.items():
        if gdf.geometry.geom_type.iloc[0] not in ("LineString", "MultiLineString"):
            continue

        for _, row in gdf.iterrows():
            geom = row.geometry
            sub_lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)

            for line in sub_lines:
                lons, lats = line.xy
            lons, lats = list(lons), list(lats)

            elevations = _sample_elevation_at_points(dem, lons, lats)
            x, y, z = _to_display_space(lons, lats, elevations)
            points = np.column_stack([x, y, z])

            # pv.lines_from_points builds a connected line mesh
            # from an ordered list of 3D points — the PyVista
            # equivalent of Plotly's mode="lines" Scatter3d.
            line_mesh = pv.lines_from_points(points)
            plotter.add_mesh(line_mesh, color="black", line_width=4, label=name, render_lines_as_tubes=True)

    # ── Draped formations (polygon outlines) ──────────────────
    for name, gdf in vectors.items():
        if gdf.geometry.geom_type.iloc[0] not in ("Polygon", "MultiPolygon"):
            continue

        for _, row in gdf.iterrows():
            polygon = row.geometry
            sub_polygons = (
                [polygon] if polygon.geom_type == "Polygon"
                else list(polygon.geoms)
            )

            for sub_polygon in sub_polygons:
                lons, lats = sub_polygon.exterior.xy
                lons, lats = list(lons), list(lats)

                elevations = _sample_elevation_at_points(dem, lons, lats)
                x, y, z = _to_display_space(lons, lats, elevations)
                points = np.column_stack([x, y, z])

                outline_mesh = pv.lines_from_points(points)
                plotter.add_mesh(outline_mesh, color="blue", line_width=3, label=name)

    if vectors:
        plotter.add_legend()
    plotter.add_axes()
    plotter.camera.zoom(1.2)

    return plotter
