"""Render Bokeh scatter plots from ``benchmark_docking_results.csv``.

Three square scatter subplots in one row: time vs effort, binding energy vs
effort, time vs binding energy. Each ligand is a distinct color (identify via hover).

Requires optional deps: ``uv sync --extra core --extra plots`` (pandas + bokeh).

Example:

    uv run --extra core --extra plots python scripts/plot_benchmark_docking.py
    uv run --extra core --extra plots python scripts/plot_benchmark_docking.py \\
        --csv scripts/benchmark_docking_results.csv --output /tmp/docking.html
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from beartype import beartype
from bokeh.layouts import gridplot
from bokeh.models import ColumnDataSource, HoverTool
from bokeh.palettes import Viridis256, linear_palette
from bokeh.plotting import figure, output_file, save
from bokeh.transform import factor_cmap
import pandas as pd

DEFAULT_CSV = Path(__file__).resolve().parent / "benchmark_docking_results.csv"
DEFAULT_HTML = Path(__file__).resolve().parent / "benchmark_docking_plots.html"


@beartype
def _ligand_palette(factors: list[str]) -> list[str]:
    """Return a distinct hex color for each ligand id (ordered)."""
    n = len(factors)
    if n == 0:
        return []
    return list(linear_palette(Viridis256, n))


@beartype
def _add_ligand_scatter(
    *,
    p: figure,
    source: ColumnDataSource,
    x: str,
    y: str,
    factors: list[str],
    palette: list[str],
    title: str,
    x_axis_label: str,
    y_axis_label: str,
) -> None:
    """Add one colored scatter layer and hover for ``ligand_id``."""
    cmap = factor_cmap("ligand_id", palette=palette, factors=factors)
    scatter_kw: dict[str, Any] = {
        "size": 10,
        "alpha": 0.85,
        "line_color": "white",
        "line_width": 0.5,
        "fill_color": cmap,
    }
    r = p.scatter(x, y, source=source, **scatter_kw)
    p.title.text = title
    p.xaxis.axis_label = x_axis_label
    p.yaxis.axis_label = y_axis_label
    p.add_tools(
        HoverTool(
            renderers=[r],
            tooltips=[
                ("ligand", "@ligand_id"),
                ("effort", "@effort"),
                ("time (s)", "@time_taken{0.000}"),
                ("binding energy", "@binding_energy{0.000}"),
                ("repeat", "@repeat_number"),
            ],
        )
    )


def build_figure(df: pd.DataFrame) -> Any:
    """Lay out three square scatter subplots in one row."""
    factors = sorted(df["ligand_id"].astype(str).unique().tolist())
    palette = _ligand_palette(factors)

    # Plot 1: all rows with effort + time
    d1 = df.dropna(subset=["effort", "time_taken"]).copy()
    s1 = ColumnDataSource(d1)

    # Plots 2–3 need binding energy
    d_be = df.dropna(subset=["effort", "binding_energy"]).copy()
    s2 = ColumnDataSource(d_be)

    d_te = df.dropna(subset=["time_taken", "binding_energy"]).copy()
    s3 = ColumnDataSource(d_te)

    plot_size = 420
    common_kw = {
        "width": plot_size,
        "height": plot_size,
        "toolbar_location": "above",
        "tools": "pan,wheel_zoom,box_zoom,reset,save",
    }

    p1 = figure(**common_kw)
    _add_ligand_scatter(
        p=p1,
        source=s1,
        x="effort",
        y="time_taken",
        factors=factors,
        palette=palette,
        title="Time vs effort",
        x_axis_label="effort",
        y_axis_label="time (s)",
    )

    p2 = figure(**common_kw)
    _add_ligand_scatter(
        p=p2,
        source=s2,
        x="effort",
        y="binding_energy",
        factors=factors,
        palette=palette,
        title="Binding energy vs effort",
        x_axis_label="effort",
        y_axis_label="binding energy (kcal/mol)",
    )

    p3 = figure(**common_kw)
    _add_ligand_scatter(
        p=p3,
        source=s3,
        x="binding_energy",
        y="time_taken",
        factors=factors,
        palette=palette,
        title="Time vs binding energy",
        x_axis_label="binding energy (kcal/mol)",
        y_axis_label="time (s)",
    )

    return gridplot(
        [[p1, p2, p3]],
        sizing_mode="stretch_width",
        merge_tools=True,
    )


def main(*, csv_path: Path, output_html: Path) -> None:
    """Load CSV and write a single HTML file with all subplots."""
    df = pd.read_csv(csv_path)
    needed = {"ligand_id", "effort", "time_taken", "binding_energy", "repeat_number"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")

    layout = build_figure(df)
    output_file(output_html, title="Benchmark docking")
    save(layout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bokeh scatter plots from benchmark_docking_results.csv",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Input CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_HTML,
        help=f"Output HTML (default: {DEFAULT_HTML})",
    )
    args = parser.parse_args()
    main(csv_path=args.csv, output_html=args.output)
