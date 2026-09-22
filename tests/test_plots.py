"""Tests for the plots module."""

from unittest.mock import patch

import numpy as np
import pytest

from deeporigin.plots import (
    _create_hover_tooltip,
    plot_grid_heatmap,
    plot_heatmap,
    scatter,
)


def test_scatter_basic_functionality():
    """Test basic scatter plot functionality with valid SMILES."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([2, 4, 6, 8, 10])
    smiles_list = [
        "CCO",  # ethanol
        "CC(=O)O",  # acetic acid
        "c1ccccc1",  # benzene
        "CCN(CC)CC",  # triethylamine
        "CC(C)O",  # isopropanol
    ]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Verify show was called with a figure
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        assert hasattr(figure, "scatter")
        assert figure.title.text == "Scatter Plot"
        assert figure.xaxis.axis_label == "X"
        assert figure.yaxis.axis_label == "Y"
        assert figure.width == 800
        assert figure.height == 800


def test_scatter_invalid_lengths():
    """Test that ValueError is raised when input arrays have different lengths."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with pytest.raises(ValueError, match="must all have the same length"):
        scatter(x=x, y=y, smiles_list=smiles_list)


def test_scatter_invalid_smiles():
    """Test handling of invalid SMILES strings."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["invalid_smiles", "CCO", "another_invalid"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Verify show was called with a figure
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        assert hasattr(figure, "scatter")


def test_scatter_all_invalid_smiles():
    """Test that ValueError is raised when all SMILES are invalid."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["invalid1", "invalid2", "invalid3"]

    with pytest.raises(ValueError, match="No valid SMILES strings found"):
        scatter(x=x, y=y, smiles_list=smiles_list)


def test_scatter_empty_inputs():
    """Test handling of empty input arrays."""
    x = np.array([])
    y = np.array([])
    smiles_list = []

    with pytest.raises(ValueError, match="No valid SMILES strings found"):
        scatter(x=x, y=y, smiles_list=smiles_list)


def test_scatter_with_lists():
    """Test that function works with Python lists as well as numpy arrays."""
    x = [1, 2, 3]
    y = [1, 2, 3]
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Verify show was called with a figure
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        assert hasattr(figure, "scatter")


def test_scatter_figure_properties():
    """Test that the figure has expected properties."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Check figure properties
        assert figure.title.text == "Scatter Plot", "Unexpected title"
        assert figure.xaxis.axis_label == "X", "Unexpected x-axis label"
        assert figure.yaxis.axis_label == "Y", "Unexpected y-axis label"
        assert figure.width == 800, "Unexpected width"
        assert figure.height == 800, "Unexpected height"

        # Check that hover tool is present
        hover_tools = [
            tool for tool in figure.tools if tool.__class__.__name__ == "HoverTool"
        ]
        assert len(hover_tools) == 1


def test_scatter_custom_labels():
    """Test that custom axis labels are applied correctly."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(
            x=x,
            y=y,
            smiles_list=smiles_list,
            x_label="Molecular Weight",
            y_label="LogP",
        )

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Check that custom labels are applied
        assert figure.xaxis.axis_label == "Molecular Weight"
        assert figure.yaxis.axis_label == "LogP"


def test_scatter_custom_title():
    """Test that custom title is applied correctly."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, title="My Custom Plot Title")

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Check that custom title is applied
        assert figure.title.text == "My Custom Plot Title"


def test_scatter_data_source_structure():
    """Test that the ColumnDataSource has the expected structure."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Get the data source from the figure
        renderers = figure.renderers
        scatter_renderer = None
        for renderer in renderers:
            if hasattr(renderer, "data_source"):
                scatter_renderer = renderer
                break

        assert scatter_renderer is not None
        data_source = scatter_renderer.data_source.data

        # Verify data structure
        assert "x" in data_source
        assert "y" in data_source
        assert "smiles" in data_source
        assert "image" in data_source

        # Verify data lengths match
        assert len(data_source["x"]) == len(smiles_list)
        assert len(data_source["y"]) == len(smiles_list)
        assert len(data_source["smiles"]) == len(smiles_list)
        assert len(data_source["image"]) == len(smiles_list)


