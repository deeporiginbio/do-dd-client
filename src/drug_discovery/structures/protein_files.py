"""Find and check local protein structure files before a folder import.

import-dataset does not decompress ``.gz``, and in a batch it imports a file it
can't read as a protein with only its name, without failing the run. The
problems that can be seen locally are checked here instead (compressed,
missing, empty, unsupported, or no atom records), so every problem is reported
at once and nothing is uploaded when any file would fail. Files that share a file name are fine: like single
imports, each becomes its own protein.

:func:`build_protein_bundle` then writes the zip and CSV that import-dataset
takes, so the caller never builds them.
"""

from __future__ import annotations

from collections.abc import Sequence
import csv
from pathlib import Path
import zipfile

from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import (
    PROTEIN_FILES_REJECTED_TITLE,
    PROTEIN_FOLDER_CSV_MAPPER,
    PROTEIN_STRUCTURE_SUFFIXES,
)

_SUPPORTED_LABEL = ", ".join(PROTEIN_STRUCTURE_SUFFIXES)


def _is_compressed_structure(path: Path) -> bool:
    """Return True for a compressed structure file such as ``1abc.pdb.gz``."""
    suffixes = [s.lower() for s in path.suffixes]
    return (
        len(suffixes) >= 2
        and suffixes[-1] == ".gz"
        and suffixes[-2] in PROTEIN_STRUCTURE_SUFFIXES
    )


def _is_structure_candidate(path: Path) -> bool:
    """Return True for files a directory scan keeps: structures and compressed structures."""
    return (
        path.suffix.lower() in PROTEIN_STRUCTURE_SUFFIXES
        or _is_compressed_structure(path)
    )


def _is_system_file(relative: Path) -> bool:
    """Return True for hidden files or folders and macOS ``__MACOSX`` folders."""
    return any(part.startswith(".") or part == "__MACOSX" for part in relative.parts)


def find_structure_files(
    path: str | Path | Sequence[str | Path],
    *,
    recursive: bool = False,
) -> list[Path]:
    """Return the structure files a folder import would upload.

    A directory is scanned for ``.pdb``, ``.cif``, ``.mmcif`` and ``.ent`` files
    (any case), plus compressed copies of them so that
    :func:`validate_structure_files` can report those. Other files are skipped,
    as are hidden files and folders (such as macOS ``._*`` files) and
    ``__MACOSX`` folders left by unzipping on a Mac.
    A single file or a list of files is returned as given, unfiltered, so an
    unsupported file the caller named explicitly is reported, not skipped.

    Args:
        path: A directory, a single file, or a list of files.
        recursive: Also scan subdirectories. Only applies to a directory.

    Raises:
        DeepOriginException: ``path`` is a string or path that does not exist.
    """
    if isinstance(path, (str, Path)):
        root = Path(path).expanduser()
        if root.is_file():
            return [root]
        if not root.is_dir():
            raise DeepOriginException(
                title=PROTEIN_FILES_REJECTED_TITLE,
                message=f"{root} does not exist.",
                fix="Pass a folder of structure files, or a list of files.",
            )
        candidates = root.rglob("*") if recursive else root.glob("*")
        return sorted(
            p
            for p in candidates
            if p.is_file()
            and not _is_system_file(p.relative_to(root))
            and _is_structure_candidate(p)
        )
    return [Path(p).expanduser() for p in path]


def _file_problem(path: Path) -> str | None:
    """Return why one file can't be imported, or None when it can."""
    if not path.is_file():
        return "File not found."
    if _is_compressed_structure(path):
        return "Compressed files aren't supported. Decompress it first."
    if path.suffix.lower() not in PROTEIN_STRUCTURE_SUFFIXES:
        return f"Unsupported file type. Use {_SUPPORTED_LABEL}."
    if path.stat().st_size == 0:
        return "Empty file."
    if not _has_atom_records(path):
        return "No atom records found. Check that this is a protein structure file."
    return None


def _has_atom_records(path: Path) -> bool:
    """Return True when any line is an ``ATOM`` or ``HETATM`` record (PDB or mmCIF).

    PDB records start in column 1. mmCIF loop rows may be indented, so leading
    whitespace is ignored for ``.cif`` and ``.mmcif`` files.
    """
    is_cif = path.suffix.lower() in (".cif", ".mmcif")
    with path.open("rb") as handle:
        return any(
            (line.lstrip() if is_cif else line).startswith((b"ATOM", b"HETATM"))
            for line in handle
        )


def validate_structure_files(files: Sequence[Path]) -> None:
    """Raise one error listing every file that can't be imported.

    Checks each file for existence, a supported extension, compression, and
    content: the file must not be empty and must contain atom records.

    Args:
        files: Files from :func:`find_structure_files`.

    Raises:
        DeepOriginException: No files were given, or any file fails a check.
    """
    if not files:
        raise DeepOriginException(
            title=PROTEIN_FILES_REJECTED_TITLE,
            message="No structure files found.",
            fix=f"Supported file types: {_SUPPORTED_LABEL}. Pass recursive=True to search subfolders.",
        )

    problems = [(path, reason) for path in files if (reason := _file_problem(path))]

    if not problems:
        return
    width = max(len(str(p)) for p, _ in problems)
    lines = "\n".join(f"  {str(p):<{width}}  {reason}" for p, reason in problems)
    raise DeepOriginException(
        title=PROTEIN_FILES_REJECTED_TITLE,
        message=(
            f"{len(problems)} of {len(files)} files can't be imported. "
            f"Nothing was uploaded.\n\n{lines}"
        ),
        fix="Fix or remove these files, then try again.",
    )


def build_protein_bundle(
    files: Sequence[Path], out_dir: str | Path
) -> tuple[Path, Path]:
    """Write the zip and CSV import-dataset needs to import ``files`` as proteins.

    Each file is stored in the zip under a unique internal name (``00001.pdb``,
    ``00002.cif``, ...) that keeps its extension, so the tool still reads CIF as
    CIF. import-dataset finds zip entries and caches registrations by file name,
    so two files that share a name would otherwise become one protein. The CSV
    names each protein after its original file, without extension, as
    ``Protein.from_file`` does, and points at its zip entry. The columns match
    :data:`~deeporigin.utils.constants.PROTEIN_FOLDER_CSV_MAPPER`.

    Args:
        files: Files that passed :func:`validate_structure_files`.
        out_dir: An existing directory to write ``structures.zip`` and
            ``proteins.csv`` into.

    Returns:
        ``(zip_path, csv_path)``.
    """
    out_dir = Path(out_dir)
    zip_path = out_dir / "structures.zip"
    csv_path = out_dir / "proteins.csv"
    width = max(5, len(str(len(files))))
    columns = [entry["field"] for entry in PROTEIN_FOLDER_CSV_MAPPER]
    with (
        zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive,
        csv_path.open("w", newline="", encoding="utf-8") as handle,
    ):
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index, path in enumerate(files, start=1):
            entry = f"{index:0{width}d}{path.suffix.lower()}"
            archive.write(path, arcname=entry)
            writer.writerow({"protein_name": path.stem, "file_path": entry})
    return zip_path, csv_path
