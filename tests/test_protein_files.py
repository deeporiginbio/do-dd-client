"""Tests for finding, checking and bundling local protein structure files."""

import csv
from pathlib import Path
import sys
import zipfile

import pytest

from deeporigin.drug_discovery.structures.protein_files import (
    build_protein_bundle,
    find_structure_files,
    validate_structure_files,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import PROTEIN_FOLDER_CSV_MAPPER

PROTEIN_DIRS = Path(__file__).parent / "fixtures" / "protein_dirs"


def _names(files: list[Path]) -> list[str]:
    return [p.name for p in files]


def _rejection(files: list[Path]) -> str:
    with pytest.raises(DeepOriginException) as excinfo:
        validate_structure_files(files)
    return excinfo.value.body


def test_flat_dir_keeps_structures_and_skips_other_files():
    """A flat folder yields its structures sorted, and skips notes.txt."""
    files = find_structure_files(PROTEIN_DIRS / "flat")

    assert _names(files) == [
        "1eby.cif",
        "1eby.pdb",
        "4gih_prepared.pdb",
        "af_model.pdb",
        "brd.pdb",
    ]
    validate_structure_files(files)


def test_dir_is_top_level_only_by_default():
    """Subfolders are ignored unless recursive=True."""
    assert _names(find_structure_files(PROTEIN_DIRS / "nested")) == ["top.pdb"]
    assert find_structure_files(PROTEIN_DIRS / "nested_unique") == []


def test_recursive_dir_finds_files_in_subfolders():
    """recursive=True finds structures at any depth."""
    files = find_structure_files(PROTEIN_DIRS / "nested_unique", recursive=True)

    assert _names(files) == ["x.pdb", "y.cif"]
    validate_structure_files(files)


def test_files_sharing_a_name_are_accepted():
    """Two model.pdb files in different subfolders are two proteins, as with single imports."""
    files = find_structure_files(PROTEIN_DIRS / "nested", recursive=True)

    assert [p.relative_to(PROTEIN_DIRS / "nested").as_posix() for p in files] == [
        "apo/model.pdb",
        "holo/model.pdb",
        "top.pdb",
    ]
    validate_structure_files(files)


def test_invalid_files_are_all_reported_at_once():
    """Compressed, empty and atom-less files are listed together; the valid file is not."""
    files = find_structure_files(PROTEIN_DIRS / "invalid")
    assert _names(files) == ["compressed.pdb.gz", "empty.pdb", "no_atoms.pdb", "ok.pdb"]

    body = _rejection(files)

    assert "3 of 4 files can't be imported. Nothing was uploaded." in body
    assert "compressed.pdb.gz" in body and "Decompress it first" in body
    assert "empty.pdb" in body and "Empty file" in body
    assert "no_atoms.pdb" in body and "No atom records found" in body
    assert "ok.pdb" not in body


def test_hetatm_only_file_is_accepted(tmp_path):
    """A file whose only coordinates are HETATM records still has atoms."""
    path = tmp_path / "ligand_only.pdb"
    path.write_text("HETATM    1  C1  LIG A   1       0.000   0.000   0.000\nEND\n")

    validate_structure_files([path])


@pytest.mark.parametrize("folder", ["empty", "nested_unique"])
def test_no_structures_found(folder):
    """A folder without top-level structures is rejected."""
    files = find_structure_files(PROTEIN_DIRS / folder)

    assert "No structure files found" in _rejection(files)


def test_explicit_files_are_kept_unfiltered_and_checked():
    """Files named by the caller are reported, not silently skipped."""
    files = find_structure_files(
        [
            PROTEIN_DIRS / "flat" / "brd.pdb",
            PROTEIN_DIRS / "flat" / "notes.txt",
            PROTEIN_DIRS / "flat" / "missing.pdb",
        ]
    )
    assert _names(files) == ["brd.pdb", "notes.txt", "missing.pdb"]

    body = _rejection(files)

    assert "notes.txt" in body and "Unsupported file type" in body
    assert "missing.pdb" in body and "File not found" in body
    assert "brd.pdb " not in body


def test_single_file_path():
    """A path to one structure file imports just that file."""
    path = PROTEIN_DIRS / "flat" / "1eby.pdb"

    assert find_structure_files(path) == [path]
    assert find_structure_files(str(path)) == [path]


def test_extensions_match_any_case(tmp_path):
    """Upper-case extensions such as .PDB and .CIF are found."""
    for name in ("A.PDB", "b.Cif", "c.mmcif", "d.ent", "e.sdf"):
        (tmp_path / name).write_text("ATOM\n")

    assert _names(find_structure_files(tmp_path)) == [
        "A.PDB",
        "b.Cif",
        "c.mmcif",
        "d.ent",
    ]


def test_hidden_and_macos_files_are_skipped(tmp_path):
    """macOS ``._*`` files, hidden folders and ``__MACOSX`` don't block the import."""
    for rel in ("a.pdb", "._a.pdb", ".cache/b.pdb", "__MACOSX/._a.pdb", "sub/c.pdb"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("ATOM\n")

    assert _names(find_structure_files(tmp_path)) == ["a.pdb"]
    assert _names(find_structure_files(tmp_path, recursive=True)) == ["a.pdb", "c.pdb"]


def test_indented_mmcif_atom_rows_are_accepted(tmp_path):
    """mmCIF loop rows may be indented; PDB records must start in column 1."""
    cif = tmp_path / "indented.cif"
    cif.write_text("data_x\nloop_\n_atom_site.group_PDB\n  ATOM 1 N\n")
    validate_structure_files([cif])

    pdb = tmp_path / "indented.pdb"
    pdb.write_text("  ATOM      1  N   ALA A   1\n")
    with pytest.raises(DeepOriginException):
        validate_structure_files([pdb])


def test_missing_path_raises(tmp_path):
    """A folder that does not exist is an error, not an empty import."""
    with pytest.raises(DeepOriginException) as excinfo:
        find_structure_files(tmp_path / "nope")

    assert "does not exist" in excinfo.value.body


def _read_bundle(zip_path: Path, csv_path: Path) -> tuple[list[dict], dict[str, bytes]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with zipfile.ZipFile(zip_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    return rows, entries


def test_bundle_gives_files_sharing_a_name_their_own_zip_entries(tmp_path):
    """Two model.pdb files get distinct zip entries and keep the name model."""
    files = find_structure_files(PROTEIN_DIRS / "nested", recursive=True)

    rows, entries = _read_bundle(*build_protein_bundle(files, tmp_path))

    assert rows == [
        {"protein_name": "model", "file_path": "00001.pdb"},
        {"protein_name": "model", "file_path": "00002.pdb"},
        {"protein_name": "top", "file_path": "00003.pdb"},
    ]
    assert list(entries) == ["00001.pdb", "00002.pdb", "00003.pdb"]
    assert [entries[row["file_path"]] for row in rows] == [
        p.read_bytes() for p in files
    ]


def test_bundle_keeps_each_file_type(tmp_path):
    """Extensions are kept (lowercased) so the tool parses CIF as CIF."""
    src = tmp_path / "src"
    src.mkdir()
    for name in ("A.PDB", "b.cif", "c.mmcif", "d.ent"):
        (src / name).write_text("ATOM\n")
    out = tmp_path / "out"
    out.mkdir()

    rows, entries = _read_bundle(*build_protein_bundle(find_structure_files(src), out))

    assert [(r["protein_name"], r["file_path"]) for r in rows] == [
        ("A", "00001.pdb"),
        ("b", "00002.cif"),
        ("c", "00003.mmcif"),
        ("d", "00004.ent"),
    ]
    assert sorted(entries) == ["00001.pdb", "00002.cif", "00003.mmcif", "00004.ent"]


def test_bundle_csv_quotes_awkward_names(tmp_path):
    """Names with commas, quotes, spaces or extra dots survive the CSV."""
    src = tmp_path / "src"
    src.mkdir()
    names = ["7DH5 (1).pdb", "1AKI..pdb", "a,b c.pdb"]
    if sys.platform != "win32":  # Windows filenames cannot contain a double quote
        names.append('a,b "c".pdb')
    for name in names:
        (src / name).write_text("ATOM\n")
    out = tmp_path / "out"
    out.mkdir()

    rows, _ = _read_bundle(*build_protein_bundle(find_structure_files(src), out))

    assert sorted(r["protein_name"] for r in rows) == sorted(
        Path(n).stem for n in names
    )


def test_bundle_columns_match_the_mapper(tmp_path):
    """Every CSV column is mapped, and every mapped field is a CSV column."""
    files = find_structure_files(PROTEIN_DIRS / "flat")

    _, csv_path = build_protein_bundle(files, tmp_path)
    header = csv_path.read_text(encoding="utf-8").splitlines()[0].split(",")

    assert header == [entry["field"] for entry in PROTEIN_FOLDER_CSV_MAPPER]
