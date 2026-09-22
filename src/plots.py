"""this module contains functions for plotting"""

import math
from typing import Optional, Sequence

from bokeh.io import save, show
from bokeh.models import (
    BasicTicker,
    ColorBar,
    ColumnDataSource,
    HoverTool,
    LinearColorMapper,
    PrintfTickFormatter,
)
from bokeh.palettes import Viridis256
from bokeh.plotting import figure
import numpy as np


def _interpolated_palette(stops: list[tuple[float, str]], n: int = 256) -> list[str]:
    """Linearly interpolate hex color ``stops`` (fraction, "#RRGGBB") into an n-color palette."""

    def hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    rgb_stops = [(frac, hex_to_rgb(color)) for frac, color in stops]
    palette = []
    for x in np.linspace(0, 1, n):
        (x0, c0), (x1, c1) = next(
            (a, b)
            for a, b in zip(rgb_stops, rgb_stops[1:], strict=False)
            if a[0] <= x <= b[0]
        )
        t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
        rgb = tuple(round(c0[k] + t * (c1[k] - c0[k])) for k in range(3))
        palette.append("#{:02X}{:02X}{:02X}".format(*rgb))
    return palette


#: White (inactive) -> vivid red -> dark red (active), fixed to a 0-1 range.
#: Matches platform-ui's "WhiteRed" panel-heatmap scale exactly.
WHITE_RED_HAZARD_PALETTE = _interpolated_palette(
    [(0.0, "#FFFFFF"), (0.5, "#D93E39"), (1.0, "#641D1A")]
)

_HEATMAP_TOOLS = "pan,wheel_zoom,box_zoom,reset,save"
_VALUE_STR_FIELD = "@value_str"


def _resolve_labels(
    n: int,
    labels: Optional[Sequence[str]],
    *,
    param_name: str,
    shape_desc: str,
) -> list[str]:
    """Default to "0..n-1", or validate that provided labels have length n."""
    if labels is None:
        return [str(i) for i in range(n)]
    labels = list(map(str, labels))
    if len(labels) != n:
        raise ValueError(f"Length of `{param_name}` must match {shape_desc}.")
    return labels


def _auto_color_range(
    mat: np.ndarray, clim: Optional[tuple[float, float]]
) -> tuple[float, float]:
    """Fixed *clim*, or (vmin, vmax) from *mat*'s finite values."""
    if clim is not None:
        return clim
    finite_vals = mat[np.isfinite(mat)]
    if finite_vals.size == 0:
        return 0.0, 1.0
    vmin, vmax = float(np.nanmin(finite_vals)), float(np.nanmax(finite_vals))
    if math.isclose(vmin, vmax):
        delta = 1e-6 if vmin == 0 else abs(vmin) * 1e-6
        vmin, vmax = vmin - delta, vmax + delta
    return vmin, vmax


def _triangle_grid_source(
    mat: np.ndarray,
    row_labels: Sequence[str],
    col_labels: Sequence[str],
    *,
    upper: bool,
) -> ColumnDataSource:
    """Triangle-vertex geometry for one half (upper or lower) of a split-heatmap grid, split top-left to bottom-right."""
    n_rows, n_cols = mat.shape
    xs, ys, vals, rows, cols = [], [], [], [], []
    for i in range(n_rows):
        y1 = n_rows - i  # top edge of this row's band
        y0 = y1 - 1
        for j in range(n_cols):
            v = mat[i, j]
            if not np.isfinite(v):
                continue
            x0, x1 = j, j + 1
            if upper:
                xs.append([x0, x1, x1])
                ys.append([y1, y1, y0])
            else:
                xs.append([x0, x0, x1])
                ys.append([y1, y0, y0])
            vals.append(v)
            rows.append(row_labels[i])
            cols.append(col_labels[j])
    return ColumnDataSource(
        {
            "xs": xs,
            "ys": ys,
            "value": vals,
            "value_str": [f"{v:.4f}" for v in vals],
            "row": rows,
            "col": cols,
        }
    )


