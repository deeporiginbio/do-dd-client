"""Data Platform dataset API wrapper (admin-scoped CRUD, search, and import trigger)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.auth import decode_access_token
from deeporigin.exceptions import DeepOriginException

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

ADMIN_PREFIX = "/data-platform/admin"
_SUPERUSER_REALM_ROLE = "do-super-user"


class Datasets:
    """Dataset API wrapper.

    Provides access to dataset CRUD, search, and import-trigger endpoints
    through the DeepOriginClient. All endpoints require SUPERUSER scope.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        self._c = client

    def _require_superuser(self) -> None:
        """Verify the client token carries the ``do-super-user`` realm role.

        Skipped for local environments (mock server, no real auth).

        Raises:
            DeepOriginException: If the token lacks the SUPERUSER role.
        """
        if self._c.env == "local":
            return
        claims = decode_access_token(self._c.token)
        roles: list[str] = claims.get("realm_access", {}).get("roles", [])
        if _SUPERUSER_REALM_ROLE not in roles:
            raise DeepOriginException(
                title="Insufficient Scope",
                message=(
                    "Dataset admin endpoints require the SUPERUSER role "
                    f"('{_SUPERUSER_REALM_ROLE}' in realm_access.roles). "
                    "Your current token does not have this role."
                ),
            )

    def search(
        self,
        *,
        cursor: str | None = None,
        filter_dict: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
        search: str | None = None,
        with_total_count: bool = False,
    ) -> dict:
        """Search datasets.

        Args:
            cursor: Keyset pagination cursor.
            filter_dict: Filter criteria (e.g. ``{"tags": {"in": ["HTS", "FBDD"]}}``).
            limit: Maximum number of results per page.
            offset: Number of results to skip.
            select: Fields to include in the response.
            sort: Sort specification (e.g. ``{"name": "asc"}``).
            search: Free-text search across fulltext-indexed fields (name, summary).
            with_total_count: If True, return only ``meta.total_count`` (no rows).

        Returns:
            Dictionary with ``data`` (list of datasets) and ``meta``.
        """
        self._require_superuser()
        body: dict[str, Any] = {}
        if cursor is not None:
            body["cursor"] = cursor
        if filter_dict is not None:
            body["filter"] = filter_dict
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if sort is not None:
            body["sort"] = sort
        if search is not None:
            body["search"] = search
        if with_total_count:
            body["with_total_count"] = True

        return self._c.post_json(f"{ADMIN_PREFIX}/datasets/search", body=body)

    def get(self, id: str) -> dict:
        """Get a dataset by ID.

        Args:
            id: Dataset ID (friendly or 16 hex chars).

        Returns:
            Dictionary containing the dataset record.
        """
        self._require_superuser()
        return self._c.get_json(f"{ADMIN_PREFIX}/datasets/{id}")

    def create(
        self,
        *,
        name: str,
        file_path: str,
        dataset_key: str,
        dataset_version: str,
        summary: str | None = None,
        description: str | None = None,
        source_url: str | None = None,
        source_name: str | None = None,
        tags: list[str] | None = None,
        compound_count: int | None = None,
        file_size_bytes: int | None = None,
        dataset_schema: dict[str, Any] | None = None,
        sample_rows: list[dict[str, Any]] | None = None,
        changelog: str | None = None,
    ) -> dict:
        """Create a dataset record.

        Args:
            name: Dataset display name (required).
            file_path: Resolved storage path in file-service (required).
            dataset_key: Routing key for catalog resolution (required).
            dataset_version: Routing version for catalog resolution (required).
            summary: Short blurb for card subtitle.
            description: Full detail text.
            source_url: Link to original data source.
            source_name: Display label for the external source link.
            tags: List of tag strings.
            compound_count: Total number of compounds/rows.
            file_size_bytes: Size of the dataset file in bytes.
            dataset_schema: JSON Schema with x-* extensions describing import structure.
            sample_rows: Cached first rows for preview.
            changelog: Description of what changed in this version.

        Returns:
            Dictionary containing the created dataset record.
        """
        self._require_superuser()
        set_dict: dict[str, Any] = {
            "name": name,
            "file_path": file_path,
            "dataset_key": dataset_key,
            "dataset_version": dataset_version,
        }
        if summary is not None:
            set_dict["summary"] = summary
        if description is not None:
            set_dict["description"] = description
        if source_url is not None:
            set_dict["source_url"] = source_url
        if source_name is not None:
            set_dict["source_name"] = source_name
        if tags is not None:
            set_dict["tags"] = tags
        if compound_count is not None:
            set_dict["compound_count"] = compound_count
        if file_size_bytes is not None:
            set_dict["file_size_bytes"] = file_size_bytes
        if dataset_schema is not None:
            set_dict["dataset_schema"] = dataset_schema
        if sample_rows is not None:
            set_dict["sample_rows"] = sample_rows
        if changelog is not None:
            set_dict["changelog"] = changelog

        return self._c.post_json(
            f"{ADMIN_PREFIX}/datasets",
            body={"set": set_dict},
        )

    def update(self, id: str, *, set_dict: dict[str, Any]) -> dict:
        """Update a dataset record.

        Args:
            id: Dataset ID (friendly or 16 hex chars).
            set_dict: Fields to update (e.g. ``{"description": "new text"}``).

        Returns:
            Dictionary containing the updated dataset record.
        """
        self._require_superuser()
        return self._c._patch(
            f"{ADMIN_PREFIX}/datasets/{id}",
            json={"set": set_dict},
        ).json()

    def trigger_import(
        self,
        id: str,
        *,
        org_key: str,
        cluster_id: str,
        batch_size: int | None = None,
        dry_run: bool | None = None,
        max_rows: int | None = None,
        name: str | None = None,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Trigger a dataset import into a target org.

        Args:
            id: Dataset ID to import.
            org_key: Target organization key.
            cluster_id: Compute cluster identifier (passed through to tools-service).
            batch_size: Number of rows per MQ batch.
            dry_run: If True, validate without writing data.
            max_rows: Maximum number of rows to import.
            name: Execution display name.
            project_id: Target project ID.
            metadata: Additional metadata passed to the import tool.

        Returns:
            Dictionary with ``executionId`` of the triggered import.
        """
        self._require_superuser()
        body: dict[str, Any] = {
            "orgKey": org_key,
            "clusterId": cluster_id,
        }
        if batch_size is not None:
            body["batchSize"] = batch_size
        if dry_run is not None:
            body["dryRun"] = dry_run
        if max_rows is not None:
            body["maxRows"] = max_rows
        if name is not None:
            body["name"] = name
        if project_id is not None:
            body["projectId"] = project_id
        if metadata is not None:
            body["metadata"] = metadata

        return self._c.post_json(
            f"{ADMIN_PREFIX}/datasets/{id}/import",
            body=body,
        )
