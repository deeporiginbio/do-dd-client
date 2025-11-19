This document describes how to work with proteins and use them in Deep Origin tools. 

## The `Protein` class

The [`Protein` class](../ref/protein.md)  is the primary way to work with proteins in Deep Origin.

## Constructing a protein


### From a file

A protein can be constructed from a file:

```python
from deeporigin.drug_discovery import Protein, BRD_DATA_DIR
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
```

### From a PDB ID

A protein can also be constructed from a PDB ID:


```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
```


## Inspecting the Protein

### PDB ID

To view the PDB ID of a Protein (if it exists), use:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
protein.pdb_id
```

!!! success "Expected output"
    ```
    1EBY
    ```

### Getting the protein sequence

You can retrieve the amino acid sequences of all polypeptide chains in a protein structure using the `sequence` property:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
sequences = protein.sequence

for seq in sequences:
    print(seq)
```

This property returns a list of amino acid sequences (as Bio.Seq objects) for each polypeptide chain found in the structure. If the structure contains multiple chains, each chain's sequence is included as a separate entry in the list. This is useful for analyzing the primary structure of the protein or for downstream sequence-based analyses.

!!! success "Expected output"
    ```
    PQITLWQRPLVTIKIGGQLKEALLDTGADDTVLEEMNLPGRWKPKMIGGIGGFIKVRQYDQILIEICGHKAIGTVLVGPTPVNIIGRNLLTQIGCTLNF
    PQITLWQRPLVTIKIGGQLKEALLDTGADDTVLEEMNLPGRWKPKMIGGIGGFIKVRQYDQILIEICGHKAIGTVLVGPTPVNIIGRNLLTQIGCTLNF
    ```

### Finding missing residues

You can identify missing residues (gaps) in the protein structure using the `find_missing_residues` method:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("5QSP")
missing = protein.find_missing_residues()
print(missing)
```

This method scans each chain in the protein and returns a dictionary where the keys are chain IDs and the values are lists of tuples, each representing a gap. Each tuple is of the form `(start_resseq, end_resseq)`, indicating that residues between `start_resseq` and `end_resseq` (exclusive) are missing from the structure.

!!! success "Expected output"
    ```python
    {'A': [(511, 514), (547, 550), (679, 682), (841, 855)],
     'B': [(509, 516), (546, 551), (679, 684), (840, 854)]}
    ```
    

### Visualizing a protein

??? warning "Browser support"
    These visualizations work best on Google Chrome. We are aware of issues on other browsers, especially Safari on macOS.

A protein object can be visualized using `show`:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
protein.show()
```

A visualization such as this will be shown:

<iframe 
    src="../../images/1eby.html" 
    width="100%" 
    height="600" 
    style="border:none;"
    title="Protein visualization"
></iframe>

!!! info "Jupyter notebook required"
    Visualizations such as these require this code to be run in a jupyter notebook. We recommend using [these instructions](../../install.md) to install Jupyter.



## Modifying and preparing a protein


### Extract crystal ligands

When PDB files contain a crystal ligand, the crystal ligand can be removed from the structure and used as a Ligand. 


```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
ligand = protein.extract_ligand()
```

!!! warning "Method mutates the `Protein` object"
    The `extract_ligand()` method not only extracts the ligand but also **mutates the protein object** by removing the ligand from the protein structure. This means that after calling this method, the protein will no longer contain the ligand atoms.


!!! note "Note about atom counts"
    In this example, the atom count might not change significantly because the ligand atoms are typically a small fraction of the total protein structure. However, the protein's internal structure and `block_content` are updated to exclude the ligand. Additionally, the PDB file's MASTER record is automatically updated to reflect the new atom and CONECT record counts.


### Loop modelling 

Missing information and gaps in the structure can be filled in using the Loop Modelling tool. 

For example, this protein from the PDB has missing elements, as can be seen from the dashed lines below:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("5QSP")
protein.show()
```

<iframe 
    src="../../images/5QSP.html" 
    width="100%" 
    height="600" 
    style="border:none;"
    title="Protein visualization"
></iframe>

We can verify that there are missing residues using the `find_missing_residues` method:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("5QSP")
protein.find_missing_residues()
```

!!! success "Expected output"
    ```
    {'A': [(511, 514), (547, 550), (679, 682), (841, 855)],
     'B': [(509, 516), (546, 551), (679, 684), (840, 854)]}
    ```


We can use the loop modelling tool to fix this structure using:


```{.python notest}
protein.model_loops()
protein.show()
```

<iframe 
    src="../../images/5QSP-lm.html" 
    width="100%" 
    height="600" 
    style="border:none;"
    title="Protein visualization"
></iframe>

We can verify that there are no missing residues anymore:

```{.python notest}
protein.find_missing_residues()
```

!!! success "Expected output"
    ```
    {}
    ```


??? info "How does loop modelling work?"

    The current implementation of LoopModeling tool can use known experimental or predicted structures to fill gaps in given protein structure.

    The tool works by searching for potential templates for each chain with missing residues in Protein Data Bank (PDB) and specified directory of templates. If the PDB contains the Uniprot IDs, this can also be used to download the predicted AlphaFold2 structures from AF Structural Database.

    First, for each chain the full sequence and the sequence of the resolved structure are extracted and aligned to identify gaps as continuous groups of missing residues. If gaps are found the PDB database is searched for templates using specified sequence identity threshold. Structures in the additional template directory and AF structure are added for consideration.

    For each template, global 3D alignment is first performed and an attempt is made to transfer the motifs corresponding to missing residues in the target if corresponding residues are present in the given template. The success is evaluated based on CA-CA distances at the edges of the gap and sequence identity of the residues to be transferred.

    If the global alignment fails for the given gap, the local alignment is attempted using the specified number of residues adjacent to the gap and the transfer of the structural motif is again attempted.

    Based on each found template, a model is constructed with structural motifs that were successfully matched. If the b_mixed_models flag is on, the attempt will be made to fill the gaps where matching was not successful using models based on other templates, sorted by resolution.

    Finally, the results for all chains are combined to obtain N possible structures using best models obtained for each chain.

### Removing specific residues

You can remove specific residue names from a protein structure using the `remove_resnames` method:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")

# Remove water molecules (HOH) and ions (NA, CL)
protein.remove_resnames(exclude_resnames=["HOH", "NA", "CL"])
```

!!! note "Residue name format"
    Residue names in PDB files are always uppercase (e.g., "HOH" for water, "NA" for sodium, "CL" for chloride).

This method modifies the protein structure in place by removing the specified residue names. If no residue names are provided, the protein structure remains unchanged.

### Removing HETATM records

You can remove HETATM records from the protein structure using the `remove_hetatm` method:

```python

from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")

# Remove all HETATM records except water and zinc
protein.remove_hetatm(keep_resnames=["HOH"], remove_metals=["ZN"])
```

This method modifies the protein structure in place by removing HETATM records (heteroatoms) from the structure. You can:

- Keep specific residues by providing their names in `keep_resnames`
- Keep specific metals by providing their names in `remove_metals` (these metals will be excluded from removal)
- If no arguments are provided, all HETATM records will be removed

!!! note "Metal names"
    Metal names should be provided in uppercase (e.g., "ZN" for zinc, "FE" for iron).

### Removing water molecules

You can remove all water molecules from a protein structure using the `remove_water` method:

```python

from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")

protein.remove_water()
```

This method modifies the protein structure in place by removing all water molecules (residue name "HOH"). Unlike `remove_resnames`, this method does not return a new protein structure but instead modifies the existing one.


### Removing Specific Residues

You can remove specific residue types while keeping others:

```python

from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")


# Remove specific residue names
protein.remove_resnames(exclude_resnames=["HOH", "SO4"])

# Remove only water molecules
protein_no_water = protein.remove_water()
```

### Chain Selection

You can select specific chains from the protein structure:

```{.python notest}
# Select a single chain
chain_a = protein.select_chain('A')

# Select multiple chains
chains_ab = protein.select_chains(['A', 'B'])
```



## Best Practices

1. Always visualize the structure before and after preparation to ensure the desired changes were made
2. When working with metalloproteins, use `remove_hetatm()` with appropriate `keep_resnames` or `remove_metals` parameters
3. For multi-chain proteins, consider selecting specific chains before preparation
4. Save the prepared structure using `to_pdb()` if you need to use it later:

```{.python notest}
# Save the prepared structure
protein.to_pdb("prepared_protein.pdb")
```

## Common Use Cases

### Preparing a Protein for Docking

```{.python notest}
# Load and prepare protein
protein = Protein.from_pdb_id("1EBY")
protein.remove_water()  # Remove water molecules
protein.remove_hetatm(keep_resnames=['ZN'])  # Keep important cofactors
protein.to_pdb("docking_ready.pdb")
```

### Working with Metalloproteins

```{.python notest}
# Load and prepare metalloprotein
protein = Protein.from_pdb_id("1XYZ")
protein.remove_hetatm(remove_metals=['ZN', 'MG'])  # Keep metal ions
protein.show()
```

### Multi-chain Protein Preparation

```{.python notest}
# Load and prepare multi-chain protein
protein = Protein.from_pdb_id("1ABC")
chains_ab = protein.select_chains(['A', 'B'])  # Select chains A and B
chains_ab.remove_water()  # Remove water from selected chains
chains_ab.show()
```
