"""PocketFinder -- sync-only execution for detecting protein binding pockets.

Usage::

    pf = PocketFinder(protein)
    pf.quote()          # populates pf.estimate
    pockets = pf.run()  # blocking; populates pf.cost
"""

from __future__ import annotations

from typing import Any, Self

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


class PocketFinder(Execution, QuoteMixin, SyncExecutableMixin):
    """Find binding pockets in a protein structure (sync-only).

    Uses ``client.executions.create`` with ``sync=True`` for :meth:`run` and
    ``sync=False`` with ``approveAmount=0`` for :meth:`quote`. The platform
    returns an execution id (``id``) you can use with :meth:`get_results` and
    result-explorer APIs.

    Attributes:
        protein: The protein to analyse.
        pocket_count: Maximum number of pockets to detect.
        pocket_min_size: Minimum pocket volume in cubic Angstroms.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"]

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        pocket_count: int = 1,
        pocket_min_size: int = 30,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a PocketFinder for the given protein.

        Args:
            protein: Protein structure to search for pockets.
            pocket_count: Maximum number of pockets to detect. Defaults to 1.
            pocket_min_size: Minimum pocket size in cubic Angstroms. Defaults to 30.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._protein = protein
        self._pocket_count = pocket_count
        self._pocket_min_size = pocket_min_size

    @property
    def protein(self) -> Protein:
        """The protein to analyse."""
        return self._protein

    @property
    def pocket_count(self) -> int:
        """Maximum number of pockets to detect."""
        return self._pocket_count

    @property
    def pocket_min_size(self) -> int:
        """Minimum pocket volume in cubic Angstroms."""
        return self._pocket_min_size

    def __repr__(self) -> str:
        """Return a concise summary of the PocketFinder."""
        parts = [f"PocketFinder protein={self.protein.id!r}"]
        if self.id:
            parts.append(f"id={self.id!r}")
        parts.append(f"pocket_count={self.pocket_count}")
        parts.append(f"pocket_min_size={self.pocket_min_size}")
        return f"<{' '.join(parts)}>"

    def _validate_pocket_params(self) -> None:
        """Raise if ``pocket_count`` or ``pocket_min_size`` are invalid."""
        if self._pocket_count < 1:
            raise ValueError("pocket_count must be at least 1") from None
        if self._pocket_min_size < 1:
            raise ValueError("pocket_min_size must be at least 1") from None

    def _ensure_protein_remote(self) -> None:
        """Upload/sync protein and ensure ``remote_path`` is set for the API."""
        self._validate_pocket_params()
        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

    def _tool_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` for pocket finder."""
        return {
            "protein": {
                "file_path": self._protein.remote_path,
                "id": self._protein.id,
            },
            "pocket_count": self._pocket_count,
            "pocket_min_size": self._pocket_min_size,
        }

    def _make_payload(
        self,
        *,
        sync: bool = True,
        approve_amount: int | None = None,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._tool_inputs(),
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def _get_quote(self) -> dict[str, Any]:
        """Return the tools API execution DTO for a quotation (``approveAmount=0``)."""
        self._ensure_protein_remote()
        return self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(sync=False, approve_amount=0),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

    @staticmethod
    def _parse_inputs_dict(inputs: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        """Return ``protein`` input dict, ``pocket_count``, and ``pocket_min_size``."""
        protein_input = inputs.get("protein") or {}
        protein_id = protein_input.get("id")
        if protein_id is None:
            raise ValueError(
                "Missing 'protein.id' in execution userInputs; "
                "this execution may have been created with an older input schema."
            )
        raw_count = inputs.get("pocket_count")
        raw_min_size = inputs.get("pocket_min_size")
        try:
            pocket_count = int(raw_count) if raw_count is not None else 1
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_count in execution inputs.") from exc
        try:
            pocket_min_size = int(raw_min_size) if raw_min_size is not None else 30
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_min_size in execution inputs.") from exc
        if pocket_count < 1:
            raise ValueError("pocket_count from execution inputs must be at least 1")
        if pocket_min_size < 1:
            raise ValueError("pocket_min_size from execution inputs must be at least 1")
        return protein_input, pocket_count, pocket_min_size

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``PocketFinder`` from a tools execution DTO.

        Rehydrates ``protein``, ``pocket_count``, and ``pocket_min_size`` from
        ``userInputs`` (falling back to ``inputs`` for older payloads). The
        protein is loaded with ``Protein.from_id(..., download=False)`` and
        ``remote_path_override`` from the stored input, matching
        :meth:`_tool_inputs` / :meth:`Docking.from_dto`.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``PocketFinder`` with ``id``, pricing fields, and domain inputs set.

        Raises:
            ValueError: If ``protein.id`` is missing from stored inputs.
        """
        instance = super().from_dto(dto, client=client)  # ty:ignore[unresolved-attribute]
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        protein_input, pocket_count, pocket_min_size = cls._parse_inputs_dict(inputs)

        instance._protein = Protein.from_id(
            str(protein_input["id"]),
            client=client,
            download=False,
            remote_path_override=protein_input.get("file_path"),
        )
        instance._pocket_count = pocket_count
        instance._pocket_min_size = pocket_min_size

        return instance

    @beartype
    def run(self) -> list[Pocket]:
        """Execute pocket finding (blocking).

        Submits a synchronous tools execution and returns fresh ``Pocket`` objects.

        Returns:
            List of ``Pocket`` objects found in the protein.

        Raises:
            DeepOriginException: If no pockets could be loaded from the data
                platform or ``jobOutputs``.
        """
        self._ensure_protein_remote()
        dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(sync=True),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self.update_from_dto(dto)

        try:
            pockets = Pocket.from_result(
                execution_id=self.id,
                client=self.client,
            )
        except Exception:
            try:
                jo = dto.get("jobOutputs")
                raw = jo.get("pockets", []) if isinstance(jo, dict) else []
                pockets = Pocket.from_json(raw, client=self.client)
            except Exception as exc:
                raise DeepOriginException(
                    title="Could not load pockets",
                    message=(
                        "No pockets could be parsed from the data platform or jobOutputs."
                    ),
                ) from exc

        if not pockets:
            raise DeepOriginException(
                title="Could not load pockets",
                message=(
                    "No pockets could be parsed from the data platform or jobOutputs."
                ),
            ) from None

        return pockets