def plot_heatmap(
    values: np.ndarray,
    *,
    labels: Optional[Sequence[str]] = None,
    title: str = "",
    palette=Viridis256,
    size: int = 700,
    show_values_on_hover: bool = True,
    clim: Optional[tuple[float, float]] = None,
):
    """
    Visualize a square matrix (NxN) as a Bokeh heatmap.

    Parameters
    ----------
    values : np.ndarray
        Square NxN matrix. NaNs are allowed.
    labels : list[str], optional
        Row/column labels. If None, uses "0..N-1".
    title : str
        Plot title.
    palette : sequence of colors
        Bokeh palette for the heatmap.
    size : int
        Figure size in pixels (width = height for square matrix).
    show_values_on_hover : bool
        If True, shows (row, col, value) tooltips when hovering cells.
    clim : tuple[float, float], optional
        Color limits as (vmin, vmax). If None, automatically computed from data.
        Useful for consistent color scaling across multiple plots.

    Returns
    -------
    bokeh.plotting.Figure
    """
    # --- Normalize inputs ---
    mat = np.asarray(values, dtype=float)
    if labels is None:
        labels = [str(i) for i in range(mat.shape[0])]
    else:
        labels = list(map(str, labels))

    if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
        raise ValueError("R must be a square NxN matrix.")

    n = mat.shape[0]
    if len(labels) != n:
        raise ValueError("Length of `labels` must match the matrix dimension.")

    # --- Compute color scale range, ignoring NaNs ---
    if clim is not None:
        vmin, vmax = clim
    else:
        finite_vals = mat[np.isfinite(mat)]
        if finite_vals.size == 0:
            vmin, vmax = 0.0, 1.0
        else:
            vmin, vmax = float(np.nanmin(finite_vals)), float(np.nanmax(finite_vals))
            if math.isclose(vmin, vmax):
                # Avoid degenerate color scales
                delta = 1e-6 if vmin == 0 else abs(vmin) * 1e-6
                vmin, vmax = vmin - delta, vmax + delta

    # --- Build rect grid data (categorical axes so labels show nicely) ---
    xs, ys, vals, ii, jj = [], [], [], [], []
    for i in range(n):
        for j in range(n):
            xs.append(labels[j])  # x is column
            ys.append(labels[n - 1 - i])  # y reversed so (0,0) is top-left visually
            vals.append(mat[i, j])
            ii.append(i)
            jj.append(j)

    source = ColumnDataSource(
        {
            "x": xs,
            "y": ys,
            "value": vals,
            "i": ii,
            "j": jj,
            "value_str": [("NA" if not np.isfinite(v) else f"{v:.4f}") for v in vals],
        }
    )

    # --- Color mapper ---
    mapper = LinearColorMapper(
        palette=palette,
        low=vmin,
        high=vmax,
        nan_color="#dddddd",
    )

    # --- Create and configure figure ---
    p = figure(
        title=title,
        x_range=labels,
        y_range=list(reversed(labels)),
        x_axis_location="above",
        tools=_HEATMAP_TOOLS,
        toolbar_location="right",
        width=size,
        height=size,
        tooltips=None,
        match_aspect=True,
    )

    # Add cells
    p.rect(
        x="x",
        y="y",
        width=1,
        height=1,
        source=source,
        line_color=None,
        fill_color={"field": "value", "transform": mapper},
    )

    if show_values_on_hover:
        hover = HoverTool(
            tooltips=[
                ("row (i)", "@i"),
                ("col (j)", "@j"),
                ("label row", "@y"),
                ("label col", "@x"),
                ("RMSD", _VALUE_STR_FIELD),
            ]
        )
        p.add_tools(hover)

    color_bar = ColorBar(
        color_mapper=mapper,
        location=(0, 0),
        ticker=BasicTicker(desired_num_ticks=8),
        formatter=PrintfTickFormatter(format="%.3f"),
        label_standoff=8,
    )
    p.add_layout(color_bar, "right")

    p.axis.major_label_text_font_size = "9pt"
    p.xaxis.major_label_orientation = 0.9
    p.grid.visible = False

    show(p)


