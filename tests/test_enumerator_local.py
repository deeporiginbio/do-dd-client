"""Local mock-server tests for :class:`~deeporigin.drug_discovery.enumerator.Enumerator`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from deeporigin.drug_discovery import Enumerator, Ligand
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import (
    ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS,
    ENUMERATOR_RDKIT_DESCRIPTOR_COLUMNS,
    ENUMERATOR_RESULTS_CSV_COLUMNS,
)
from tests.conftest import check_tool_exists

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_PARENT_SMILES = "Brc1ccccc1"
_SUZUKI_SITE = {
    "reaction_id": "suzuki",
    "reactant_role": "core_halide",
    "atom_indices": [0, 1],
}


def _assert_tool_available(client: DeepOriginClient) -> None:
    """Skip-safe check that the enumerator tool is registered."""
    cfg = TOOL_KEYS_AND_VERSIONS["enumerator"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])


# -- run() end-to-end (mock server) -------------------------------------------


def test_enumerator_scaffold_run_returns_dataframe(client: DeepOriginClient) -> None:
    """SCAFFOLD run returns a descriptor-enriched DataFrame in MMP mode."""
    _assert_tool_available(client)
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(ligand=parent, job_type="SCAFFOLD", replace_ix=3, client=client)

    df = enum.run()

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    for column in ENUMERATOR_RESULTS_CSV_COLUMNS:
        assert column in df.columns
    for column in ENUMERATOR_RDKIT_DESCRIPTOR_COLUMNS:
        assert column in df.columns
    assert set(df["enumeration_mode"]) == {"MMP"}
    assert set(df["job_type"]) == {"SCAFFOLD"}
    assert enum.status == "Completed"
    assert enum.id is not None
    assert enum.cap_hit is False


def test_enumerator_analogue_run_returns_dataframe(client: DeepOriginClient) -> None:
    """ANALOGUE accepts multiple replace_ix and returns a DataFrame."""
    _assert_tool_available(client)
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(
        ligand=parent,
        job_type="ANALOGUE",
        replace_ix=[3, 4],
        client=client,
    )

    df = enum.run()

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert set(df["job_type"]) == {"ANALOGUE"}


def test_enumerator_available_reactions_returns_dataframe(
    client: DeepOriginClient,
) -> None:
    """AVAILABLE_REACTIONS returns the reaction-site DataFrame (no CSV)."""
    _assert_tool_available(client)
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(ligand=parent, job_type="AVAILABLE_REACTIONS", client=client)

    df = enum.run()

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert list(df.columns[: len(ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS)]) == list(
        ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS
    )
    assert "suzuki" in set(df["reaction_id"])
    assert enum.cap_hit is None


def test_enumerator_reaction_run_returns_dataframe(client: DeepOriginClient) -> None:
    """REACTION enumerates against explicit reaction sites and returns a DataFrame."""
    _assert_tool_available(client)
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(
        ligand=parent,
        job_type="REACTION",
        reaction_sites=[_SUZUKI_SITE],
        client=client,
    )

    df = enum.run()

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert set(df["enumeration_mode"]) == {"REACTION"}
    assert set(df["reaction_id"]) == {"suzuki"}
    assert df["building_block_id"].astype(str).str.len().gt(0).all()


# -- payload construction (no network beyond client init) ---------------------


def test_enumerator_scaffold_payload(client: DeepOriginClient) -> None:
    """SCAFFOLD payload carries replace_ix, MMP params, and top-level sync."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(
        ligand=parent,
        job_type="SCAFFOLD",
        replace_ix=3,
        radius=2,
        max_fragment_size=5,
        client=client,
    )
    payload = enum._make_payload(sync=True)

    inputs = payload["inputs"]
    assert payload["sync"] is True
    assert "sync" not in inputs
    assert inputs["ligand"] == {"smiles": _PARENT_SMILES}
    assert inputs["job_type"] == "SCAFFOLD"
    assert inputs["replace_ix"] == [3]
    assert inputs["radius"] == 2
    assert inputs["max_fragment_size"] == 5
    assert "reaction_sites" not in inputs


def test_enumerator_reaction_payload(client: DeepOriginClient) -> None:
    """REACTION payload carries cleaned reaction_sites and no MMP params."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(
        ligand=parent,
        job_type="REACTION",
        reaction_sites=[{**_SUZUKI_SITE, "extra": "ignored"}],
        client=client,
    )
    inputs = enum._make_payload(sync=True)["inputs"]

    assert inputs["reaction_sites"] == [_SUZUKI_SITE]
    assert "replace_ix" not in inputs
    assert "radius" not in inputs


def test_enumerator_available_reactions_payload(client: DeepOriginClient) -> None:
    """AVAILABLE_REACTIONS payload carries only the ligand and job_type."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(ligand=parent, job_type="AVAILABLE_REACTIONS", client=client)
    inputs = enum._make_payload(sync=True)["inputs"]

    assert set(inputs) == {"ligand", "job_type"}


