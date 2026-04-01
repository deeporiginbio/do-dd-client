This document describes how to filter the outputs of Docking based on various properties.

!!! warning "Deprecated: `Complex`"
    The examples below use the deprecated [`Complex`](../ref/complex.md) type. New workflows should use [`Docking`](../ref/docking.md) (and related APIs) instead of `Complex.docking`.

Here we assume that you have constructed a `Complex` object and successfully run [Docking](../tutorial/docking.md).
Following convention, we assume that the `Complex` object is called `sim`.

## Fetch docked poses

First, we get the results of Docking in a pandas DataFrame using:

```{.python notest}
poses = sim.docking.get_poses()
```
Inspecting the `poses` object shows us:

<div style='width: 500px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; background-color: #f9f9f9;'><h3 style='margin-top: 0; color: #333;'>LigandSet with 2246 ligands</h3><p style='margin: 8px 0;'><strong>157</strong> unique SMILES</p><p style='margin: 8px 0;'>Properties: Binding Energy, POSE SCORE, SCORE, SMILES, initial_smiles</p><div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'><p style='margin: 4px 0; font-size: 0.9em; color: #666;'><em>Use <code>.to_dataframe()</code> to convert to a dataframe, <code>.show_df()</code> to view dataframewith structures, or <code>.show()</code> for 3D visualization</em></p></div></div>

## Plot docking results

The metrics of all docked poses can be plotted in a scatter plot using:

```{.python notest}
poses.plot()
```

<iframe 
    src="../../images/docking-scatter.html" 
    width="100%" 
    height="660" 
    style="border:none;"
    title="Scatter plot of docking scores"
></iframe>

## Pick top results

We can pick the top pose for each SMILES string using:

```{.python notest}
poses.filter_top_poses()
```