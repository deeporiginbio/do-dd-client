"""Patent -- extract chemical structures from PDF documents via ``deeporigin.draco``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self
import uuid

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import UFA_PROVIDER

_PATENT_OUTPUT_KEY = "do_patent_molecules"
_PATENT_UPLOAD_PREFIX = "patent/"
_LIGANDS_WITH_RESULTS_PAGE_SIZE = 1000


@beartype
def _patent_ligands_with_results_dataframe(
    response: dict[str, Any],
) -> pd.DataFrame | None:
    """Build a ligand table from ``ligands_with_results`` search rows."""
    ligands = response.get("data")
    if not isinstance(ligands, list) or not ligands:
        return None

    molecules: list[dict[str, Any]] = []
    for ligand in ligands:
        if not isinstance(ligand, dict):
            continue
        results = ligand.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            smiles = result.get("smiles") or ligand.get("smiles")
            row = dict(result)
            row["smiles"] = smiles
            molecules.append(row)

    return _patent_molecules_to_dataframe(molecules)


@beartype
def _paginate_ligands_with_results_search(
    *,
    client: DeepOriginClient,
    org_key: str,
    base_body: dict[str, Any],
) -> dict[str, Any]:
    """Run a cursor-paginated ligands-with-results search."""
    all_data: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    cursor: str | None = None

    while True:
        body = dict(base_body)
        if cursor is not None:
            body["cursor"] = cursor

        try:
            response = client.post_json(
                f"/data-platform/{org_key}/ligands_with_results/search",
                body=body,
            )
        except DeepOriginException:
            if all_data:
                break
            raise

        page_data = response.get("data")
        if isinstance(page_data, list):
            all_data.extend(page_data)

        page_meta = response.get("meta")
        if isinstance(page_meta, dict):
            meta = page_meta

        next_cursor = (
            page_meta.get("nextCursor") if isinstance(page_meta, dict) else None
        )
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor

    return {"data": all_data, "meta": meta}


@beartype
def _fetch_patent_ligands_with_results(
    *,
    client: DeepOriginClient,
    org_key: str,
    tool_key: str,
    tool_version: str,
    execution_id: str,
) -> dict[str, Any]:
    """Query do-patent molecules via the ligands-with-results search API."""
    experiments = [
        {
            "tool_key": tool_key,
            "tool_version": tool_version,
            "output_key": _PATENT_OUTPUT_KEY,
            "execution_ids": [execution_id],
        }
    ]
    search_bodies: list[dict[str, Any]] = [
        {
            "experiments": experiments,
            "only_with_results": True,
            "limit": _LIGANDS_WITH_RESULTS_PAGE_SIZE,
        },
        {
            "experiments": experiments,
            "only_with_results": True,
            "results_layout": "rows",
            "limit": _LIGANDS_WITH_RESULTS_PAGE_SIZE,
            "select": ["id", "smiles", "canonical_smiles", "results"],
        },
        {
            "experiments": experiments,
            "only_with_results": True,
            "results_layout": "rows",
            "limit": _LIGANDS_WITH_RESULTS_PAGE_SIZE,
            "select": ["id", "smiles", "canonical_smiles", "results"],
            "sort": {"id": "asc"},
        },
    ]

    last_error: DeepOriginException | None = None
    for base_body in search_bodies:
        try:
            response = _paginate_ligands_with_results_search(
                client=client,
                org_key=org_key,
                base_body=base_body,
            )
        except DeepOriginException as exc:
            last_error = exc
            continue

        if response.get("data"):
            return response

    if last_error is not None:
        raise last_error

    return {"data": [], "meta": {}}


_PATENT_RESULT_COLUMNS = (
    "smiles",
    "name",
    "page",
    "confidence",
    "type",
    "record_id",
    "source",
)


@beartype
def _patent_molecules_to_dataframe(
    molecules: list[dict[str, Any]],
) -> pd.DataFrame | None:
    """Build a ligand-oriented table from raw do-patent molecule dicts."""
    ligand_rows: list[dict[str, Any]] = []
    for data in molecules:
        if not isinstance(data, dict):
            continue
        smiles = data.get("smiles")
        if not isinstance(smiles, str) or not smiles.strip():
            continue
        ligand_rows.append(
            {
                "smiles": smiles.strip(),
                "name": data.get("iupac_name"),
                "page": data.get("page"),
                "confidence": data.get("confidence"),
                "type": data.get("type"),
                "record_id": data.get("record_id"),
                "source": data.get("source"),
            }
        )

    if not ligand_rows:
        return None

    df = pd.DataFrame(ligand_rows)
    head = [c for c in _PATENT_RESULT_COLUMNS if c in df.columns]
    tail = [c for c in df.columns if c not in head]
    return df[head + tail]


@beartype
def _patent_results_dataframe(response: dict[str, Any]) -> pd.DataFrame | None:
    """Build a ligand-oriented table from do-patent molecule result rows."""
    rows = response.get("data")
    if not isinstance(rows, list) or not rows:
        return None

    molecules: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        data = row.get("data")
        if isinstance(data, dict):
            molecules.append(data)

    return _patent_molecules_to_dataframe(molecules)


class Patent(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """Extract chemical structures from a patent or chemistry PDF.

    Async-only workflow backed by platform tool ``deeporigin.draco``. Upload a
    local PDF with :meth:`start`, optionally quote first via ``start(quote=True)``
    and :meth:`confirm`, then poll with :meth:`wait` or :meth:`sync` and read
    extracted structures via :meth:`get_results`.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["patent"]["tool_key"]

    @beartype
    def __init__(
        self,
        pdf: str | Path,
        *,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["patent"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create a Patent job for the given local PDF path.

        Args:
            pdf: Path to a local ``.pdf`` file. Uploaded to UFA on ``start()``.
            tool_version: Platform tool version pin.
            client: Optional API client.
            name: Optional execution label.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._pdf_path: Path | None = None
        self._remote_pdf_path: str | None = None
        self._validate_pdf_path(pdf)
        self._pdf_path = Path(pdf).expanduser().resolve()
        if name is not None:
            self.name = name

    @property
    def pdf(self) -> Path | None:
        """Local PDF path when known (``None`` after :meth:`from_dto` rehydration)."""
        return self._pdf_path

    @property
    def remote_pdf_path(self) -> str | None:
        """UFA key for the uploaded PDF after :meth:`start` or :meth:`from_dto`."""
        return self._remote_pdf_path

    def __repr__(self) -> str:
        """Return a concise summary of the Patent job."""
        parts = ["Patent("]
        if self._pdf_path is not None:
            parts.append(f"pdf={self._pdf_path!r}")
        elif self._remote_pdf_path is not None:
            parts.append(f"remote_pdf_path={self._remote_pdf_path!r}")
        if self.id:
            parts.append(f"id={self.id!r}")
        parts.append(")")
        return "".join(parts)

    @beartype
    def _validate_pdf_path(self, pdf: str | Path) -> None:
        """Raise if ``pdf`` is missing or not a ``.pdf`` file."""
        path = Path(pdf).expanduser()
        if not path.is_file():
            msg = f"PDF file not found: {path}"
            raise ValueError(msg)
        if path.suffix.lower() != ".pdf":
            msg = f"Expected a .pdf file, got: {path.suffix!r}"
            raise ValueError(msg)

    @beartype
    def _ensure_pdf_uploaded(self) -> str:
        """Upload the local PDF when needed and return the UFA remote key."""
        if self._remote_pdf_path is not None:
            return self._remote_pdf_path
        if self._pdf_path is None:
            msg = "Cannot upload PDF: no local path is set on this Patent instance."
            raise ValueError(msg)

        remote_path = f"{_PATENT_UPLOAD_PREFIX}{uuid.uuid4().hex}/{self._pdf_path.name}"
        assert self.client.files is not None
        self.client.files.upload(self._pdf_path, remote_path)
        self._remote_pdf_path = remote_path
        return remote_path

    def _build_params(self) -> dict[str, Any]:
        """Construct workflow input parameters for ``deeporigin.draco``."""
        remote_path = self._ensure_pdf_uploaded()
        return {
            "input_file": {
                "$provider": UFA_PROVIDER,
                "key": remote_path,
            },
        }

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Build create payload for ``executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._build_params(),
            "outputs": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        if self.name is not None:
            payload["name"] = self.name
        return payload

    @beartype
    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit the patent extraction execution to the platform.

        Args:
            approve_amount: Spend cap forwarded to the platform. ``0`` requests
                a quote only; ``None`` runs immediately.
        """
        _ = kwargs
        payload = self._make_payload(approve_amount=approve_amount, sync=False)
        execution_dto = self._create_execution(data=payload)
        if execution_dto.get("executionId") is None:
            msg = "Execution response must contain 'executionId'"
            raise ValueError(msg)
        self.update_from_dto(execution_dto)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a Patent instance from an execution DTO.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client.

        Returns:
            A fully-hydrated Patent instance with status from the DTO.

        Raises:
            ValueError: If ``input_file.key`` is missing from stored inputs.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        input_file = inputs.get("input_file")
        if not isinstance(input_file, dict) or not input_file.get("key"):
            msg = "Missing 'input_file.key' in execution userInputs."
            raise ValueError(msg)

        instance._pdf_path = None
        instance._remote_pdf_path = str(input_file["key"])
        return instance

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a Patent instance from an existing platform execution ID."""
        return super().from_id(id, client=client)

    def get_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve extracted structures as a ligand-oriented DataFrame.

        Returns:
            A DataFrame with ``smiles``, ``name``, ``page``, and related columns,
            or ``None`` if the job has not succeeded or no molecules were found.

        Raises:
            ValueError: If no execution has been started.
        """
        self.sync()
        if not is_success_status(self.status):
            return None

        exec_id = self.id
        if exec_id is None:
            raise ValueError(
                "Cannot get results: no execution has been started (id is None)."
            )

        tool_version = self.tool_version
        if isinstance(self.dto, dict):
            tool_info = self.dto.get("tool") or {}
            tool_version = str(tool_info.get("version") or tool_version)

        try:
            ligands_response = _fetch_patent_ligands_with_results(
                client=self.client,
                org_key=self.client.org_key,
                tool_key=self.tool_key,
                tool_version=tool_version,
                execution_id=exec_id,
            )
        except DeepOriginException:
            ligands_response = None

        if isinstance(ligands_response, dict):
            df = _patent_ligands_with_results_dataframe(ligands_response)
            if df is not None:
                return df

        response = super().get_results()
        if isinstance(response, dict):
            df = _patent_results_dataframe(response)
            if df is not None:
                return df

        dto = self.dto
        job_outputs: dict[str, Any] | None = None
        if isinstance(dto, dict):
            raw_outputs = dto.get("jobOutputs")
            if isinstance(raw_outputs, dict):
                job_outputs = raw_outputs

        if job_outputs is None:
            fresh_dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            if isinstance(fresh_dto, dict):
                raw_outputs = fresh_dto.get("jobOutputs")
                if isinstance(raw_outputs, dict):
                    job_outputs = raw_outputs

        if isinstance(job_outputs, dict):
            molecules = job_outputs.get(_PATENT_OUTPUT_KEY)
            if isinstance(molecules, list):
                return _patent_molecules_to_dataframe(molecules)

        return None
