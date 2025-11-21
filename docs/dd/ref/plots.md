# Plots

The `deeporigin.plots` module provides visualization functions for drug discovery data, including interactive scatter plots with molecular structure visualization.

## Functions

::: src.plots.scatter
    options:
      show_signature_annotations: true
      show_root_heading: true
      show_root_full_path: false
      heading_level: 3

## Examples

### Basic Scatter Plot with Molecule Images

```python
import numpy as np
from deeporigin.plots import scatter

# Sample data
x = np.array([1, 2, 3, 4, 5])
y = np.array([2, 4, 6, 8, 10])
smiles_list = [
    "CCO",           # ethanol
    "CC(=O)O",       # acetic acid
    "c1ccccc1",      # benzene
    "CCN(CC)CC",     # triethylamine
    "CC(C)O"         # isopropanol
]

# Create and display scatter plot
scatter(
    x=x, 
    y=y, 
    smiles_list=smiles_list, 
    x_label="X Coordinate", 
    y_label="Y Coordinate",
    title="Molecule Analysis Plot"
)
```

### Working with Drug Discovery Data

```{.python notest}
import pandas as pd
from deeporigin.plots import scatter

# Load data from a CSV file with SMILES and properties
df = pd.read_csv("ligand_data.csv")

# Create and display scatter plot of molecular weight vs logP
scatter(
    x=df["molecular_weight"].values,
    y=df["logp"].values,
    smiles_list=df["smiles"].tolist(),
    x_label="Molecular Weight (Da)",
    y_label="LogP",
    title="Drug Discovery: Molecular Properties Analysis"
)
```

### Saving Plot to HTML File

You can save the scatter plot to an HTML file instead of displaying it by providing the `output_file` parameter:

```python
import numpy as np
from deeporigin.plots import scatter

# Sample data
x = np.array([1, 2, 3, 4, 5])
y = np.array([2, 4, 6, 8, 10])
smiles_list = [
    "CCO",           # ethanol
    "CC(=O)O",       # acetic acid
    "c1ccccc1",      # benzene
    "CCN(CC)CC",     # triethylamine
    "CC(C)O"         # isopropanol
]

# Save scatter plot to HTML file
scatter(
    x=x, 
    y=y, 
    smiles_list=smiles_list, 
    x_label="X Coordinate", 
    y_label="Y Coordinate",
    title="Molecule Analysis Plot",
    output_file="scatter_plot.html"
)
```

When `output_file` is provided, the plot is saved as an interactive HTML file that can be opened in any web browser. The file includes all interactive features such as hover tooltips with molecule images.

### Setting Axis Limits

You can control the axis limits using individual `x_lim_min`, `x_lim_max`, `y_lim_min`, and `y_lim_max` parameters. This gives you fine-grained control - you can set just the minimum, just the maximum, or both:

```python
import numpy as np
from deeporigin.plots import scatter

# Sample data
x = np.array([1, 2, 3, 4, 5])
y = np.array([2, 4, 6, 8, 10])
smiles_list = [
    "CCO",           # ethanol
    "CC(=O)O",       # acetic acid
    "c1ccccc1",      # benzene
    "CCN(CC)CC",     # triethylamine
    "CC(C)O"         # isopropanol
]

# Create scatter plot with custom axis limits
scatter(
    x=x, 
    y=y, 
    smiles_list=smiles_list, 
    x_label="X Coordinate", 
    y_label="Y Coordinate",
    title="Molecule Analysis Plot",
    x_lim_min=0,      # Set x-axis minimum to 0
    x_lim_max=6,      # Set x-axis maximum to 6
    y_lim_max=12      # Set only y-axis maximum to 12 (min auto-scales)
)
```

Each limit parameter is optional and independent. If not provided, that limit will auto-scale based on the data range. This allows you to, for example, set only the maximum value for an axis while letting the minimum auto-scale.

## Features

- **Interactive Hover**: Hover over any point to see the molecular structure image
- **SMILES Validation**: Automatically filters out invalid SMILES strings
- **High-Quality Images**: Generates 200x200 pixel molecular structure images
- **Responsive Design**: Follows mouse movement for optimal user experience
- **Error Handling**: Gracefully handles invalid SMILES and rendering errors

## Requirements

The plots module requires the following optional dependencies:

- `bokeh`: For interactive plotting
- `rdkit`: For molecular structure rendering

Install them with:

```bash
pip install deeporigin[plots,tools]
```

## Notes

- Invalid SMILES strings are automatically filtered out
- If all SMILES strings are invalid, a `ValueError` is raised
- The function returns a Bokeh figure object that can be further customized
- Molecular images are generated at 200x200 pixels for optimal display
