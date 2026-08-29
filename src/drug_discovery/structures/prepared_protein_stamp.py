"""Prepared Protein stamp: file-borne DO_PREPARED token for PDB and mmCIF.

Mirrors the platform-toolbox stamp helper so the CLI can detect and preserve
the stamp without depending on ``toolbox_core``. Downstream Pocket Finder,
Docking, and System Prep skip AUTO protein cleanup when the token is present.

PDB uses ``REMARK  99 DO_PREPARED``. mmCIF uses
``_deeporigin.prepared     DO_PREPARED`` (a private data item — not a PDB
REMARK line embedded in CIF text).
"""

from __future__ import annotations

from pathlib import Path

from deeporigin.utils.constants import (
    PREPARED_PROTEIN_CIF_STAMP_KEY,
    PREPARED_PROTEIN_CIF_STAMP_LINE,
    PREPARED_PROTEIN_CIF_STAMP_VALUE,
    PREPARED_PROTEIN_STAMP_LINE,
)

_STAMP_BYTES = (PREPARED_PROTEIN_STAMP_LINE + "\n").encode("ascii")

_CIF_SUFFIXES = frozenset({".cif", ".mmcif"})
_PDB_SUFFIXES = frozenset({".pdb", ".pdbqt"})


def text_has_prepared_protein_stamp(text: str) -> bool:
    """Return True if a REMARK 99 DO_PREPARED token appears before ATOM/HETATM.

    Whitespace around the remark number is lenient so a one-space rewrite still
    matches. The writer always emits the canonical two-space line.

    This is PDB-only. Accidental REMARK text inside an mmCIF file must not be
    treated as prepared — use :func:`text_has_prepared_protein_cif_stamp` for
    CIF.

    Args:
        text: PDB file contents as text.
    """
    for line in text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            return False
        parts = line.split()
        if (
            len(parts) >= 3
            and parts[0] == "REMARK"
            and parts[1] == "99"
            and parts[2] == "DO_PREPARED"
        ):
            return True
    return False


def text_has_prepared_protein_cif_stamp(text: str) -> bool:
    """Return True if the canonical mmCIF Prepared Protein stamp is present.

    Matches ``_deeporigin.prepared`` with value ``DO_PREPARED``. Does not treat
    PDB-style ``REMARK  99 DO_PREPARED`` text inside CIF as prepared.

    Args:
        text: mmCIF file contents as text.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if (
            len(parts) >= 2
            and parts[0] == PREPARED_PROTEIN_CIF_STAMP_KEY
            and parts[1].strip("\"'") == PREPARED_PROTEIN_CIF_STAMP_VALUE
        ):
            return True
    return False


def _is_cif_path(path: Path) -> bool:
    """Return True if *path* should be treated as mmCIF by extension."""
    return path.suffix.lower() in _CIF_SUFFIXES


def _is_pdb_path(path: Path) -> bool:
    """Return True if *path* should be treated as PDB by extension."""
    return path.suffix.lower() in _PDB_SUFFIXES


def _sniff_cif_text(text: str) -> bool:
    """Return True if *text* looks like mmCIF (``data_`` header)."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.startswith("data_")
    return False


def has_prepared_protein_stamp(path: str | Path) -> bool:
    """Return True if the file carries a Prepared Protein stamp for its format.

    PDB/``.pdb`` files use the REMARK 99 token. CIF/``.cif`` / ``.mmcif`` files
    use ``_deeporigin.prepared``. When the suffix is ambiguous, sniff the
    contents (``data_`` ⇒ CIF, otherwise PDB).

    Args:
        path: Local structure file path to inspect.
    """
    file_path = Path(path)
    text = file_path.read_bytes().decode("latin-1")
    if _is_cif_path(file_path) or (
        not _is_pdb_path(file_path) and _sniff_cif_text(text)
    ):
        return text_has_prepared_protein_cif_stamp(text)
    return text_has_prepared_protein_stamp(text)


def stamp_prepared_protein_pdb(path: str | Path) -> None:
    """Prepend the canonical Prepared Protein PDB stamp if not already present.

    Uses a text prepend, not a structure rewrite, so ATOM/HETATM bytes are
    unchanged. Idempotent when a PDB stamp is already present.

    Args:
        path: Local PDB path to stamp.

    Raises:
        OSError: If the file cannot be read or written.
        FileNotFoundError: If *path* does not exist.
    """
    pdb_path = Path(path)
    text = pdb_path.read_bytes().decode("latin-1")
    if text_has_prepared_protein_stamp(text):
        return
    body = pdb_path.read_bytes()
    pdb_path.write_bytes(_STAMP_BYTES + body)  # NOSONAR local path, not external input


def stamp_prepared_protein_cif(path: str | Path) -> None:
    """Insert the canonical mmCIF Prepared Protein stamp if not already present.

    Inserts ``_deeporigin.prepared     DO_PREPARED`` immediately after the first
    ``data_`` line when present, otherwise at the start of the file. Does not
    rewrite atom sites. Idempotent when the CIF stamp is already present.

    Args:
        path: Local mmCIF path to stamp.

    Raises:
        OSError: If the file cannot be read or written.
        FileNotFoundError: If *path* does not exist.
    """
    cif_path = Path(path)
    raw = cif_path.read_bytes()
    text = raw.decode("utf-8")
    if text_has_prepared_protein_cif_stamp(text):
        return

    lines = text.splitlines(keepends=True)
    insert_at = 0
    for index, line in enumerate(lines):
        if line.lstrip().startswith("data_"):
            insert_at = index + 1
            break

    stamp_line = PREPARED_PROTEIN_CIF_STAMP_LINE + "\n"
    lines.insert(insert_at, stamp_line)
    cif_path.write_bytes("".join(lines).encode("utf-8"))  # NOSONAR local path


def stamp_prepared_protein(path: str | Path) -> None:
    """Stamp a structure file in its native format (PDB or mmCIF).

    Dispatches on file extension (and content sniff when needed). Never
    converts CIF to PDB or vice versa.

    Args:
        path: Local PDB or mmCIF path to stamp.

    Raises:
        OSError: If the file cannot be read or written.
        FileNotFoundError: If *path* does not exist.
        ValueError: If the format cannot be determined.
    """
    file_path = Path(path)
    if _is_cif_path(file_path):
        stamp_prepared_protein_cif(file_path)
        return
    if _is_pdb_path(file_path):
        stamp_prepared_protein_pdb(file_path)
        return

    text = file_path.read_bytes().decode("latin-1")
    if _sniff_cif_text(text):
        stamp_prepared_protein_cif(file_path)
        return
    if text.lstrip().startswith(("HEADER", "TITLE", "REMARK", "ATOM", "HETATM")):
        stamp_prepared_protein_pdb(file_path)
        return
    raise ValueError(
        f"Cannot determine structure format for {file_path}; "
        "expected a .pdb / .cif / .mmcif file."
    )
