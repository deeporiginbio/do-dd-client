"""PocketFinder -- sync-only execution for detecting protein binding pockets.

Usage::

    pf = PocketFinder(protein)
    pf.quote()          # populates pf.estimate
    pockets = pf.run()  # blocking; populates pf.cost
"""

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
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

    def _quote_impl(self) -> None:
        """Request a cost estimate for pocket finding.

        Populates ``self.estimate`` with the estimated cost in dollars.
        Does **not** mutate lifecycle status (sync-only class).
        """
        from deeporigin.functions.pocket_finder import find_pockets as _find_pockets

        client = self.client

        result = _find_pockets(
            protein=self.protein,
            pocket_count=self.pocket_count,
            pocket_min_size=self.pocket_min_size,
            client=client,
            quote=True,
        )

        self._estimate = result.estimate

    def run(self) -> list[Pocket]:
        """Execute pocket finding (blocking).

        Returns the detected pockets and populates ``self.cost`` with
        the actual cost incurred.

        Returns:
            List of ``Pocket`` objects found in the protein.
        """
        from deeporigin.drug_discovery.structures.protein import (
            _make_pockets_from_result,
        )
        from deeporigin.functions.pocket_finder import (
            cache_path as _pocket_cache_path,
        )
        from deeporigin.functions.pocket_finder import (
            find_pockets as _find_pockets,
        )

        client = self.client

        result = _find_pockets(
            protein=self.protein,
            pocket_count=self.pocket_count,
            pocket_min_size=self.pocket_min_size,
            client=client,
            quote=False,
        )

        pockets = _make_pockets_from_result(
            result=result,
            client=client,
            cache_path_fn=_pocket_cache_path,
            use_cache=True,
        )

        self._cost = result.cost

        return pockets

    def get_results(self) -> list[Pocket]:
        """Retrieve previously computed pockets from the platform.

        Fetches pocket results for this protein via the results API,
        without re-running the computation.

        Returns:
            List of ``Pocket`` objects retrieved from the platform.
        """
        return Pocket.from_result(
            protein_id=self.protein.id,
            client=self.client,
        )
