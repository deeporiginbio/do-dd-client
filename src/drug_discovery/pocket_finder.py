"""PocketFinder -- sync-only execution for detecting protein binding pockets.

Usage::

    pf = PocketFinder(protein)
    pf.quote()          # populates pf.estimate
    pockets = pf.run()  # blocking; populates pf.cost
"""

from __future__ import annotations

from typing import Any

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    POCKET_FINDER_FUNCTION_KEY,
    POCKET_FINDER_FUNCTION_VERSION,
)


class PocketFinder(Execution, QuoteMixin, SyncExecutableMixin):
    """Find binding pockets in a protein structure (sync-only).

    This is a blocking operation that typically completes in under 2 minutes.
    It does **not** create a persisted execution record on the platform, so
    ``status``, ``from_id()``, and ``list()`` are not available.

    Attributes:
        protein: The protein to analyse.
        pocket_count: Maximum number of pockets to detect.
        pocket_min_size: Minimum pocket volume in cubic Angstroms.
    """

    tool_key: str = POCKET_FINDER_FUNCTION_KEY

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        pocket_count: int = 1,
        pocket_min_size: int = 30,
        tool_version: str = POCKET_FINDER_FUNCTION_VERSION,
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

    def _pocket_finder_function_params(self) -> dict[str, Any]:
        """Build the ``params`` object for :meth:`DeepOriginClient.functions.run`."""
        return {
            "protein": {
                "file_path": self._protein.remote_path,
                "id": self._protein.id,
            },
            "pocket_count": self._pocket_count,
            "pocket_min_size": self._pocket_min_size,
        }

    def _get_quote(self) -> dict[str, Any]:
        """Call the functions API with ``quote=True`` and return the raw response."""
        self._ensure_protein_remote()
        return self.client.functions.run(
            key=POCKET_FINDER_FUNCTION_KEY,
            version=self.tool_version,
            params=self._pocket_finder_function_params(),
            quote=True,
        )

    @beartype
    def run(self) -> list[Pocket]:
        """Execute pocket finding (blocking).

        Always runs the tool and returns fresh results.

        Returns:
            List of ``Pocket`` objects found in the protein.
        """
        self._ensure_protein_remote()
        raw = self.client.functions.run(
            key=POCKET_FINDER_FUNCTION_KEY,
            version=self.tool_version,
            params=self._pocket_finder_function_params(),
            quote=False,
        )
        result = FunctionResult([raw])

        execution_id = result._responses[0]["id"]
        self._id = execution_id

        if self.protein.id is not None:
            try:
                pockets = Pocket.from_result(
                    execution_id=execution_id,
                    client=self.client,
                )
            except Exception:
                import warnings

                warnings.warn(
                    "Could not load pocket results from the data platform; "
                    "using function response instead. Results may be delayed.",
                    stacklevel=2,
                )
                pockets = Pocket.from_function_result(
                    result=result,
                    client=self.client,
                )
        else:
            pockets = Pocket.from_function_result(
                result=result,
                client=self.client,
            )

        self._cost = result.cost
        self.status = result.status

        return pockets
