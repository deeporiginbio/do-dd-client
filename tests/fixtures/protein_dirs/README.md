# Protein folder fixtures

Local folders of structure files for `projects.sync_proteins`. Each structure is a trimmed copy of a real fixture: its header records plus three residues of the first chain, so files stay a few KB and still parse. They are for local tests only, too small to be meaningful in a real import.

Each file becomes one protein named after its file name without extension, the same as `Protein.from_file(...).sync()`.

| Folder | Scenario | Expected result |
|---|---|---|
| `flat/` | Happy path, top level only | 5 files imported: `1eby` (from `1eby.cif`), `1eby` (from `1eby.pdb`), `4gih_prepared`, `af_model`, `brd`. `notes.txt` skipped. On the real platform `1eby.cif` and `1eby.pdb` hold the same coordinates, so import-dataset 4.x matches them to one protein |
| `nested/` | `top.pdb` (residues of the prepared 4GIH file), plus `holo/model.pdb` and `apo/model.pdb` | Top level only: `top`. Recursive: `model`, `model`, `top` (two proteins share a name, as two single imports would) |
| `nested_unique/` | `a/x.pdb` and `b/y.cif` | Top level only: no structures found. Recursive: `x`, `y` |
| `invalid/` | `ok.pdb`, `empty.pdb`, `compressed.pdb.gz`, `no_atoms.pdb` | Rejected before upload, naming the three bad files |
| `empty/` | No structure files | Rejected: no structures found |

Sources of the files in `flat/`, and what their headers contain:

| File | Source | Header |
|---|---|---|
| `brd.pdb` | `src/data/brd/brd.pdb` | None |
| `1eby.pdb` | `tests/fixtures/1eby.pdb` | `HEADER` id `1EBY`, `DBREF … UNP P03366` |
| `1eby.cif` | `tests/fixtures/1EBY.cif` | `_entry.id 1EBY`, `_struct_ref` UNP `P03366` |
| `4gih_prepared.pdb` | platform-toolbox `prepared-4gih/input.pdb` | Protein Prep stamp `DO_PREPARED`, `DO_PDB_ID 4GIH`; import-dataset 4.x sets `pdb_id` and `state=prepared` from it |
| `af_model.pdb` | Residues 44–46 of `src/data/brd/brd.pdb` with an AlphaFold-style header | Blank `HEADER` id, `DBREF XXXX … UNP O60885` |

Within a folder every file has different atoms, except `flat/1eby.pdb` and `flat/1eby.cif` (noted above). Across folders some files repeat: `nested/apo/model.pdb`, `nested_unique/a/x.pdb` and `invalid/ok.pdb` equal `flat/brd.pdb`; `nested/holo/model.pdb` equals `flat/1eby.pdb`; `nested_unique/b/y.cif` equals `flat/1eby.cif`. Importing several folders into one project therefore reuses those proteins.
