"""ProteinPrep -- async-only execution for expert protein preparation.

Usage::

    prep = ProteinPrep(protein, pdb_id="1EBY")  # pdb_id inferred if protein.pdb_id is set
    prep.start()
    prep.wait()
    prepared = prep.get_results()  # in-memory Protein; id is None
"""

from __future__ import annotations

import re
from typing import Any, Self

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import (
    PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
    PROTEIN_PREP_PDB_ID_PATTERN,
)

_PDB_ID_RE = re.compile(PROTEIN_PREP_PDB_ID_PATTERN)
_RESULT_TYPE_PREPARED_PROTEIN = "preparedprotein"


def _copy_str_list(values: list[str] | None) -> list[str]:
    """Return a shallow copy of *values*, or an empty list when ``None``."""
    return list(values) if values is not None else []


def _resolve_pdb_id(*, protein: Protein, pdb_id: str | None) -> str:
    """Return a 4-character PDB ID from *pdb_id* or ``protein.pdb_id``.

    Args:
        protein: Input protein that may already carry ``pdb_id``.
        pdb_id: Explicit override; used when set.

    Returns:
        Stripped 4-character alphanumeric PDB identifier.

    Raises:
        ValueError: If neither source is set, or the value does not match
            :data:`~deeporigin.utils.constants.PROTEIN_PREP_PDB_ID_PATTERN`.
    """
    raw = pdb_id if pdb_id is not None else protein.pdb_id
    if raw is None or not str(raw).strip():
        raise ValueError(
            "pdb_id is required when protein.pdb_id is not set. "
            "Pass pdb_id= as a 4-character PDB identifier for loop modelling."
        )
    resolved = str(raw).strip()
    if _PDB_ID_RE.fullmatch(resolved) is None:
        raise ValueError(
            "pdb_id must be a 4-character alphanumeric PDB identifier, "
            f"got {resolved!r}."
        )
    return resolved


def _protein_from_prepared_data(
    data: dict[str, Any],
    *,
    fallback_pdb_id: str | None,
    fallback_name: str | None,
) -> Protein:
    """Build an in-memory Protein from a prepared-protein output dict.

    Args:
        data: ``jobOutputs.protein`` or result-explorer ``data`` payload.
        fallback_pdb_id: PDB ID used when the payload omits ``pdb_id``.
        fallback_name: Input protein name used to label the result.

    Returns:
        Protein with ``id`` unset and ``remote_path`` set to the prepared PDB.

    Raises:
        ValueError: If ``protein_pdb_file_path`` is missing or empty.
    """
    path = data.get("protein_pdb_file_path")
    if not path or not str(path).strip():
        raise ValueError(PROTEIN_PREP_NO_OUTPUT_PATHS_MSG)
    pdb_id = data.get("pdb_id") or fallback_pdb_id
    base_name = fallback_name.strip() if isinstance(fallback_name, str) else ""
    name = f"{base_name} (prepared)" if base_name else "prepared protein"
    return Protein(
        name=name,
        pdb_id=str(pdb_id) if pdb_id else None,
        structure=None,
        remote_path=str(path),
    )