def plot_grid_heatmap(
    values: np.ndarray,
    *,
    row_labels: Optional[Sequence[str]] = None,
    col_labels: Optional[Sequence[str]] = None,
    title: str = "",
    value_label: str = "value",
    palette=Viridis256,
    width: int = 900,
    height: int = 500,
    show_values_on_hover: bool = True,
    clim: Optional[tuple[float, float]] = None,
):
    """
    Visualize a rectangular (NxM) matrix as a Bokeh heatmap, with independent
    row and column labels.

    Parameters
    ----------
    values : np.ndarray
        NxM matrix. NaNs are allowed.
    row_labels, col_labels : list[str], optional
        Labels for each axis. Default to "0..N-1" / "0..M-1".
    title : str
        Plot title.
    value_label : str
        Name for the cell value in the hover tooltip.
    palette : sequence of colors
        Bokeh palette for the heatmap.
    width, height : int
        Figure size in pixels.
    show_values_on_hover : bool
        If True, shows (row, col, value) tooltips when hovering cells.
    clim : tuple[float, float], optional
        Color limits as (vmin, vmax). If None, computed from data.

    Returns
    -------
    bokeh.plotting.Figure
    """
    from deeporigin.utils.notebook import get_notebook_environment

    if get_notebook_environment() in ["marimo", "jupyter"]:
        from bokeh.io import output_notebook

        output_notebook(hide_banner=True)

    mat = np.asarray(values, dtype=float)
    if mat.ndim != 2:
        raise ValueError("values must be a 2D matrix.")
    n_rows, n_cols = mat.shape

    row_labels = _resolve_labels(
        n_rows, row_labels, param_name="row_labels", shape_desc="values.shape[0]"
    )
    col_labels = _resolve_labels(
        n_cols, col_labels, param_name="col_labels", shape_desc="values.shape[1]"
    )
    vmin, vmax = _auto_color_range(mat, clim)

    xs, ys, vals, ii, jj = [], [], [], [], []
    for i in range(n_rows):
        for j in range(n_cols):
            xs.append(col_labels[j])
            ys.append(
                row_labels[n_rows - 1 - i]
            )  # reversed so (0,0) is top-left visually
            vals.append(mat[i, j])
            ii.append(i)
            jj.append(j)

    source = ColumnDataSource(
        {
            "x": xs,
            "y": ys,
            "value": vals,
            "i": ii,
            "j": jj,
            "value_str": [("NA" if not np.isfinite(v) else f"{v:.4f}") for v in vals],
        }
    )

    mapper = LinearColorMapper(
        palette=palette, low=vmin, high=vmax, nan_color="#dddddd"
    )

    p = figure(
        title=title,
        x_range=col_labels,
        y_range=list(reversed(row_labels)),
        tools=_HEATMAP_TOOLS,
        toolbar_location="right",
        width=width,
        height=height,
        tooltips=None,
    )
    p.rect(
        x="x",
        y="y",
        width=1,
        height=1,
        source=source,
        line_color=None,
        fill_color={"field": "value", "transform": mapper},
    )

    if show_values_on_hover:
        hover = HoverTool(
            tooltips=[
                ("row (i)", "@i"),
                ("col (j)", "@j"),
                ("label row", "@y"),
                ("label col", "@x"),
                (value_label, _VALUE_STR_FIELD),
            ]
        )
        p.add_tools(hover)

    color_bar = ColorBar(
        color_mapper=mapper,
        location=(0, 0),
        ticker=BasicTicker(desired_num_ticks=8),
        formatter=PrintfTickFormatter(format="%.3f"),
        label_standoff=8,
    )
    p.add_layout(color_bar, "right")

    p.axis.major_label_text_font_size = "9pt"
    p.xaxis.major_label_orientation = 0.9
    p.grid.visible = False

    show(p, notebook_handle=True)


