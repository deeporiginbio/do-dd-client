"""Enumerator -- generate analogue libraries from a parent ligand (served, sync-only).

Backed by the served platform tool ``deeporigin.enumerator`` (a ``direct``
execution). One :class:`Enumerator` is configured with a single ``job_type`` and
executed with a blocking :meth:`run`, which returns a :class:`pandas.DataFrame`.

The tool exposes four ``job_type`` values:

- ``SCAFFOLD`` -- CReM matched-molecular-pair (MMP) enumeration that grows a
  fragment at a single attachment atom (one ``replace_ix`` index).
- ``ANALOGUE`` -- CReM MMP enumeration that swaps a connected fragment (one or
  more ``replace_ix`` indices forming a connected substructure).
- ``AVAILABLE_REACTIONS`` -- discovers named-reaction sites on the parent and
  returns their atom indices. Writes no CSV; the DataFrame is built from the
  inline result list.
- ``REACTION`` -- enumerates products against the Enamine fragment library at
  explicit ``reaction_sites``. Each site must match a hit returned by a prior
  ``AVAILABLE_REACTIONS`` run.

``SCAFFOLD`` and ``ANALOGUE`` are the two MMP flavors.

Usage::

    from deeporigin.drug_discovery import Enumerator, Ligand

    parent = Ligand.from_smiles("Brc1ccccc1")

    # MMP: grow a fragment at atom 0
    df = Enumerator(ligand=parent, job_type="SCAFFOLD", replace_ix=0).run()

    # Discover reaction sites, then enumerate against them
    sites = Enumerator(ligand=parent, job_type="AVAILABLE_REACTIONS").run()
    df = Enumerator(
        ligand=parent,
        job_type="REACTION",
        reaction_sites=[
            {"reaction_id": "suzuki", "reactant_role": "core_halide", "atom_indices": [0, 1]},
        ],
    ).run()
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import (
    ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS,
    ENUMERATOR_JOB_TYPES,
    ENUMERATOR_MAX_FRAGMENT_SIZE_MAX,
    ENUMERATOR_MAX_FRAGMENT_SIZE_MIN,
    ENUMERATOR_MAX_REACTION_SITES,
    ENUMERATOR_MMP_JOB_TYPES,
    ENUMERATOR_RADIUS_MAX,
    ENUMERATOR_RADIUS_MIN,
)

_DEFAULT_MAX_FRAGMENT_SIZE = 10


def _normalize_replace_ix(replace_ix: int | list[int] | None) -> list[int] | None:
    """Normalize ``replace_ix`` to a list of atom indices (or ``None``).

    Args:
        replace_ix: A single atom index, a list of atom indices, or ``None``.

    Returns:
        A list of atom indices, or ``None`` when ``replace_ix`` is ``None``.
    """
    if replace_ix is None:
        return None
    if isinstance(replace_ix, int):
        return [replace_ix]
    return list(replace_ix)


class Enumerator(Execution, SyncExecutableMixin):
    """Enumerate analogues of a parent ligand via the served enumerator tool.

    Configure the instance with a parent :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`,
    a ``job_type``, and its mode-specific parameters, then call :meth:`run` to
    execute synchronously and receive a :class:`pandas.DataFrame`.

    For ``SCAFFOLD`` / ``ANALOGUE`` / ``REACTION`` the DataFrame is parsed from
    the tool's descriptor-enriched ``results.csv``. For ``AVAILABLE_REACTIONS``
    the DataFrame is built from the inline ``available_reactions`` list (no CSV
    is written).

    Attributes:
        ligand: Parent ligand whose ``smiles`` (and optional ``id``) is enumerated.
        job_type: One of ``SCAFFOLD``, ``ANALOGUE``, ``AVAILABLE_REACTIONS``, ``REACTION``.
        replace_ix: RDKit atom indices marking the MMP enumeration site (MMP modes).
        reaction_sites: Named-reaction sites for REACTION enumeration.
        radius: CReM environment radius (MMP modes).
        max_fragment_size: Maximum heavy atoms in the added/replacement fragment (MMP modes).
        cap_hit: Whether the last run hit the platform enumeration cap (MMP/REACTION),
            or ``None`` before a run or for ``AVAILABLE_REACTIONS``.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["enumerator"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        ligand: Ligand,
        job_type: str,
        replace_ix: int | list[int] | None = None,
        reaction_sites: list[dict[str, Any]] | None = None,
        radius: int = ENUMERATOR_RADIUS_MIN,
        max_fragment_size: int = _DEFAULT_MAX_FRAGMENT_SIZE,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["enumerator"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure an enumerator run for a single parent ligand.

        Args:
            ligand: Parent ligand. Its ``smiles`` is sent inline; its ``id`` (when
                set) is echoed back as ``parent_ligand_id`` in the results.
            job_type: Enumeration mode; one of :data:`~deeporigin.utils.constants.ENUMERATOR_JOB_TYPES`.
            replace_ix: RDKit atom index (or indices) marking the enumeration site.
                Required for ``SCAFFOLD`` (exactly one) and ``ANALOGUE`` (one or more,
                forming a connected substructure). Not used for the reaction modes.
            reaction_sites: List of ``{reaction_id, reactant_role, atom_indices}``
                dicts. Required for ``REACTION``; take these verbatim from an
                ``AVAILABLE_REACTIONS`` run. Not used for the MMP modes.
            radius: CReM environment radius for MMP modes (1-5). Defaults to 1.
            max_fragment_size: Maximum heavy atoms in the added/replacement fragment
                for MMP modes (1-15). Defaults to 10.
            tool_version: Platform tool version to run. Settable so callers can pin
                or upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If ``job_type`` is unknown, required mode inputs are missing
                or malformed, or numeric bounds are exceeded.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._ligand = ligand
        self._job_type = job_type
        self._replace_ix = _normalize_replace_ix(replace_ix)
        self._reaction_sites = reaction_sites
        self._radius = radius
        self._max_fragment_size = max_fragment_size
        self._cap_hit: bool | None = None
        self._validate()

    def _validate(self) -> None:
        """Validate the configured inputs for the selected ``job_type``.

        Raises:
            ValueError: If any input is invalid for the selected mode.
        """
        if self._job_type not in ENUMERATOR_JOB_TYPES:
            raise ValueError(
                f"Unknown job_type {self._job_type!r}. "
                f"Allowed: {sorted(ENUMERATOR_JOB_TYPES)}"
            )
        if not self._ligand.smiles:
            raise ValueError("Enumerator requires a ligand with a SMILES string.")
        if not (ENUMERATOR_RADIUS_MIN <= self._radius <= ENUMERATOR_RADIUS_MAX):
            raise ValueError(
                f"radius must be between {ENUMERATOR_RADIUS_MIN} and "
                f"{ENUMERATOR_RADIUS_MAX}, got {self._radius}."
            )
        if not (
            ENUMERATOR_MAX_FRAGMENT_SIZE_MIN
            <= self._max_fragment_size
            <= ENUMERATOR_MAX_FRAGMENT_SIZE_MAX
        ):
            raise ValueError(
                f"max_fragment_size must be between {ENUMERATOR_MAX_FRAGMENT_SIZE_MIN} "
                f"and {ENUMERATOR_MAX_FRAGMENT_SIZE_MAX}, got {self._max_fragment_size}."
            )

        if self._job_type in ENUMERATOR_MMP_JOB_TYPES:
            self._validate_mmp()
        elif self._job_type == "REACTION":
            self._validate_reaction()
        else:  # AVAILABLE_REACTIONS
            if self._replace_ix is not None or self._reaction_sites is not None:
                raise ValueError(
                    "AVAILABLE_REACTIONS takes only a ligand; "
                    "replace_ix and reaction_sites are not allowed."
                )

    def _validate_mmp(self) -> None:
        """Validate ``replace_ix`` for the MMP modes (SCAFFOLD / ANALOGUE)."""
        if self._reaction_sites is not None:
            raise ValueError(
                f"reaction_sites is not allowed for job_type {self._job_type!r}."
            )
        if not self._replace_ix:
            raise ValueError(
                f"job_type {self._job_type!r} requires replace_ix (atom indices)."
            )
        if any(ix < 0 for ix in self._replace_ix):
            raise ValueError("replace_ix values must be non-negative atom indices.")
        if self._job_type == "SCAFFOLD" and len(self._replace_ix) != 1:
            raise ValueError(
                "SCAFFOLD requires exactly one replace_ix (the attachment atom)."
            )

    def _validate_reaction(self) -> None:
        """Validate ``reaction_sites`` for the REACTION mode."""
        if self._replace_ix is not None:
            raise ValueError("replace_ix is not allowed for job_type 'REACTION'.")
        if not self._reaction_sites:
            raise ValueError("REACTION requires a non-empty reaction_sites list.")
        if len(self._reaction_sites) > ENUMERATOR_MAX_REACTION_SITES:
            raise ValueError(
                f"reaction_sites accepts at most {ENUMERATOR_MAX_REACTION_SITES} "
                f"entries, got {len(self._reaction_sites)}."
            )
        for site in self._reaction_sites:
            reaction_id = site.get("reaction_id")
            reactant_role = site.get("reactant_role")
            atom_indices = site.get("atom_indices")
            if not isinstance(reaction_id, str) or not reaction_id:
                raise ValueError("Each reaction site needs a non-empty reaction_id.")
            if not isinstance(reactant_role, str) or not reactant_role:
                raise ValueError("Each reaction site needs a non-empty reactant_role.")
            if (
                not isinstance(atom_indices, list)
                or not atom_indices
                or not all(isinstance(i, int) for i in atom_indices)
            ):
                raise ValueError(
                    "Each reaction site needs a non-empty atom_indices list of ints."
                )

    @property
    def ligand(self) -> Ligand:
        """Parent ligand targeted by this enumeration (read-only)."""
        return self._ligand

    @property
    def job_type(self) -> str:
        """Enumeration mode for this run (read-only)."""
        return self._job_type

    @property
    def replace_ix(self) -> list[int] | None:
        """RDKit atom indices marking the MMP enumeration site, if any (read-only)."""
        return list(self._replace_ix) if self._replace_ix is not None else None

    @property
    def reaction_sites(self) -> list[dict[str, Any]] | None:
        """Named-reaction sites for REACTION enumeration, if any (read-only)."""
        return self._reaction_sites

    @property
    def radius(self) -> int:
        """CReM environment radius used for MMP modes (read-only)."""
        return self._radius

    @property
    def max_fragment_size(self) -> int:
        """Maximum heavy atoms in the added/replacement fragment (MMP modes, read-only)."""
        return self._max_fragment_size

    @property
    def cap_hit(self) -> bool | None:
        """Whether the last MMP/REACTION run hit the platform enumeration cap.

        ``None`` before :meth:`run`, or for ``AVAILABLE_REACTIONS`` (which has no cap).
        """
        return self._cap_hit

    def __repr__(self) -> str:
        """Return a concise summary of this Enumerator."""
        parts = [f"Enumerator job_type={self._job_type!r}"]
        if self._ligand.id is not None:
            parts.append(f"ligand_id={self._ligand.id!r}")
        if self.id:
            parts.append(f"id={self.id!r}")
        status = getattr(self, "status", None)
        if status:
            parts.append(f"status={status!r}")
        return f"<{' '.join(parts)}>"

    def _make_payload(
        self,
        *,
        approve_amount: int | None = None,
        sync: bool = True,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        The enumerator input schema forbids unknown properties, so ``sync`` is
        sent as a top-level body field (like molprops / system-prep) rather than
        inside ``inputs``.

        Args:
            approve_amount: Spend cap forwarded as ``approveAmount`` when set.
            sync: ``True`` for blocking (direct) execution.

        Returns:
            Payload dict for ``executions.create``.
        """
        ligand_input: dict[str, Any] = {"smiles": self._ligand.smiles}
        if self._ligand.id is not None:
            ligand_input["id"] = self._ligand.id

        inputs: dict[str, Any] = {
            "ligand": ligand_input,
            "job_type": self._job_type,
        }
        if self._job_type in ENUMERATOR_MMP_JOB_TYPES:
            inputs["replace_ix"] = list(self._replace_ix or [])
            inputs["radius"] = self._radius
            inputs["max_fragment_size"] = self._max_fragment_size
        elif self._job_type == "REACTION":
            inputs["reaction_sites"] = [
                {
                    "reaction_id": site["reaction_id"],
                    "reactant_role": site["reactant_role"],
                    "atom_indices": list(site["atom_indices"]),
                }
                for site in (self._reaction_sites or [])
            ]

        payload: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    @beartype
    def run(self) -> pd.DataFrame:
        """Execute the enumeration synchronously (blocking) and return a DataFrame.

        Submits one synchronous execution (``sync=True``), applies the response
        via :meth:`~deeporigin.drug_discovery.execution.Execution.update_from_dto`,
        and returns results via :meth:`get_results`.

        Returns:
            A :class:`pandas.DataFrame`. For ``SCAFFOLD`` / ``ANALOGUE`` /
            ``REACTION`` it is the descriptor-enriched ``results.csv``; for
            ``AVAILABLE_REACTIONS`` it has columns
            :data:`~deeporigin.utils.constants.ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS`.

        Raises:
            DeepOriginException: If the execution did not complete successfully or
                no results could be parsed.
        """
        dto = self._create_execution(data=self._make_payload(sync=True))
        self.update_from_dto(dto)

        if not is_success_status(self.status):
            raise DeepOriginException(
                title="Enumeration did not complete",
                message=(
                    f"Enumerator execution ended in {self.status!r} state "
                    f"(execution id {self.id!r})."
                ),
            )

        return self.get_results(dto)

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this execution's results as a :class:`pandas.DataFrame`.

        Reads ``jobOutputs`` from ``dto`` (or fetches it via
        ``client.executions.get`` when omitted, e.g. after
        :meth:`~deeporigin.drug_discovery.execution.Execution.from_id`).

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get``. Passing it avoids an extra GET.

        Returns:
            A DataFrame of enumeration products (MMP / REACTION) or discovered
            reaction sites (AVAILABLE_REACTIONS).

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If no results could be parsed.
        """
        exec_id = self._ensure_id()
        if dto is None:
            dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        job_outputs = dto.get("jobOutputs") if isinstance(dto, dict) else None
        if not isinstance(job_outputs, dict):
            job_outputs = {}

        if self._job_type == "AVAILABLE_REACTIONS":
            return self._available_reactions_dataframe(job_outputs)
        return self._enumeration_results_dataframe(job_outputs)

    @staticmethod
    def _available_reactions_dataframe(job_outputs: dict[str, Any]) -> pd.DataFrame:
        """Build a DataFrame of discovered reaction sites from ``jobOutputs``."""
        rows = [
            row
            for row in (job_outputs.get("available_reactions") or [])
            if isinstance(row, dict)
        ]
        columns = list(ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS)
        if not rows:
            return pd.DataFrame({column: [] for column in columns})
        df = pd.DataFrame(rows)
        ordered = [c for c in columns if c in df.columns]
        extra = [c for c in df.columns if c not in ordered]
        return df[ordered + extra]

    def _enumeration_results_dataframe(
        self, job_outputs: dict[str, Any]
    ) -> pd.DataFrame:
        """Download and parse the enumerator ``results.csv`` into a DataFrame."""
        results = [
            row
            for row in (job_outputs.get("enumeration_results") or [])
            if isinstance(row, dict)
        ]
        if not results:
            raise DeepOriginException(
                title="No enumeration results",
                message="The execution returned no enumeration_results.",
            )
        first = results[0]
        csv_path = first.get("csv_file_path")
        if not csv_path:
            raise DeepOriginException(
                title="No results CSV",
                message="enumeration_results is missing csv_file_path.",
            )
        self._cap_hit = bool(first.get("cap_hit", False))

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "results.csv")
            self.client.files.download(
                remote_path=csv_path,
                local_path=local_path,
            )
            return pd.read_csv(local_path)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ``Enumerator`` from a tools execution DTO.

        Rehydrates the parent ligand and mode-specific inputs from ``userInputs``
        (falling back to ``inputs`` for older payloads).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            An ``Enumerator`` with ``id``, pricing fields, and domain inputs set.

        Raises:
            ValueError: If the stored inputs are missing a ligand SMILES.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}

        ligand_in = inputs.get("ligand") or {}
        smiles = ligand_in.get("smiles")
        if not smiles:
            raise ValueError(
                "Cannot rehydrate Enumerator: stored inputs have no ligand SMILES."
            )
        ligand = Ligand.from_smiles(str(smiles))
        if ligand_in.get("id") is not None:
            ligand.id = str(ligand_in["id"])

        instance._ligand = ligand
        instance._job_type = str(inputs.get("job_type") or "")
        instance._replace_ix = _normalize_replace_ix(inputs.get("replace_ix"))
        instance._reaction_sites = inputs.get("reaction_sites")
        instance._radius = int(inputs.get("radius", ENUMERATOR_RADIUS_MIN))
        instance._max_fragment_size = int(
            inputs.get("max_fragment_size", _DEFAULT_MAX_FRAGMENT_SIZE)
        )
        instance._cap_hit = None
        return instance