class ProteinPrep(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """Prepare a protein structure via ``deeporigin.protein-prep`` (async-only).

    Submit with :meth:`start`, track with :meth:`wait` / :meth:`watch` /
    :meth:`sync`, then load an in-memory :class:`Protein` from
    :meth:`get_results`. There is no ``run()``. Quoting is unused (billing is
    skipped); do not pass ``quote=True``.

    Attributes:
        protein: Input protein structure (unchanged after the run).
        pdb_id: 4-character PDB ID used for loop-modelling templates.
        keep_chain_ids: Chain IDs to keep; empty means all chains.
        keep_cofactor_ids: Cofactor/metal residue names to keep; empty keeps none.
        keep_water_residue_names: Water residue-name classes to keep; empty keeps none.
        remove_ligand_ids: Ligand residue names to remove during cleanup.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        pdb_id: str | None = None,
        keep_chain_ids: list[str] | None = None,
        keep_cofactor_ids: list[str] | None = None,
        keep_water_residue_names: list[str] | None = None,
        remove_ligand_ids: list[str] | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a ProteinPrep for the given protein.

        Args:
            protein: Protein structure to prepare.
            pdb_id: 4-character PDB ID for loop modelling. Inferred from
                ``protein.pdb_id`` when omitted.
            keep_chain_ids: Chain IDs to keep. Empty (default) keeps all chains.
            keep_cofactor_ids: Cofactor/metal residue names to keep. Empty
                (default) keeps none.
            keep_water_residue_names: Water residue-name classes to keep.
                Empty (default) keeps none.
            remove_ligand_ids: Ligand residue names to remove. Empty (default)
                removes none beyond the tool's cleanup defaults.
            tool_version: Platform tool version pin.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If ``pdb_id`` cannot be resolved or is not 4 alphanumeric
                characters.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._protein = protein
        self._pdb_id = _resolve_pdb_id(protein=protein, pdb_id=pdb_id)
        self._keep_chain_ids = _copy_str_list(keep_chain_ids)
        self._keep_cofactor_ids = _copy_str_list(keep_cofactor_ids)
        self._keep_water_residue_names = _copy_str_list(keep_water_residue_names)
        self._remove_ligand_ids = _copy_str_list(remove_ligand_ids)

    @property
    def protein(self) -> Protein:
        """Input protein structure used for preparation."""
        return self._protein

    @property
    def pdb_id(self) -> str:
        """4-character PDB ID used for loop-modelling templates."""
        return self._pdb_id

    @property
    def keep_chain_ids(self) -> list[str]:
        """Protein chain IDs to keep; empty means all chains."""
        return self._keep_chain_ids

    @property
    def keep_cofactor_ids(self) -> list[str]:
        """Cofactor/metal residue names to keep; empty keeps none."""
        return self._keep_cofactor_ids

    @property
    def keep_water_residue_names(self) -> list[str]:
        """Water residue-name classes to keep; empty keeps none."""
        return self._keep_water_residue_names

    @property
    def remove_ligand_ids(self) -> list[str]:
        """Ligand residue names to remove during cleanup."""
        return self._remove_ligand_ids

    def __repr__(self) -> str:
        """Return a concise summary of this ProteinPrep."""
        parts = [f"ProteinPrep protein={self.protein.id!r} pdb_id={self.pdb_id!r}"]
        if self.id:
            parts.append(f"id={self.id!r}")
        return f"<{' '.join(parts)}>"

    def _ensure_protein_remote(self) -> None:
        """Upload/sync the protein and ensure ``remote_path`` is set."""
        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        ``sync`` is unused: Protein Prep has no ``sync`` input and always runs
        as an async workflow.

        Args:
            approve_amount: Spend cap; omitted from the body when ``None``.
            sync: Ignored (kept for the Execution payload contract).

        Returns:
            Payload for ``client.executions.create``.
        """
        protein = self._protein
        payload: dict[str, Any] = {
            "inputs": {
                "protein": {
                    "id": protein.id,
                    "file_path": protein.remote_path,
                },
                "pdb_id": self._pdb_id,
                "keep_chain_ids": list(self._keep_chain_ids),
                "keep_cofactor_ids": list(self._keep_cofactor_ids),
                "keep_water_residue_names": list(self._keep_water_residue_names),
                "remove_ligand_ids": list(self._remove_ligand_ids),
            },
            "outputs": {},
            "metadata": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit protein prep as a persisted async execution.

        Args:
            approve_amount: Spend cap forwarded to the platform. ``None`` omits
                the field (the tool has no quote).
            **kwargs: Unused; accepted for mixin compatibility.
        """
        _ = kwargs
        self._ensure_protein_remote()
        execution_dto = self._create_execution(
            data=self._make_payload(approve_amount=approve_amount, sync=False),
        )
        if execution_dto.get("executionId") is None:
            raise ValueError("Execution response must contain 'executionId'") from None
        self.update_from_dto(execution_dto)

    @staticmethod
    def _parse_inputs_dict(
        inputs: dict[str, Any],
    ) -> tuple[dict[str, Any], str, list[str], list[str], list[str], list[str]]:
        """Parse stored userInputs into protein dict, pdb_id, and keep/remove lists.

        Args:
            inputs: Execution ``userInputs`` (or ``inputs``) dict.

        Returns:
            ``protein`` input dict, resolved ``pdb_id``, and the four keep/remove
            lists.

        Raises:
            ValueError: If ``pdb_id`` is missing or invalid, or ``protein`` is
                not an object.
        """
        protein_input = inputs.get("protein") or {}
        if not isinstance(protein_input, dict):
            raise ValueError("Missing 'protein' object in execution userInputs.")
        raw_pdb_id = inputs.get("pdb_id")
        if raw_pdb_id is None or not str(raw_pdb_id).strip():
            raise ValueError("Missing 'pdb_id' in execution userInputs.")
        pdb_id = str(raw_pdb_id).strip()
        if _PDB_ID_RE.fullmatch(pdb_id) is None:
            raise ValueError(
                "pdb_id from execution inputs must be a 4-character "
                f"alphanumeric PDB identifier, got {pdb_id!r}."
            )

        def _list_field(name: str) -> list[str]:
            raw = inputs.get(name) or []
            if not isinstance(raw, list):
                raise ValueError(f"Invalid {name} in execution inputs.")
            return [str(item) for item in raw]

        return (
            protein_input,
            pdb_id,
            _list_field("keep_chain_ids"),
            _list_field("keep_cofactor_ids"),
            _list_field("keep_water_residue_names"),
            _list_field("remove_ligand_ids"),
        )

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``ProteinPrep`` from a tools execution DTO.

        Rehydrates ``protein``, ``pdb_id``, and keep/remove lists from
        ``userInputs`` (falling back to ``inputs``).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``ProteinPrep`` with ``id``, lifecycle fields, and domain inputs set.

        Raises:
            ValueError: If ``pdb_id`` is missing from stored inputs.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        (
            protein_input,
            pdb_id,
            keep_chain_ids,
            keep_cofactor_ids,
            keep_water_residue_names,
            remove_ligand_ids,
        ) = cls._parse_inputs_dict(inputs)

        protein_id = protein_input.get("id")
        file_path = protein_input.get("file_path")
        if protein_id is not None:
            instance._protein = Protein.from_id(
                str(protein_id),
                client=client,
                download=False,
                remote_path_override=file_path,
            )
        else:
            instance._protein = Protein(
                name=str(pdb_id),
                pdb_id=pdb_id,
                structure=None,
                remote_path=file_path,
            )
        instance._pdb_id = pdb_id
        instance._keep_chain_ids = keep_chain_ids
        instance._keep_cofactor_ids = keep_cofactor_ids
        instance._keep_water_residue_names = keep_water_residue_names
        instance._remove_ligand_ids = remove_ligand_ids
        return instance

    def _protein_from_outputs(self, data: dict[str, Any]) -> Protein:
        """Build the in-memory result Protein from an output dict.

        Args:
            data: Prepared-protein payload (``jobOutputs.protein`` or explorer
                ``data``).

        Returns:
            In-memory Protein wrapping the prepared PDB path.
        """
        return _protein_from_prepared_data(
            data,
            fallback_pdb_id=self._pdb_id,
            fallback_name=self._protein.name,
        )

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> Protein:
        """Load the prepared protein as an in-memory :class:`Protein`.

        Tries result-explorer rows for this execution
        (``result_type=preparedprotein``), then ``jobOutputs.protein``. Does not
        PATCH or create a proteins-table record; the returned Protein has
        ``id is None`` and ``remote_path`` set to the prepared PDB.

        Args:
            dto: Optional execution payload. Passing it avoids an extra GET
                when the result-explorer path fails but ``jobOutputs`` is
                already in hand.

        Returns:
            An in-memory :class:`Protein` for the prepared structure.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If no prepared PDB path could be loaded.
        """
        exec_id = self._ensure_id()

        try:
            response = self.client.results.get(
                result_type=_RESULT_TYPE_PREPARED_PROTEIN,
                compute_job_id=exec_id,
                limit=1,
            )
            records = response.get("data") or []
            if records:
                data = records[0].get("data") or {}
                if isinstance(data, dict) and data.get("protein_pdb_file_path"):
                    return self._protein_from_outputs(data)
        except Exception:
            pass

        try:
            exec_dto = dto
            if exec_dto is None:
                exec_dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            jo = exec_dto.get("jobOutputs") if isinstance(exec_dto, dict) else None
            protein_out = jo.get("protein") if isinstance(jo, dict) else None
            if isinstance(protein_out, dict):
                return self._protein_from_outputs(protein_out)
        except ValueError:
            pass

        raise DeepOriginException(
            title="Could not load prepared protein",
            message=PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
        )