def plot_split_heatmap(
    values_a: np.ndarray,
    values_b: np.ndarray,
    *,
    row_labels: Optional[Sequence[str]] = None,
    col_labels: Optional[Sequence[str]] = None,
    title: str = "",
    label_a: str = "A",
    label_b: str = "B",
    palette=WHITE_RED_HAZARD_PALETTE,
    clim: tuple[float, float] = (0.0, 1.0),
    width: int = 900,
    height: int = 500,
):
    """
    Visualize two same-shaped NxM matrices as one heatmap, each cell split
    diagonally (top-left to bottom-right): the upper triangle is
    *values_a*, the lower triangle is *values_b*. A missing half (NaN)
    renders grey.

    Parameters
    ----------
    values_a, values_b : np.ndarray
        Two NxM matrices, same shape. NaN cells render grey for that half.
    row_labels, col_labels : list[str], optional
        Labels for each axis. Default to "0..N-1" / "0..M-1".
    title : str
        Plot title.
    label_a, label_b : str
        Names for *values_a* / *values_b* in hover tooltips.
    palette : sequence of colors
        Bokeh palette for both halves.
    clim : tuple[float, float]
        Fixed color limits (vmin, vmax) -- not auto-scaled, so both halves
        stay comparable.
    width, height : int
        Figure size in pixels.

    Returns
    -------
    bokeh.plotting.Figure
    """
    from deeporigin.utils.notebook import get_notebook_environment

    if get_notebook_environment() in ["marimo", "jupyter"]:
        from bokeh.io import output_notebook

        output_notebook(hide_banner=True)

    mat_a = np.asarray(values_a, dtype=float)
    mat_b = np.asarray(values_b, dtype=float)
    if mat_a.ndim != 2 or mat_b.ndim != 2:
        raise ValueError("values_a and values_b must be 2D matrices.")
    if mat_a.shape != mat_b.shape:
        raise ValueError("values_a and values_b must have the same shape.")
    n_rows, n_cols = mat_a.shape

    row_labels = _resolve_labels(
        n_rows, row_labels, param_name="row_labels", shape_desc="values.shape[0]"
    )
    col_labels = _resolve_labels(
        n_cols, col_labels, param_name="col_labels", shape_desc="values.shape[1]"
    )

    vmin, vmax = clim
    mapper = LinearColorMapper(palette=palette, low=vmin, high=vmax)

    source_a = _triangle_grid_source(mat_a, row_labels, col_labels, upper=True)
    source_b = _triangle_grid_source(mat_b, row_labels, col_labels, upper=False)

    p = figure(
        title=title,
        x_range=(0, n_cols),
        y_range=(0, n_rows),
        tools=_HEATMAP_TOOLS,
        toolbar_location="right",
        width=width,
        height=height,
        tooltips=None,
    )

    # Grey background -- shows through wherever a triangle isn't drawn (no data).
    p.rect(
        x=[j + 0.5 for j in range(n_cols) for _ in range(n_rows)],
        y=[n_rows - i - 0.5 for _ in range(n_cols) for i in range(n_rows)],
        width=1,
        height=1,
        line_color=None,
        fill_color="#dddddd",
    )

    fill = {"field": "value", "transform": mapper}
    renderer_a = p.patches(
        xs="xs",
        ys="ys",
        source=source_a,
        fill_color=fill,
        line_color="white",
        line_width=1,
    )
    renderer_b = p.patches(
        xs="xs",
        ys="ys",
        source=source_b,
        fill_color=fill,
        line_color="white",
        line_width=1,
    )

    p.add_tools(
        HoverTool(
            renderers=[renderer_a],
            tooltips=[
                ("ligand", "@row"),
                ("target", "@col"),
                (label_a, _VALUE_STR_FIELD),
            ],
        )
    )
    p.add_tools(
        HoverTool(
            renderers=[renderer_b],
            tooltips=[
                ("ligand", "@row"),
                ("target", "@col"),
                (label_b, _VALUE_STR_FIELD),
            ],
        )
    )

    color_bar = ColorBar(
        color_mapper=mapper,
        location=(0, 0),
        ticker=BasicTicker(desired_num_ticks=8),
        formatter=PrintfTickFormatter(format="%.3f"),
        label_standoff=8,
    )
    p.add_layout(color_bar, "right")

    p.xaxis.ticker = [j + 0.5 for j in range(n_cols)]
    p.xaxis.major_label_overrides = {
        j + 0.5: label for j, label in enumerate(col_labels)
    }
    p.yaxis.ticker = [n_rows - i - 0.5 for i in range(n_rows)]
    p.yaxis.major_label_overrides = {
        n_rows - i - 0.5: label for i, label in enumerate(row_labels)
    }
    p.xaxis.major_label_orientation = 0.9
    p.axis.major_label_text_font_size = "9pt"
    p.grid.visible = False

    show(p, notebook_handle=True)


