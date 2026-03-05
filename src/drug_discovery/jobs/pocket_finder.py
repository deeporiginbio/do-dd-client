"""PocketFinder -- sync-only job for detecting protein binding pockets.

Usage::

    pf = PocketFinder(protein)
    pf.quote()          # populates pf.estimate
    pockets = pf.run()  # blocking; populates pf.cost
"""

from beartype import beartype

from deeporigin.drug_discovery.jobs.base import JobBase
from deeporigin.drug_discovery.jobs.mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    POCKET_FINDER_FUNCTION_KEY,
    POCKET_FINDER_FUNCTION_VERSION,
)


class PocketFinder(JobBase, QuoteMixin, SyncExecutableMixin):
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
    tool_version: str = POCKET_FINDER_FUNCTION_VERSION

    _immutable_fields: frozenset[str] = frozenset(
        {"protein", "pocket_count", "pocket_min_size"}
    )

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        pocket_count: int = 1,
        pocket_min_size: int = 30,
        use_cache: bool = True,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a PocketFinder for the given protein.

        Args:
            protein: Protein structure to search for pockets.
            pocket_count: Maximum number of pockets to detect. Defaults to 1.
            pocket_min_size: Minimum pocket size in cubic Angstroms. Defaults to 30.
            use_cache: Whether to use cached results if available. Defaults to True.
            client: Optional API client. Uses the default if not provided.
        """
        super().__init__()
        with self._system_update():
            self.protein = protein
            self.pocket_count = pocket_count
            self.pocket_min_size = pocket_min_size
        self._use_cache = use_cache
        self._client = client

    def quote(self) -> None:
        """Request a cost estimate for pocket finding.

        Populates ``self.estimate`` with the estimated cost in dollars.
        Does **not** mutate lifecycle status (sync-only class).
        """
        from deeporigin.functions.pocket_finder import find_pockets as _find_pockets

        client = self._resolve_client()

        result = _find_pockets(
            protein=self.protein,
            pocket_count=self.pocket_count,
            pocket_min_size=self.pocket_min_size,
            client=client,
            quote=True,
        )

        with self._system_update():
            self.estimate = result.estimate

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

        client = self._resolve_client()

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
            use_cache=self._use_cache,
        )

        with self._system_update():
            self.cost = result.cost

        return pockets

    def _resolve_client(self) -> DeepOriginClient:
        """Return the client, falling back to the default singleton."""
        if self._client is not None:
            return self._client
        return DeepOriginClient.get()