def test_enumerator_payload_includes_ligand_id(client: DeepOriginClient) -> None:
    """A ligand id is echoed into the payload ligand block."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    parent.id = "lig-123"
    enum = Enumerator(ligand=parent, job_type="SCAFFOLD", replace_ix=0, client=client)
    inputs = enum._make_payload(sync=True)["inputs"]

    assert inputs["ligand"] == {"smiles": _PARENT_SMILES, "id": "lig-123"}


# -- validation ----------------------------------------------------------------


def test_enumerator_rejects_unknown_job_type(client: DeepOriginClient) -> None:
    """An unknown job_type raises ValueError."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="Unknown job_type"):
        Enumerator(ligand=parent, job_type="MUTATE", replace_ix=0, client=client)


def test_enumerator_scaffold_requires_single_replace_ix(
    client: DeepOriginClient,
) -> None:
    """SCAFFOLD requires exactly one replace_ix."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="exactly one replace_ix"):
        Enumerator(ligand=parent, job_type="SCAFFOLD", replace_ix=[0, 1], client=client)


def test_enumerator_scaffold_requires_replace_ix(client: DeepOriginClient) -> None:
    """SCAFFOLD without replace_ix raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="requires replace_ix"):
        Enumerator(ligand=parent, job_type="SCAFFOLD", client=client)


def test_enumerator_analogue_requires_replace_ix(client: DeepOriginClient) -> None:
    """ANALOGUE without replace_ix raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="requires replace_ix"):
        Enumerator(ligand=parent, job_type="ANALOGUE", client=client)


def test_enumerator_reaction_requires_sites(client: DeepOriginClient) -> None:
    """REACTION without reaction_sites raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="non-empty reaction_sites"):
        Enumerator(ligand=parent, job_type="REACTION", client=client)


def test_enumerator_reaction_rejects_replace_ix(client: DeepOriginClient) -> None:
    """REACTION with replace_ix raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="replace_ix is not allowed"):
        Enumerator(
            ligand=parent,
            job_type="REACTION",
            reaction_sites=[_SUZUKI_SITE],
            replace_ix=0,
            client=client,
        )


def test_enumerator_available_reactions_rejects_extra_inputs(
    client: DeepOriginClient,
) -> None:
    """AVAILABLE_REACTIONS with replace_ix raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="AVAILABLE_REACTIONS takes only a ligand"):
        Enumerator(
            ligand=parent,
            job_type="AVAILABLE_REACTIONS",
            replace_ix=0,
            client=client,
        )


def test_enumerator_rejects_radius_out_of_range(client: DeepOriginClient) -> None:
    """radius above the allowed maximum raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="radius must be between"):
        Enumerator(
            ligand=parent,
            job_type="SCAFFOLD",
            replace_ix=0,
            radius=6,
            client=client,
        )


def test_enumerator_rejects_max_fragment_size_out_of_range(
    client: DeepOriginClient,
) -> None:
    """max_fragment_size above the allowed maximum raises."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    with pytest.raises(ValueError, match="max_fragment_size must be between"):
        Enumerator(
            ligand=parent,
            job_type="SCAFFOLD",
            replace_ix=0,
            max_fragment_size=16,
            client=client,
        )


def test_enumerator_ignores_mmp_bounds_for_non_mmp_modes(
    client: DeepOriginClient,
) -> None:
    """radius / max_fragment_size bounds are not enforced outside MMP modes."""
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(
        ligand=parent,
        job_type="AVAILABLE_REACTIONS",
        radius=99,
        max_fragment_size=99,
        client=client,
    )

    assert enum.job_type == "AVAILABLE_REACTIONS"


# -- rehydration ---------------------------------------------------------------


def test_enumerator_from_dto_rehydrates_inputs(client: DeepOriginClient) -> None:
    """from_dto restores ligand SMILES and mode-specific inputs."""
    _assert_tool_available(client)
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(ligand=parent, job_type="SCAFFOLD", replace_ix=3, client=client)
    enum.run()

    restored = Enumerator.from_dto(enum.dto, client=client)

    assert restored.job_type == "SCAFFOLD"
    assert restored.ligand.smiles == _PARENT_SMILES
    assert restored.replace_ix == [3]


def test_enumerator_from_dto_rejects_missing_job_type(
    client: DeepOriginClient,
) -> None:
    """from_dto fails fast when the stored inputs carry no usable job_type."""
    _assert_tool_available(client)
    parent = Ligand.from_smiles(_PARENT_SMILES)
    enum = Enumerator(ligand=parent, job_type="SCAFFOLD", replace_ix=3, client=client)
    enum.run()

    dto = dict(enum.dto)
    inputs = dict(dto.get("userInputs") or dto.get("inputs") or {})
    inputs.pop("job_type", None)
    dto["userInputs"] = inputs
    dto["inputs"] = inputs

    with pytest.raises(ValueError, match="unknown job_type"):
        Enumerator.from_dto(dto, client=client)