def test_scatter_molecule_images():
    """Test that molecule images are generated correctly."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Get the data source from the figure
        renderers = figure.renderers
        scatter_renderer = None
        for renderer in renderers:
            if hasattr(renderer, "data_source"):
                scatter_renderer = renderer
                break

        assert scatter_renderer is not None
        data_source = scatter_renderer.data_source.data

        # Verify that images are base64 encoded data URLs
        for image_data in data_source["image"]:
            assert image_data.startswith("data:image/png;base64,")
            # Verify it's not empty
            assert len(image_data) > len("data:image/png;base64,")


def test_scatter_hover_tooltip():
    """Test that hover tooltip contains expected information."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Find the hover tool
        hover_tools = [
            tool for tool in figure.tools if tool.__class__.__name__ == "HoverTool"
        ]
        assert len(hover_tools) == 1

        hover_tool = hover_tools[0]
        tooltips = hover_tool.tooltips

        # Verify tooltip contains expected elements
        assert "@image" in tooltips
        assert "@smiles" in tooltips
        assert "@x" in tooltips
        assert "@y" in tooltips


def test_create_hover_tooltip_default_labels():
    """Test that _create_hover_tooltip uses default labels when none provided."""
    tooltip = _create_hover_tooltip()

    # Check that default labels are used
    assert "X: @x" in tooltip
    assert "Y: @y" in tooltip
    assert "@image" in tooltip
    assert "@smiles" in tooltip
    assert "@index" in tooltip


def test_create_hover_tooltip_custom_labels():
    """Test that _create_hover_tooltip uses custom labels when provided."""
    tooltip = _create_hover_tooltip("Molecular Weight", "LogP")

    # Check that custom labels are used
    assert "Molecular Weight: @x" in tooltip
    assert "LogP: @y" in tooltip
    assert "@image" in tooltip
    assert "@smiles" in tooltip
    assert "@index" in tooltip


def test_scatter_hover_tooltip_custom_labels():
    """Test that scatter plot hover tooltip uses custom axis labels."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(
            x=x,
            y=y,
            smiles_list=smiles_list,
            x_label="Molecular Weight",
            y_label="LogP",
        )

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Find the hover tool
        hover_tools = [
            tool for tool in figure.tools if tool.__class__.__name__ == "HoverTool"
        ]
        assert len(hover_tools) == 1

        hover_tool = hover_tools[0]
        tooltips = hover_tool.tooltips

        # Verify tooltip uses custom labels
        assert "Molecular Weight: @x" in tooltips
        assert "LogP: @y" in tooltips
        assert "@image" in tooltips
        assert "@smiles" in tooltips
        assert "@index" in tooltips


def test_scatter_save_to_file(tmp_path):
    """Test that scatter plot can be saved to a file when output_file is provided."""

    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]
    output_path = tmp_path / "test_scatter.html"

    with (
        patch("deeporigin.plots.show") as mock_show,
        patch("deeporigin.plots.save") as mock_save,
    ):
        scatter(x=x, y=y, smiles_list=smiles_list, output_file=str(output_path))

        # Verify save was called instead of show
        mock_save.assert_called_once()
        mock_show.assert_not_called()

        # Verify the figure was passed to save
        figure = mock_save.call_args[0][0]
        assert hasattr(figure, "scatter")
        assert figure.title.text == "Scatter Plot"

        # Verify the file path was passed correctly
        assert mock_save.call_args[0][1] == str(output_path)


def test_scatter_save_to_file_with_custom_properties(tmp_path):
    """Test that scatter plot saved to file retains custom properties."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]
    output_path = tmp_path / "custom_scatter.html"

    with (
        patch("deeporigin.plots.show") as mock_show,
        patch("deeporigin.plots.save") as mock_save,
    ):
        scatter(
            x=x,
            y=y,
            smiles_list=smiles_list,
            x_label="Molecular Weight",
            y_label="LogP",
            title="Custom Plot",
            output_file=str(output_path),
        )

        # Verify save was called
        mock_save.assert_called_once()
        mock_show.assert_not_called()

        # Verify the figure has custom properties
        figure = mock_save.call_args[0][0]
        assert figure.title.text == "Custom Plot"
        assert figure.xaxis.axis_label == "Molecular Weight"
        assert figure.yaxis.axis_label == "LogP"


def test_scatter_default_behavior_without_output_file():
    """Test that scatter plot shows by default when output_file is not provided."""
    x = np.array([1, 2])
    y = np.array([1, 2])
    smiles_list = ["CCO", "CC(=O)O"]

    with (
        patch("deeporigin.plots.show") as mock_show,
        patch("deeporigin.plots.save") as mock_save,
    ):
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Verify show was called and save was not
        mock_show.assert_called_once()
        mock_save.assert_not_called()


def test_scatter_x_lim_min():
    """Test that x_lim_min parameter sets x-axis minimum correctly."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1", "CCN(CC)CC", "CC(C)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, x_lim_min=0.5)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify x-axis minimum is set correctly
        assert figure.x_range.start == 0.5


def test_scatter_x_lim_max():
    """Test that x_lim_max parameter sets x-axis maximum correctly."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1", "CCN(CC)CC", "CC(C)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, x_lim_max=5.5)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify x-axis maximum is set correctly
        assert figure.x_range.end == 5.5


