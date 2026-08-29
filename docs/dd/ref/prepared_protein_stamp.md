# Prepared Protein stamp

Helpers that detect and preserve the file-borne Prepared Protein stamp on
structure files.

| Format | Stamp |
|--------|--------|
| PDB | `REMARK  99 DO_PREPARED` |
| mmCIF | `_deeporigin.prepared     DO_PREPARED` |

Protein Prep writes this stamp onto the prepared structure before upload.
Downstream tools (Pocket Finder, Docking, System Prep) skip automatic protein
cleanup when the stamp is present. The CLI must not drop it when rewriting or
syncing a protein that already points at a stamped remote file.

## Marking a protein as prepared

If you prepare a protein outside Deep Origin and want downstream tools to treat
it as already prepared, stamp the on-disk file with
[`Protein.mark_as_prepared()`](protein.md):

```{.python notest}
from deeporigin.drug_discovery import Protein

protein = Protein.from_file("my_prepared.cif")  # or .pdb
protein.mark_as_prepared()  # mutates the local file in its native format
protein.sync()              # uploads the stamped bytes to UFA
```

`mark_as_prepared()` never converts CIF to PDB (or vice versa). Prefer platform
[Protein Prep](../tools/proteinprep.md) when you want Deep Origin to prepare the
structure for you.

Client `to_pdb()` / `to_cif()` translate the stamp across formats when the
source was stamped. External converters (for example PyMOL “save as”) may still
drop it — re-run `mark_as_prepared()` on the saved file if needed.

Toolbox AUTO cleanup for stamped mmCIF is rolled out separately; stamped PDBs
are already honoured.

::: src.drug_discovery.structures.prepared_protein_stamp
    options:
      docstring_style: google
      show_root_heading: false
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      members_order: alphabetical
      filters:
        - "!^_"
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true
