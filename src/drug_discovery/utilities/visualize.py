"""Visualization utilities for drug discovery using Jupyter notebooks.

This module provides decorators and utilities for visualizing molecular structures
and other drug discovery related data in Jupyter notebooks using the DeepOrigin Molstar viewer.
"""

from deeporigin_molstar import JupyterViewer
import pandas as pd


def jupyter_visualization(func):
    """Decorator for converting HTML visualization output to Jupyter notebook display.

    This decorator wraps functions that generate HTML visualizations and converts
    their output to be properly displayed in Jupyter notebooks using the DeepOrigin
    Molstar viewer.

    Args:
        func (callable): A function that returns HTML visualization content.

    Returns:
        callable: A wrapped function that returns a JupyterViewer visualization.

    Example:
        @jupyter_visualization
        def generate_molecule_view(molecule):
            # Generate HTML visualization
            return html_content
    """

    def wrapper(*args, **kwargs):
        html_visualization = func(*args, **kwargs)
        return JupyterViewer.visualize(html_visualization)

    return wrapper


def render_smiles_in_dataframe(df: pd.DataFrame, smiles_col: str) -> pd.DataFrame:
    """Use RDKit to render SMILES structures in a dataframe.

    Args:
        df (pd.DataFrame): DataFrame containing a SMILES column.
        smiles_col (str): Name of the column containing SMILES strings.

    Returns:
        pd.DataFrame: DataFrame with an added 'Structure' column containing rendered molecules.
    """
    if smiles_col not in df.columns:
        raise ValueError(f"Column '{smiles_col}' not found in DataFrame.")

    from rdkit.Chem import PandasTools

    df[smiles_col] = df[smiles_col].fillna("")

    PandasTools.AddMoleculeColumnToFrame(df, smilesCol=smiles_col, molCol="Structure")
    PandasTools.RenderImagesInAllDataFrames()

    new_order = ["Structure"] + [col for col in df.columns if col != "Structure"]
    df = df[new_order]

    return df
