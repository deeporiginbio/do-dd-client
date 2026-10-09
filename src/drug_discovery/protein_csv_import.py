"""Import a CSV of proteins of any size without holding an HTTP call open.

:meth:`ProteinCsvImport.start` stages the CSV (and an optional zip of
structure files), submits a hidden import-dataset execution that preflight
routes to the workflow, and returns a :class:`ProteinCsvImport` handle at once.
:meth:`ProteinCsvImport.wait` blocks on the data-platform SSE stream until
ingestion is done, then reads the project's proteins.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from deeporigin.drug_discovery.import_dataset_sync import (
    run_import_dataset_workflow,
    stage_local_file,
)
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.structures.repr_display import (
    fetch_project_display_name,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import is_success_status, normalize_platform_status
from deeporigin.platform.project_scope import require_client_project_id
from deeporigin.utils.constants import (
    DATA_PLATFORM_INGESTION_TIMEOUT_SECONDS,
    IMPORT_DATASET_PROTEINS_COLUMN_ALIASES,
    IMPORT_DATASET_PROTEINS_DATABASE_KEY,
    IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    IMPORT_DATASET_PROTEINS_GROUP,
    IMPORT_DATASET_PROTEINS_IDENTITY_FIELDS,
    PROTEIN_IMPORT_FAILED_TITLE,
    PROTEIN_SEARCH_PAGE_SIZE,
)


def _protein_import_failed(message: str) -> DeepOriginException:
    """Build the exception raised when a protein CSV import fails.

    Args:
        message: Human-readable failure detail.

    Returns:
        DeepOriginException: Exception titled ``PROTEIN_IMPORT_FAILED_TITLE``.
    """
    return DeepOriginException(title=PROTEIN_IMPORT_FAILED_TITLE, message=message)


def protein_csv_mapper(csv_path: str | Path) -> list[dict[str, str]]:
    """Map each column of a protein CSV to the protein field of the same name.

    The header is taken as is: column ``c`` is sent as ``proteins.c``, so the
    columns must be platform protein fields such as ``protein_name``,
    ``fasta_sequence``, ``pdb_id`` and ``file_path``. Only the header is read.

    Args:
        csv_path: Local path of the CSV.

    Returns:
        list[dict[str, str]]: One ``{"field", "json-path"}`` entry per column.

    Raises:
        DeepOriginException: If the CSV has no header row, or none of its
            columns is in ``IMPORT_DATASET_PROTEINS_IDENTITY_FIELDS``.
    """
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    columns = [column.strip() for column in header if column.strip()]
    if not columns:
        raise _protein_import_failed(f"The CSV {str(csv_path)!r} has no header row.")
    if not set(columns) & set(IMPORT_DATASET_PROTEINS_IDENTITY_FIELDS):
        renames = [
            f"{column!r} to {IMPORT_DATASET_PROTEINS_COLUMN_ALIASES[column]!r}"
            for column in columns
            if column in IMPORT_DATASET_PROTEINS_COLUMN_ALIASES
        ]
        hint = f" Rename {', '.join(renames)}." if renames else ""
        raise _protein_import_failed(
            f"The CSV {str(csv_path)!r} has columns {columns}, but needs at least "
            f"one of {list(IMPORT_DATASET_PROTEINS_IDENTITY_FIELDS)}.{hint}"
        )
    return [
        {"field": column, "json-path": f"{IMPORT_DATASET_PROTEINS_GROUP}.{column}"}
        for column in columns
    ]


def build_protein_csv_import_inputs(
    *,
    csv_path: str,
    mapper: list[dict[str, str]],
    protein_zip_path: str | None = None,
) -> dict[str, Any]:
    """Build import-dataset inputs for a protein CSV import.

    The inputs carry none of ``process_*``, ``register_*``, ``rows`` or
    ``sync``, so preflight routes the execution to the workflow and the submit
    call returns as soon as the execution is created. No ``result_lane`` is
    sent, so results use the tool's default lane.

    Args:
        csv_path: Remote (file-service) path of the staged CSV.
        mapper: CSV column to protein field mapping.
        protein_zip_path: Optional remote path of a staged zip of structure
            files named in the CSV's ``file_path`` column.

    Returns:
        dict[str, Any]: The ``inputs`` object for the import-dataset execution.
    """
    inputs: dict[str, Any] = {
        "csv_path": csv_path,
        "mapper": mapper,
        "database_key": IMPORT_DATASET_PROTEINS_DATABASE_KEY,
        "database_version": IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    }
    if protein_zip_path is not None:
        inputs["protein_zip_path"] = protein_zip_path
    return inputs


@dataclass(frozen=True)
class ProteinCsvImport:
    """Handle for a submitted protein CSV import.

    Create one with :meth:`start`, then call :meth:`wait` for the proteins.

    Attributes:
        execution_id: ID of the platform job running the import.
        project_id: Project the proteins are imported into.
        client: Client used to submit the import, reused by :meth:`wait`.
    """

    execution_id: str
    project_id: str
    client: DeepOriginClient

    @classmethod
    def start(
        cls,
        csv_path: str | Path,
        *,
        protein_zip_path: str | Path | None = None,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Submit a protein CSV import and return a handle without waiting.

        The CSV, and the optional zip of structure files, are uploaded first.
        The import then runs on the platform; call :meth:`wait` to block until
        it has finished and get the proteins.

        Args:
            csv_path: Local path of the CSV. Its header names the protein
                field each column fills, for example ``protein_name``,
                ``fasta_sequence``, ``pdb_id`` and ``file_path``.
            protein_zip_path: Optional local path of a zip of structure files.
                Each row's ``file_path`` is a filename inside this zip.
            client: Client to use. Defaults to ``DeepOriginClient()``. Must be
                scoped to a project.

        Returns:
            ProteinCsvImport: Handle holding the execution id and project id.

        Raises:
            DeepOriginException: If the CSV has no header row, or the platform
                does not return an execution id.
        """
        if client is None:
            client = DeepOriginClient()
        project_id = require_client_project_id(client)
        mapper = protein_csv_mapper(csv_path)

        remote_csv = stage_local_file(client, csv_path)
        remote_zip = (
            stage_local_file(client, protein_zip_path)
            if protein_zip_path is not None
            else None
        )
        inputs = build_protein_csv_import_inputs(
            csv_path=remote_csv,
            mapper=mapper,
            protein_zip_path=remote_zip,
        )
        dto = run_import_dataset_workflow(
            inputs=inputs,
            project_id=project_id,
            client=client,
        )
        execution_id = dto.get("executionId")
        if not execution_id:
            raise _protein_import_failed(
                "import-dataset did not return an execution id for the protein CSV."
            )
        return cls(
            execution_id=str(execution_id),
            project_id=project_id,
            client=client,
        )

    def wait(
        self,
        *,
        timeout: float = DATA_PLATFORM_INGESTION_TIMEOUT_SECONDS,
    ) -> list[Protein]:
        """Block until the import has finished, then return the project's proteins.

        Returns as soon as the platform reports the import finished. A protein
        that already existed in the project is reused rather than imported
        twice, so this returns every protein in the project, not only the rows
        in the CSV.

        Args:
            timeout: Seconds to wait before giving up.

        Returns:
            list[Protein]: Every protein in the project, metadata only (no
            structure downloaded).

        Raises:
            DeepOriginException: If the import ended in a status other than
                success.
            TimeoutError: If the import has not finished within ``timeout``.
        """
        row = self.client.executions.wait_for_ingestion(  # ty: ignore[unresolved-attribute]
            self.execution_id,
            project_id=self.project_id,
            timeout=timeout,
        )
        status = normalize_platform_status(row.get("status"))
        if not is_success_status(status):
            raise _protein_import_failed(
                f"Protein import (execution_id={self.execution_id!r}) ended with "
                f"status {status!r}: {self._status_reason(fallback=status)}"
            )
        return self._project_proteins()

    def _status_reason(self, *, fallback: str | None) -> str:
        """Return the tools-service ``statusReason`` for this execution.

        The data-platform execution row carries no failure reason, so it is
        read from the tools-service execution.

        Args:
            fallback: Value returned when the execution has no reason.

        Returns:
            str: The status reason, or ``fallback``.
        """
        dto = self.client.executions.get(self.execution_id)  # ty: ignore[unresolved-attribute]
        reason = dto.get("statusReason") if isinstance(dto, dict) else None
        return str(reason or fallback)

    def _project_proteins(self) -> list[Protein]:
        """Read every protein in the project, following the search cursor.

        Returns:
            list[Protein]: Metadata-only proteins in the project.
        """
        project_name = fetch_project_display_name(
            self.project_id, None, client=self.client
        )[0]
        proteins: list[Protein] = []
        cursor: str | None = None
        while True:
            response = self.client.entities.search_proteins(  # ty: ignore[unresolved-attribute]
                project_id=self.project_id,
                limit=PROTEIN_SEARCH_PAGE_SIZE,
                cursor=cursor,
            )
            page = response.get("data") or []
            proteins.extend(
                Protein._from_platform_record(
                    record,
                    client=self.client,
                    remote_path=record.get("file_path"),
                    project_name=project_name,
                )
                for record in page
                if isinstance(record, dict)
            )
            cursor = (response.get("meta") or {}).get("nextCursor")
            if not cursor:
                return proteins
