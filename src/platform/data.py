"""Data Platform API wrapper for DeepOriginClient."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Data:
    """Data Platform API wrapper.

    Provides access to data platform-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Data wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def health(self) -> dict:
        """Check the health status of the data platform.

        Returns:
            Dictionary containing the health status response.
        """
        return self._c.get_json("/data-platform/health")

    @lru_cache(maxsize=1)  # noqa: B019
    def list_models(self) -> dict:
        """List public models.

        Returns:
            Dictionary containing the list of models.
        """
        return self._c.get_json(f"/data-platform/{self._c.org_key}/meta/models")

    def search_ligands_with_results(
        self,
        *,
        cursor: str | None = None,
        experiments: list[dict[str, str]] | None = None,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Search ligands joined with tool results (wide pivot view).

        Args:
            cursor: Cursor for pagination.
            experiments: List of experiment filters, each containing toolId and
                optionally toolVersion.
            filter: Additional filter criteria as a dictionary.
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.
        """
        body: dict[str, Any] = {}
        if cursor is not None:
            body["cursor"] = cursor
        if experiments is not None:
            body["experiments"] = experiments
        if filter is not None:
            body["filter"] = filter
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if sort is not None:
            body["sort"] = sort

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/ligands_with_results/search",
            body=body,
        )

    def search(
        self,
        entity: str,
        *,
        cursor: str | None = None,
        filter_dict: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Search an entity (table).

        Args:
            entity: Entity (table) name to search (e.g., "ligands").
            cursor: Cursor for pagination.
            filter_dict: Additional filter criteria as a dictionary.
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.

        Raises:
            ValueError: If the entity is not a valid table name.
        """
        # Validate entity against list of available models
        models_response = self.list_models()
        valid_table_names = {
            model["tableName"] for model in models_response.get("models", [])
        }
        if entity not in valid_table_names:
            raise ValueError(
                f"Invalid entity '{entity}'. Valid entities are: {', '.join(sorted(valid_table_names))}"
            )

        if filter_dict is None:
            filter_dict = {"deleted": False}
        else:
            filter_dict = filter_dict.copy()
            filter_dict["deleted"] = False

        body: dict[str, Any] = {}
        if cursor is not None:
            body["cursor"] = cursor

        body["filter"] = filter_dict
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if sort is not None:
            body["sort"] = sort

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/{entity}/search",
            body=body,
        )

    def search_ligands(
        self,
        *,
        cursor: str | None = None,
        filter: dict[str, Any] | None = None,
        min_molecular_weight: float | int | None = None,
        max_molecular_weight: float | int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Search ligands entity.

        Convenience method that calls search(entity="ligands").

        Args:
            cursor: Cursor for pagination.
            filter: Additional filter criteria as a dictionary.
            min_molecular_weight: Minimum molecular weight filter (inclusive).
            max_molecular_weight: Maximum molecular weight filter (inclusive).
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.

        Raises:
            ValueError: If ligands is not a valid table name (should not happen).
        """
        # Build filter dict, starting with provided filter or empty dict
        filter_dict = filter.copy() if filter is not None else {}
        filter_dict.setdefault("deleted", False)

        # Build molecular weight filters
        props = []
        if min_molecular_weight is not None:
            props.append(
                {
                    "column": "molecular_weight",
                    "op": "gte",
                    "value": min_molecular_weight,
                }
            )
        if max_molecular_weight is not None:
            props.append(
                {
                    "column": "molecular_weight",
                    "op": "lte",
                    "value": max_molecular_weight,
                }
            )

        if props:
            # Merge with existing props if any
            existing_props = filter_dict.get("props", [])
            filter_dict["props"] = existing_props + props

        return self.search(
            "ligands",
            cursor=cursor,
            filter_dict=filter_dict,
            limit=limit,
            offset=offset,
            select=select,
            sort=sort,
        )

    def search_proteins(
        self,
        *,
        cursor: str | None = None,
        pdb_id: str | None = None,
        min_molecular_weight: float | int | None = None,
        max_molecular_weight: float | int | None = None,
        sequence: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Search proteins entity.

        Convenience method that calls search(entity="proteins").

        Args:
            cursor: Cursor for pagination.
            pdb_id: Filter by PDB ID.
            min_molecular_weight: Minimum molecular weight filter (inclusive).
            max_molecular_weight: Maximum molecular weight filter (inclusive).
            sequence: Filter by FASTA sequence (exact match).
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.

        Raises:
            ValueError: If proteins is not a valid table name (should not happen).
        """

        filter_dict = {"deleted": False}
        if pdb_id is not None:
            filter_dict["pdb_id"] = pdb_id

        # Build molecular weight filters
        props = []
        if min_molecular_weight is not None:
            props.append(
                {
                    "column": "molecular_weight",
                    "op": "gte",
                    "value": min_molecular_weight,
                }
            )
        if max_molecular_weight is not None:
            props.append(
                {
                    "column": "molecular_weight",
                    "op": "lte",
                    "value": max_molecular_weight,
                }
            )
        if sequence is not None:
            props.append(
                {
                    "column": "fasta_sequence",
                    "op": "eq",
                    "value": sequence,
                }
            )

        if props:
            filter_dict["props"] = props

        return self.search(
            "proteins",
            cursor=cursor,
            filter_dict=filter_dict,
            limit=limit,
            offset=offset,
            select=select,
            sort=sort,
        )