def _generate_molecule_image(smiles: str) -> str | None:
    """Generate a base64-encoded image from a SMILES string.

    Args:
        smiles: SMILES string to render.

    Returns:
        Base64-encoded image data URL, or None if rendering fails.
    """
    import base64
    from io import BytesIO

    from rdkit import Chem
    from rdkit.Chem import Draw

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        img = Draw.MolToImage(mol, size=(200, 200))
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except Exception:
        return None


def _process_smiles_data(
    x: np.ndarray,
    y: np.ndarray,
    smiles_list: list[str],
) -> tuple[list, list, list, list, list]:
    """Process SMILES data and generate images for valid molecules.

    Args:
        x: X-coordinates for the scatter plot points.
        y: Y-coordinates for the scatter plot points.
        smiles_list: List of SMILES strings corresponding to each point.

    Returns:
        Tuple containing (valid_x, valid_y, valid_smiles, image_data, valid_idx).

    Raises:
        ValueError: If no valid SMILES strings are found.
    """
    image_data = []
    valid_smiles = []
    valid_x = []
    valid_y = []
    valid_idx = []

    for i, smiles in enumerate(smiles_list):
        image_str = _generate_molecule_image(smiles)
        if image_str is not None:
            image_data.append(image_str)
            valid_smiles.append(smiles)
            valid_x.append(x[i])
            valid_y.append(y[i])
            valid_idx.append(i)

    if not valid_x:
        raise ValueError("No valid SMILES strings found")

    return valid_x, valid_y, valid_smiles, image_data, valid_idx


def _create_hover_tooltip(x_label: str = "X", y_label: str = "Y") -> str:
    """Create HTML template for hover tooltip showing molecule images.

    Args:
        x_label: Label for the x-axis coordinate.
        y_label: Label for the y-axis coordinate.

    Returns:
        HTML template string for the hover tooltip.
    """
    return f"""
    <div>
        <img src="@image" width="200" height="200" style="float: left; margin: 0px 15px 15px 0px;" border="2"></img>
        <div style="float: left; width: 200px;">
            <div style="font-size: 12px; font-weight: bold;">Index:</div>
            <div style="font-size: 10px; font-family: monospace;">@index</div>
            <div style="font-size: 12px; font-weight: bold;">SMILES:</div>
            <div style="font-size: 10px; font-family: monospace;">@smiles</div>
            <div style="font-size: 12px; font-weight: bold; margin-top: 10px;">Coordinates:</div>
            <div style="font-size: 10px;">{x_label}: @x</div>
            <div style="font-size: 10px;">{y_label}: @y</div>
        </div>
    </div>
    """