def test_scatter_x_lim_both():
    """Test that both x_lim_min and x_lim_max parameters work together."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1", "CCN(CC)CC", "CC(C)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, x_lim_min=0.5, x_lim_max=5.5)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify x-axis limits are set correctly
        assert figure.x_range.start == 0.5
        assert figure.x_range.end == 5.5


def test_scatter_y_lim_min():
    """Test that y_lim_min parameter sets y-axis minimum correctly."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1", "CCN(CC)CC", "CC(C)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, y_lim_min=0.0)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify y-axis minimum is set correctly
        assert figure.y_range.start == 0.0


def test_scatter_y_lim_max():
    """Test that y_lim_max parameter sets y-axis maximum correctly."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1", "CCN(CC)CC", "CC(C)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, y_lim_max=6.0)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify y-axis maximum is set correctly
        assert figure.y_range.end == 6.0


def test_scatter_y_lim_both():
    """Test that both y_lim_min and y_lim_max parameters work together."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1", "CCN(CC)CC", "CC(C)O"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, y_lim_min=0.0, y_lim_max=6.0)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify y-axis limits are set correctly
        assert figure.y_range.start == 0.0
        assert figure.y_range.end == 6.0


def test_scatter_all_lim():
    """Test that all limit parameters work together."""
    x = np.array([1, 2, 3])
    y = np.array([10, 20, 30])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(
            x=x,
            y=y,
            smiles_list=smiles_list,
            x_lim_min=0,
            x_lim_max=4,
            y_lim_min=5,
            y_lim_max=35,
        )

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify all axis limits are set correctly
        assert figure.x_range.start == 0
        assert figure.x_range.end == 4
        assert figure.y_range.start == 5
        assert figure.y_range.end == 35


def test_scatter_lim_with_output_file(tmp_path):
    """Test that axis limits work when saving to file."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]
    output_path = tmp_path / "test_scatter_lim.html"

    with patch("deeporigin.plots.save") as mock_save:
        scatter(
            x=x,
            y=y,
            smiles_list=smiles_list,
            x_lim_min=0,
            x_lim_max=4,
            y_lim_min=0,
            y_lim_max=4,
            output_file=str(output_path),
        )

        # Get the figure that was passed to save
        figure = mock_save.call_args[0][0]

        # Verify axis limits are set correctly
        assert figure.x_range.start == 0
        assert figure.x_range.end == 4
        assert figure.y_range.start == 0
        assert figure.y_range.end == 4


def test_scatter_custom_width_height():
    """Test that custom width and height parameters are applied correctly."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list, width=1200, height=600)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify custom width and height are set correctly
        assert figure.width == 1200
        assert figure.height == 600


def test_scatter_default_width_height():
    """Test that default width and height are used when not specified."""
    x = np.array([1, 2, 3])
    y = np.array([1, 2, 3])
    smiles_list = ["CCO", "CC(=O)O", "c1ccccc1"]

    with patch("deeporigin.plots.show") as mock_show:
        scatter(x=x, y=y, smiles_list=smiles_list)

        # Get the figure that was passed to show
        figure = mock_show.call_args[0][0]

        # Verify default width and height
        assert figure.width == 800
        assert figure.height == 800


