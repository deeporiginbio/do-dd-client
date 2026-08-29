"""Tests for Prepared Protein stamp helpers and stamp-preserving Protein I/O."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery.structures.prepared_protein_stamp import (
    has_prepared_protein_stamp,
    stamp_prepared_protein,
    stamp_prepared_protein_cif,
    stamp_prepared_protein_pdb,
    text_has_prepared_protein_cif_stamp,
    text_has_prepared_protein_stamp,
)
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import (
    PREPARED_PROTEIN_CIF_STAMP_LINE,
    PREPARED_PROTEIN_STAMP_LINE,
)

_MINIMAL_ATOM = (
    "ATOM      1  N   ALA A   1      11.104  13.207   9.068  1.00  0.00           N\n"
    "END\n"
)

_MINIMAL_CIF = """data_test
#
_atom_site.id 1
#
"""

_FIXTURE_CIF = Path(__file__).parent / "fixtures" / "1EBY.cif"


def test_text_has_prepared_protein_stamp_detects_canonical_line() -> None:
    """Canonical REMARK  99 DO_PREPARED before ATOM is detected."""
    text = f"{PREPARED_PROTEIN_STAMP_LINE}\n{_MINIMAL_ATOM}"
    assert text_has_prepared_protein_stamp(text) is True


def test_text_has_prepared_protein_stamp_lenient_whitespace() -> None:
    """One-space REMARK 99 still matches (reader is lenient)."""
    text = f"REMARK 99 DO_PREPARED\n{_MINIMAL_ATOM}"
    assert text_has_prepared_protein_stamp(text) is True


def test_text_has_prepared_protein_stamp_false_after_atom() -> None:
    """Stamp after the first ATOM/HETATM does not count."""
    text = f"{_MINIMAL_ATOM}{PREPARED_PROTEIN_STAMP_LINE}\n"
    assert text_has_prepared_protein_stamp(text) is False


def test_text_has_prepared_protein_stamp_absent() -> None:
    """Unstamped PDB text returns False."""
    assert text_has_prepared_protein_stamp(_MINIMAL_ATOM) is False


def test_stamp_prepared_protein_pdb_is_idempotent(tmp_path: Path) -> None:
    """stamp_prepared_protein_pdb prepends once and is a no-op thereafter."""
    pdb_path = tmp_path / "protein.pdb"
    pdb_path.write_text(_MINIMAL_ATOM)
    assert has_prepared_protein_stamp(pdb_path) is False

    stamp_prepared_protein_pdb(pdb_path)
    assert has_prepared_protein_stamp(pdb_path) is True
    first = pdb_path.read_bytes()

    stamp_prepared_protein_pdb(pdb_path)
    assert pdb_path.read_bytes() == first
    assert pdb_path.read_text().startswith(PREPARED_PROTEIN_STAMP_LINE + "\n")


def test_stamp_prepared_protein_cif_is_idempotent(tmp_path: Path) -> None:
    """stamp_prepared_protein_cif inserts once and is a no-op thereafter."""
    cif_path = tmp_path / "protein.cif"
    cif_path.write_text(_MINIMAL_CIF)
    assert has_prepared_protein_stamp(cif_path) is False

    stamp_prepared_protein_cif(cif_path)
    assert has_prepared_protein_stamp(cif_path) is True
    first = cif_path.read_bytes()
    assert PREPARED_PROTEIN_CIF_STAMP_LINE in cif_path.read_text()

    stamp_prepared_protein_cif(cif_path)
    assert cif_path.read_bytes() == first


def test_pdb_remark_text_inside_cif_is_not_prepared(tmp_path: Path) -> None:
    """Accidental PDB REMARK text in a CIF file does not count as prepared."""
    cif_path = tmp_path / "accidental.cif"
    cif_path.write_text(f"data_test\n{PREPARED_PROTEIN_STAMP_LINE}\n_atom_site.id 1\n")
    assert text_has_prepared_protein_stamp(cif_path.read_text()) is True
    assert text_has_prepared_protein_cif_stamp(cif_path.read_text()) is False
    assert has_prepared_protein_stamp(cif_path) is False


def test_stamp_prepared_protein_dispatches_by_extension(tmp_path: Path) -> None:
    """stamp_prepared_protein stamps PDB and CIF without converting formats."""
    pdb_path = tmp_path / "a.pdb"
    pdb_path.write_text(_MINIMAL_ATOM)
    stamp_prepared_protein(pdb_path)
    assert pdb_path.read_text().startswith(PREPARED_PROTEIN_STAMP_LINE)

    cif_path = tmp_path / "b.cif"
    cif_path.write_text(_MINIMAL_CIF)
    stamp_prepared_protein(cif_path)
    assert PREPARED_PROTEIN_CIF_STAMP_LINE in cif_path.read_text()
    assert not cif_path.read_text().startswith("REMARK")


def test_protein_to_pdb_preserves_do_prepared_stamp(tmp_path: Path) -> None:
    """biotite rewrite via to_pdb re-prepends DO_PREPARED when the source had it."""
    stamped = tmp_path / "stamped.pdb"
    stamped.write_text(f"{PREPARED_PROTEIN_STAMP_LINE}\n{_MINIMAL_ATOM}")
    protein = Protein.from_file(stamped)
    assert has_prepared_protein_stamp(stamped) is True

    out = tmp_path / "rewritten.pdb"
    protein.to_pdb(out)
    assert has_prepared_protein_stamp(out) is True
    assert out.read_text().startswith(PREPARED_PROTEIN_STAMP_LINE + "\n")


def test_protein_to_pdb_does_not_add_stamp_when_source_unstamped(
    tmp_path: Path,
) -> None:
    """to_pdb does not invent a stamp for unstamped sources."""
    plain = tmp_path / "plain.pdb"
    plain.write_text(_MINIMAL_ATOM)
    protein = Protein.from_file(plain)

    out = tmp_path / "rewritten.pdb"
    protein.to_pdb(out)
    assert has_prepared_protein_stamp(out) is False


def test_protein_mark_as_prepared_stamps_pdb_in_place(tmp_path: Path) -> None:
    """mark_as_prepared stamps a PDB local_path without changing extension."""
    pdb_path = tmp_path / "protein.pdb"
    pdb_path.write_text(_MINIMAL_ATOM)
    protein = Protein.from_file(pdb_path)

    result = protein.mark_as_prepared()
    assert result is protein
    assert has_prepared_protein_stamp(pdb_path) is True
    assert pdb_path.suffix == ".pdb"
    assert protein.local_path == str(pdb_path)


def test_protein_mark_as_prepared_stamps_cif_without_pdb_conversion(
    tmp_path: Path,
) -> None:
    """mark_as_prepared stamps CIF in place and never writes a PDB."""
    cif_path = tmp_path / "protein.cif"
    cif_path.write_text(_FIXTURE_CIF.read_text())
    protein = Protein.from_file(cif_path)

    protein.mark_as_prepared()
    assert has_prepared_protein_stamp(cif_path) is True
    assert cif_path.suffix == ".cif"
    assert PREPARED_PROTEIN_CIF_STAMP_LINE in cif_path.read_text()
    assert list(tmp_path.glob("*.pdb")) == []


def test_protein_mark_as_prepared_requires_local_path() -> None:
    """mark_as_prepared raises when there is no readable local_path."""
    protein = Protein(name="no-file", structure=None, local_path=None)
    with pytest.raises(DeepOriginException, match="local_path"):
        protein.mark_as_prepared()


def test_protein_to_cif_translates_pdb_stamp(tmp_path: Path) -> None:
    """to_cif writes the mmCIF stamp when the PDB source was stamped."""
    stamped = tmp_path / "stamped.pdb"
    stamped.write_text(f"{PREPARED_PROTEIN_STAMP_LINE}\n{_MINIMAL_ATOM}")
    protein = Protein.from_file(stamped)

    out = tmp_path / "out.cif"
    protein.to_cif(out)
    assert has_prepared_protein_stamp(out) is True
    assert text_has_prepared_protein_cif_stamp(out.read_text()) is True


def test_protein_to_pdb_translates_cif_stamp(tmp_path: Path) -> None:
    """to_pdb writes the PDB stamp when the CIF source was stamped."""
    stamped = tmp_path / "stamped.cif"
    stamped.write_text(_FIXTURE_CIF.read_text())
    stamp_prepared_protein_cif(stamped)
    protein = Protein.from_file(stamped)

    out = tmp_path / "out.pdb"
    protein.to_pdb(out)
    assert has_prepared_protein_stamp(out) is True
    assert out.read_text().startswith(PREPARED_PROTEIN_STAMP_LINE + "\n")


def test_protein_sync_lazy_skips_upload_when_remote_path_set() -> None:
    """sync(lazy=True) with an existing id skips work entirely."""
    from deeporigin.platform.client import DeepOriginClient

    protein = Protein(
        name="prepared",
        structure=None,
        id="prot-existing",
        remote_path="entities/proteins/prepared.pdb",
    )
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None

    with patch.object(protein, "upload") as upload:
        protein.sync(lazy=True, client=client)

    upload.assert_not_called()
    assert protein.id == "prot-existing"


def test_protein_sync_skips_upload_but_registers_when_remote_path_only() -> None:
    """Non-lazy sync with remote_path set and no local file skips upload."""
    from deeporigin.platform.client import DeepOriginClient

    protein = Protein(
        name="prepared",
        structure=None,
        remote_path="entities/proteins/prepared.pdb",
    )
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.entities = MagicMock()
    client.entities.search_proteins.return_value = {"data": []}
    client.entities.create_protein.return_value = {"data": {"id": "prot-new"}}

    with patch.object(protein, "upload") as upload:
        protein.sync(lazy=False, client=client)

    upload.assert_not_called()
    client.entities.search_proteins.assert_called_once_with(
        file_path="entities/proteins/prepared.pdb",
    )
    client.entities.create_protein.assert_called_once()
    assert protein.id == "prot-new"
    assert protein.remote_path == "entities/proteins/prepared.pdb"


def test_protein_sync_links_existing_without_upload_when_remote_path_set() -> None:
    """Non-lazy sync finds an existing row by file_path without uploading."""
    from deeporigin.platform.client import DeepOriginClient

    protein = Protein(
        name="prepared",
        structure=None,
        remote_path="entities/proteins/prepared.pdb",
    )
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.entities = MagicMock()
    client.entities.search_proteins.return_value = {
        "data": [{"id": "prot-existing", "project_id": None}],
    }

    with patch.object(protein, "upload") as upload:
        protein.sync(lazy=False, client=client)

    upload.assert_not_called()
    client.entities.create_protein.assert_not_called()
    assert protein.id == "prot-existing"


def test_protein_sync_uploads_local_bytes_when_remote_path_set(
    tmp_path: Path,
) -> None:
    """sync uploads stamped local file bytes even when remote_path is already set."""
    from deeporigin.platform.client import DeepOriginClient

    cif_path = tmp_path / "protein.cif"
    cif_path.write_text(_FIXTURE_CIF.read_text())
    protein = Protein.from_file(cif_path)
    protein.mark_as_prepared()
    protein.remote_path = "entities/proteins/existing.cif"

    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.files = MagicMock()
    client.entities = MagicMock()
    client.entities.search_proteins.return_value = {
        "data": [{"id": "prot-existing", "project_id": None}],
    }

    protein.sync(lazy=False, client=client)

    client.files.upload.assert_called_once()
    uploaded_path = client.files.upload.call_args.args[0]
    kwargs = client.files.upload.call_args.kwargs
    assert Path(uploaded_path) == cif_path
    assert kwargs["remote_path"] == "entities/proteins/existing.cif"
    assert protein.id == "prot-existing"


def test_protein_upload_uses_local_bytes_not_to_file(tmp_path: Path) -> None:
    """Protein.upload sends local CIF bytes and does not serialize via to_file."""
    from deeporigin.platform.client import DeepOriginClient

    cif_path = tmp_path / "protein.cif"
    cif_path.write_text(_FIXTURE_CIF.read_text())
    protein = Protein.from_file(cif_path)
    protein.mark_as_prepared()

    client = MagicMock(spec=DeepOriginClient)
    client.files = MagicMock()

    with patch.object(protein, "to_file") as to_file:
        protein.upload(client=client)

    to_file.assert_not_called()
    client.files.upload.assert_called_once()
    assert Path(client.files.upload.call_args.args[0]) == cif_path
    assert str(protein.remote_path).endswith(".cif")