def scatter(
    *,
    x: np.ndarray,
    y: np.ndarray,
    smiles_list: list[str],
    x_label: str = "X",
    y_label: str = "Y",
    title: str = "Scatter Plot",
    output_file: Optional[str] = None,
    x_lim_min: Optional[float] = None,
    x_lim_max: Optional[float] = None,
    y_lim_min: Optional[float] = None,
    y_lim_max: Optional[float] = None,
    width: int = 800,
    height: int = 800,
):
    """Create and display a Bokeh scatter plot with molecule images displayed on hover.

    The function automatically detects the environment (notebook vs script) and displays
    the plot appropriately - inline in notebooks or in a browser window for scripts.
    If output_file is provided, the plot is saved to an HTML file instead of being displayed.

    Args:
        x: X-coordinates for the scatter plot points.
        y: Y-coordinates for the scatter plot points.
        smiles_list: List of SMILES strings corresponding to each point. Must be the same length as x and y.
        x_label: Label for the x-axis. Defaults to "X".
        y_label: Label for the y-axis. Defaults to "Y".
        title: Title for the plot. Defaults to "Scatter Plot".
        output_file: Optional file path to save the HTML figure. If provided, the plot is saved to this file instead of being displayed. Defaults to None.
        x_lim_min: Optional minimum value for the x-axis. If provided, sets the lower bound of the x-axis. Defaults to None (auto-scale).
        x_lim_max: Optional maximum value for the x-axis. If provided, sets the upper bound of the x-axis. Defaults to None (auto-scale).
        y_lim_min: Optional minimum value for the y-axis. If provided, sets the lower bound of the y-axis. Defaults to None (auto-scale).
        y_lim_max: Optional maximum value for the y-axis. If provided, sets the upper bound of the y-axis. Defaults to None (auto-scale).
        width: Width of the plot in pixels. Defaults to 800.
        height: Height of the plot in pixels. Defaults to 800.

    Raises:
        ValueError: If the input arrays have different lengths or no valid SMILES strings found.
        ImportError: If RDKit is not available (required for molecule rendering).
    """
    # Validate input lengths
    if len(x) != len(y) or len(x) != len(smiles_list):
        raise ValueError("x, y, and smiles_list must all have the same length")

    # Convert to numpy arrays for consistency
    x = np.asarray(x)
    y = np.asarray(y)

    # Configure output for notebook environment
    from deeporigin.utils.notebook import get_notebook_environment

    environment = get_notebook_environment()
    if environment in ["marimo", "jupyter"]:
        from bokeh.io import output_notebook

        output_notebook(hide_banner=True)

    # Process SMILES data and generate images
    valid_x, valid_y, valid_smiles, image_data, valid_idx = _process_smiles_data(
        x, y, smiles_list
    )

    # Create ColumnDataSource for Bokeh plot
    source = ColumnDataSource(
        {
            "x": valid_x,
            "y": valid_y,
            "smiles": valid_smiles,
            "image": image_data,
            "index": valid_idx,
        }
    )

    # Create figure
    p = figure(
        title=title,
        x_axis_label=x_label,
        y_axis_label=y_label,
        tools="pan,wheel_zoom,box_zoom,reset,save,hover",
        toolbar_location="right",
        width=width,
        height=height,
    )

    # Add scatter points
    p.scatter(x="x", y="y", source=source, size=8, alpha=0.7, color="blue")

    # Set axis limits if provided
    if x_lim_min is not None:
        p.x_range.start = x_lim_min
    if x_lim_max is not None:
        p.x_range.end = x_lim_max
    if y_lim_min is not None:
        p.y_range.start = y_lim_min
    if y_lim_max is not None:
        p.y_range.end = y_lim_max

    # Configure hover tool to show molecule images
    hover = p.select_one(HoverTool)
    hover.tooltips = _create_hover_tooltip(x_label, y_label)
    hover.point_policy = "follow_mouse"

    # Save to file or show the figure
    if output_file is not None:
        save(p, output_file)
    else:
        show(p, notebook_handle=True)
