"""Visualization utilities for drug discovery in Jupyter notebooks."""

import pandas as pd


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