def test_plot_heatmap_basic_square_matrix():
    """plot_heatmap renders a square matrix."""
    values = np.array([[0.0, 1.0], [1.0, 0.0]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_heatmap(values, labels=["A", "B"], title="Heatmap")

        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        assert figure.title.text == "Heatmap"


def test_plot_heatmap_non_square_raises():
    """plot_heatmap rejects non-square matrices."""
    values = np.array([[0.0, 1.0, 2.0], [1.0, 0.0, 2.0]])

    with pytest.raises(ValueError, match="square NxN matrix"):
        plot_heatmap(values)


def test_plot_heatmap_label_length_mismatch():
    """plot_heatmap validates label length against matrix size."""
    values = np.array([[0.0, 1.0], [1.0, 0.0]])

    with pytest.raises(ValueError, match="Length of `labels`"):
        plot_heatmap(values, labels=["only-one"])


def test_plot_heatmap_nan_and_custom_clim():
    """plot_heatmap handles NaNs and explicit color limits."""
    values = np.array([[np.nan, 2.0], [2.0, 2.0]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_heatmap(values, clim=(0.0, 5.0))

        mock_show.assert_called_once()


def test_plot_heatmap_degenerate_color_scale():
    """plot_heatmap widens identical vmin/vmax values."""
    values = np.array([[2.0, 2.0], [2.0, 2.0]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_heatmap(values)

        mock_show.assert_called_once()


def test_plot_grid_heatmap_rectangular():
    """plot_grid_heatmap renders an NxM matrix with independent row/col labels."""
    values = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_grid_heatmap(values, row_labels=["r1", "r2"], col_labels=["c1", "c2", "c3"])

        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        assert list(figure.x_range.factors) == ["c1", "c2", "c3"]
        assert list(figure.y_range.factors) == ["r2", "r1"]


def test_plot_grid_heatmap_default_labels():
    """plot_grid_heatmap defaults to 0..N-1 / 0..M-1 when labels are omitted."""
    values = np.array([[1.0, 2.0]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_grid_heatmap(values)

        figure = mock_show.call_args[0][0]
        assert list(figure.x_range.factors) == ["0", "1"]
        assert list(figure.y_range.factors) == ["0"]


def test_plot_grid_heatmap_label_length_mismatch():
    """plot_grid_heatmap validates row/col label lengths independently."""
    values = np.array([[1.0, 2.0], [3.0, 4.0]])

    with pytest.raises(ValueError, match="row_labels"):
        plot_grid_heatmap(values, row_labels=["only-one"])

    with pytest.raises(ValueError, match="col_labels"):
        plot_grid_heatmap(values, col_labels=["only-one"])


def test_plot_grid_heatmap_non_2d_raises():
    """plot_grid_heatmap rejects non-2D input."""
    with pytest.raises(ValueError, match="2D matrix"):
        plot_grid_heatmap(np.array([1.0, 2.0, 3.0]))


def test_plot_grid_heatmap_x_axis_at_bottom():
    """Column labels render at the bottom, not the top (matches platform-ui)."""
    values = np.array([[1.0, 2.0]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_grid_heatmap(values)

        figure = mock_show.call_args[0][0]
        assert figure.xaxis[0] in figure.below
        assert figure.xaxis[0] not in figure.above


def test_white_red_hazard_palette_matches_platform_ui_stops():
    """The hazard palette's endpoints/midpoint match platform-ui's WhiteRed scale exactly."""
    from deeporigin.plots import WHITE_RED_HAZARD_PALETTE

    assert len(WHITE_RED_HAZARD_PALETTE) == 256
    assert WHITE_RED_HAZARD_PALETTE[0] == "#FFFFFF"
    assert WHITE_RED_HAZARD_PALETTE[-1] == "#641D1A"
    assert WHITE_RED_HAZARD_PALETTE[128] == "#D93E39"


def test_plot_split_heatmap_skips_nan_per_triangle_independently():
    """Each triangle's NaN cells are skipped without affecting the other triangle."""
    from deeporigin.plots import plot_split_heatmap

    values_a = np.array([[0.9, 0.1], [np.nan, 0.5]])
    values_b = np.array([[0.8, np.nan], [0.3, 0.4]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_split_heatmap(
            values_a,
            values_b,
            row_labels=["lig1", "lig2"],
            col_labels=["EGFR", "BRAF"],
            label_a="p_active",
            label_b="pose_score",
        )
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]

    patch_renderers = [r for r in figure.renderers if r.glyph.__class__.__name__ == "Patches"]
    assert len(patch_renderers) == 2
    values = [sorted(r.data_source.data["value"]) for r in patch_renderers]
    assert sorted(values) == [[0.1, 0.5, 0.9], [0.3, 0.4, 0.8]]


def test_plot_split_heatmap_shape_mismatch_raises():
    """plot_split_heatmap requires both matrices to be the same shape."""
    from deeporigin.plots import plot_split_heatmap

    with pytest.raises(ValueError, match="same shape"):
        plot_split_heatmap(np.zeros((2, 2)), np.zeros((2, 3)))


def test_plot_split_heatmap_fixed_clim_not_auto_scaled():
    """clim is fixed, not derived from the data -- the two halves stay comparable."""
    from deeporigin.plots import plot_split_heatmap

    values_a = np.array([[0.9]])
    values_b = np.array([[0.9]])

    with patch("deeporigin.plots.show") as mock_show:
        plot_split_heatmap(values_a, values_b, clim=(0.0, 1.0))
        figure = mock_show.call_args[0][0]

    from bokeh.models import LinearColorMapper

    mapper = figure.select_one({"type": LinearColorMapper})
    assert mapper.low == 0.0
    assert mapper.high == 1.0
