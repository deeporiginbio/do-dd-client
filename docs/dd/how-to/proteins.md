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

### From a name

You can search for a protein by name and create a Protein instance from the top search result:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_name("insulin")
```

### From a Deep Origin Data Platform ID

You can create a Protein instance directly from a Deep Origin Data Platform ID. This method fetches the protein data from the platform, downloads the structure file, and creates a Protein instance with metadata from the platform:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_id("08AD337N5YV4Y")
```

The method automatically:

- Downloads the structure file from the Deep Origin Data Platform
- Sets the protein's ID, name, and PDB ID (if available) from the platform metadata
- Creates a Protein instance from the downloaded file

You can optionally provide a custom `DeepOriginClient` instance:

```python
from deeporigin.drug_discovery import Protein
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
protein = Protein.from_id("08AD337N5YV4Y", client=client)
```

!!! note "Records without file_path"
    If the platform record has no `file_path`, `from_id` returns metadata only:
    `structure` is `None` and `remote_path` is unset unless you pass
    `remote_path_override`. Call `download()` only after a structure file path
    is available on the record or via override.

!!! note "Automatic metadata"
    The method automatically populates the protein's `name` field from the platform data, preferring `protein_name`, then `pdb_id`, then `gene_symbol` (in that order).


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

### Listing chain names

You can list all unique chain IDs in the protein structure:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
chain_names = protein.list_chain_names()
print(chain_names)
```

!!! success "Expected output"
    ```
    ['A', 'B']
    ```

### Listing hetero residue names

You can list all unique hetero (non-protein) residue names in the structure:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
hetero_names = protein.list_hetero_names(exclude_water=True)
print(hetero_names)
```

This is useful for identifying ligands, cofactors, and other heteroatoms present in the structure.

### Extracting metals and cofactors

You can extract and categorize metal ions and cofactors from the protein structure:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
metals, cofactors = protein.extract_metals_and_cofactors()
print(f"Metals: {metals}")
print(f"Cofactors: {cofactors}")
```

This method returns a tuple of two lists: metal residue names and cofactor residue names.

### Getting the number of atoms

You can get the total number of atoms in the protein structure:

```python
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
num_atoms = protein.num_atoms
print(num_atoms)
```

### Finding pockets

You can find potential binding pockets in the protein structure. See [PocketFinder](../tools/pocketfinder.md) for detailed information.

```{.python notest}
from deeporigin.drug_discovery import PocketFinder, Protein

protein = Protein.from_pdb_id("1EBY")
pf = PocketFinder(protein, pocket_count=5)
pockets = pf.run()
```

### Preparing a protein

Clean a structure (keep/remove lists, loop modelling, protonation) with
[ProteinPrep](../tools/proteinprep.md). Protein Prep is async-only: `start()`,
then `wait()` or `watch()`, then `get_results()`.

```{.python notest}
from deeporigin.drug_discovery import Protein, ProteinPrep

protein = Protein.from_pdb_id("1EBY")
prep = ProteinPrep(protein)
prep.start()
prep.wait()
prepared = prep.get_results()
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
    height="610" 
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

### Check ligand pose clashes

Use :meth:`Protein.has_ligand_clashes` to verify that a docked ligand pose does not
sterically overlap the receptor. The ligand SDF must already be in the same coordinate
frame as the protein structure.

```python
from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

if protein.has_ligand_clashes(BRD_DATA_DIR / "brd-2.sdf"):
    raise ValueError("Pose has steric clashes with receptor")

# Use a stricter cutoff (default is 2.5 Å)
if protein.has_ligand_clashes(BRD_DATA_DIR / "brd-2.sdf", contact_distance=2.0):
    raise ValueError("Pose is too close to receptor atoms")
```

By default, the check compares the ligand against protein atoms only (excluding HETATM
records and waters) and ignores hydrogens. Customize this with ``protein_atoms_only``,
``exclude_waters``, and ``heavy_atoms_only``.

!!! warning "Method mutates the `Protein` object"
    The `extract_ligand()` method not only extracts the ligand but also **mutates the protein object** by removing the ligand from the protein structure. This means that after calling this method, the protein will no longer contain the ligand atoms.

!!! note "Water molecules are automatically excluded"
    The `extract_ligand()` method automatically filters out water molecules (HOH, WAT, H2O) and other excluded residue names. You can customize which residues to exclude by passing the `exclude_resnames` parameter:
    
    ```python
    # Exclude custom residue names
    ligand = protein.extract_ligand(exclude_resnames={"HOH", "CUSTOM_RES"})
    ```

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
    height="610" 
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

!!! warning "Method mutates the `Protein` object"
    The `model_loops()` method **mutates the protein object** by updating its structure with the modeled loops.

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

# Remove only water molecules (mutates in place)
protein.remove_water()
```

### Chain Selection

You can select specific chains from the protein structure. These methods return **new Protein objects** and do not modify the original:

```{.python notest}
# Select a single chain (returns new Protein object)
chain_a = protein.select_chain('A')

# Select multiple chains (returns new Protein object)
chains_ab = protein.select_chains(['A', 'B'])
```

!!! note "Returns new object"
    Unlike most modification methods, `select_chain()` and `select_chains()` return new Protein objects rather than mutating the original.



### Saving a protein structure

You can save the protein structure to a PDB file:

```{.python notest}
from deeporigin.drug_discovery import Protein

protein = Protein.from_pdb_id("1EBY")
protein.remove_water()

file_path = protein.to_pdb("prepared_protein.pdb")
```

If no file path is provided, the protein will be saved to a default location based on its hash.

!!! note "Platform proteins without a local file"
    If the protein was loaded with `from_id(..., download=False)`, it has `remote_path`
    but no local file yet. Call `download(client=...)` before `to_pdb()` or `to_file()`,
    or use `from_id(..., download=True)`.

### Docking ligands

You can dock ligands into pockets of the protein. See the [Docking guide](docking.md) for detailed information.

```{.python notest}
from deeporigin.drug_discovery import PocketFinder, Protein, Ligand, BRD_DATA_DIR

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
pf = PocketFinder(protein, pocket_count=1)
pockets = pf.run()

# Dock ligand into the first pocket
poses = protein.dock(ligand=ligand, pocket=pockets[0])
```

## Best Practices

1. Always visualize the structure before and after preparation to ensure the desired changes were made
2. When working with metalloproteins, use `remove_hetatm()` with appropriate `keep_resnames` or `remove_metals` parameters
3. For multi-chain proteins, consider selecting specific chains before preparation
4. Save the prepared structure using `to_pdb()` if you need to use it outside of Deep Origin APIs.

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
