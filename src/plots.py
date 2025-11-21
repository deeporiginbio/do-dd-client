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
        tools="pan,wheel_zoom,box_zoom,reset,save",
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
                ("RMSD", "@value_str"),
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
