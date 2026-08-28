"""Prepared Protein stamp: file-borne REMARK 99 DO_PREPARED token.

Mirrors the platform-toolbox stamp helper so the CLI can detect and preserve
the stamp without depending on ``toolbox_core``. Downstream Pocket Finder,
Docking, and System Prep skip AUTO protein cleanup when the token is present.
"""

from __future__ import annotations

from pathlib import Path

from deeporigin.utils.constants import PREPARED_PROTEIN_STAMP_LINE

_STAMP_BYTES = (PREPARED_PROTEIN_STAMP_LINE + "\n").encode("ascii")


def text_has_prepared_protein_stamp(text: str) -> bool:
    """Return True if a REMARK 99 DO_PREPARED token appears before ATOM/HETATM.

    Whitespace around the remark number is lenient so a one-space rewrite still
    matches. The writer always emits the canonical two-space line.

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


def has_prepared_protein_stamp(path: str | Path) -> bool:
    """Return True if a REMARK 99 DO_PREPARED token appears before ATOM/HETATM.

    Args:
        path: Local PDB path to inspect.
    """
    text = Path(path).read_bytes().decode("latin-1")
    return text_has_prepared_protein_stamp(text)


def stamp_prepared_protein_pdb(path: str | Path) -> None:
    """Prepend the canonical Prepared Protein stamp if it is not already present.

    Uses a text prepend, not a structure rewrite, so ATOM/HETATM bytes are
    unchanged. Idempotent when :func:`has_prepared_protein_stamp` is already
    true.

    Args:
        path: Local PDB path to stamp.

    Raises:
        OSError: If the file cannot be read or written.
        FileNotFoundError: If *path* does not exist.
    """
    pdb_path = Path(path)
    if has_prepared_protein_stamp(pdb_path):
        return
    body = pdb_path.read_bytes()
    pdb_path.write_bytes(
        _STAMP_BYTES + body
    )  # NOSONAR path is a local file path supplied by the trusted caller, not external input
