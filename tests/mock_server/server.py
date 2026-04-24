"""Local test server that mimics the DeepOrigin Platform API.

This server runs locally during tests to provide mock responses for all
API endpoints used by the DeepOriginClient.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any

from fastapi import FastAPI
import uvicorn

from .constants import (
    MOCK_BULK_DOCKING_EXECUTION_ID,
    MOCK_BULK_DOCKING_POSES_SDF_PATH,
)
from .routers import billing, data_platform, entities, files, tools
from .routers.data_platform import (
    MOCK_CANONICAL_POCKET_ID,
    MOCK_CANONICAL_PROTEIN_ID,
    MOCK_DEFAULT_PROJECT_ID,
    _base_canonical_protein_record,
    _base_default_project_record,
)


class MockServer:
    """Local test server for mocking DeepOrigin Platform API.

    When used in tests (via conftest.py), the server runs on port 4931.
    For standalone use, the port can be specified via the port parameter.
    """

    def __init__(self, port: int = 0, docking_speed: float = 0.5):
        """Initialize the test server.

        Args:
            port: Port to run the server on. If 0, uses any available port.
                Note: Tests use port 4931 (configured in conftest.py).
            docking_speed: Dockings per second used to derive simulated bulk-docking
                duration (``num_ligands / docking_speed`` seconds). Default is ``0.5``.
        """
        self.app = FastAPI()
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self._file_storage: dict[str, bytes] = {}
        self.host: str | None = None
        self._fixtures_dir = Path(__file__).parent.parent / "fixtures"
        self._fixture_cache: dict[str, dict[str, Any]] = {}
        # In-memory storage for executions
        self._executions: dict[str, dict[str, Any]] = {}
        self._execution_start_times: dict[str, datetime] = {}
        self._ligands: dict[str, dict[str, Any]] = {}
        self._proteins: dict[str, dict[str, Any]] = {}
        self._projects: dict[str, dict[str, Any]] = {}
        self._results: list[dict[str, Any]] = []
        # Tool-specific mock execution durations (in seconds)
        self._mock_execution_durations: dict[str, float] = {
            "deeporigin.abfe-end-to-end": 30.0,  # seconds
            "deeporigin.docking": 0.1,  # short poll for local Docking.run (tools API)
        }
        self.docking_speed = docking_speed
        self._load_execution_fixtures()
        self._load_ligand_fixtures()
        self._load_result_explorer_fixtures()
        self._seed_canonical_mock_protein()
        self._seed_default_project()
        self._setup_routes()

    def _load_fixture(self, fixture_name: str) -> dict[str, Any]:
        """Load a JSON fixture file.

        Args:
            fixture_name: Name of the fixture file (without .json extension).
                Can include subdirectory paths, e.g., "abfe/execution-quoted".

        Returns:
            Dictionary containing the fixture data.

        Raises:
            FileNotFoundError: If the fixture file doesn't exist.
        """
        if fixture_name in self._fixture_cache:
            return self._fixture_cache[fixture_name]

        fixture_path = self._fixtures_dir / f"{fixture_name}.json"
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

        with open(fixture_path) as f:
            data = json.load(f)

        self._fixture_cache[fixture_name] = data
        return data

    def _load_execution_fixtures(self) -> None:
        """Load all execution fixtures from the executions directory."""
        executions_dir = self._fixtures_dir / "executions"
        if executions_dir.exists():
            for fixture_file in executions_dir.glob("*.json"):
                with open(fixture_file) as f:
                    execution_data = json.load(f)
                    execution_id = execution_data.get("executionId")
                    if execution_id:
                        self._executions[execution_id] = execution_data

    def _load_execution_fixture(self, execution_id: str) -> dict[str, Any]:
        """Load an execution fixture by execution ID.

        Args:
            execution_id: The execution ID to load.

        Returns:
            Dictionary containing the execution fixture data.

        Raises:
            FileNotFoundError: If the execution fixture doesn't exist.
        """
        fixture_path = self._fixtures_dir / "executions" / f"{execution_id}.json"
        if not fixture_path.exists():
            raise FileNotFoundError(f"Execution fixture not found: {fixture_path}")

        with open(fixture_path) as f:
            return json.load(f)

    @staticmethod
    def _make_ligand_id(canonical_smiles: str) -> str:
        """Generate a deterministic ligand ID from a canonical SMILES string.

        Args:
            canonical_smiles: The canonical SMILES to hash.

        Returns:
            A 13-character ID matching the ``08`` + 11-hex-char format used by
            the real data platform.
        """
        digest = hashlib.sha256(canonical_smiles.encode()).hexdigest().upper()
        return "08" + digest[:11]

    def _load_ligand_fixtures(self) -> None:
        """Scan SDF and JSON files to pre-populate the in-memory ligand store.

        Sources (in order):
        1. ``src/data/brd/*.sdf``  (BRD_DATA_DIR package-data ligands)
        2. ``tests/fixtures/ligands-brd-all.sdf``
        3. ``tests/fixtures/brd-7.sdf``
        4. ``tests/fixtures/ligand_*.json``

        Non-BRD pools such as ``42-ligands.sdf`` are intentionally not loaded so
        mock ``search_ligands`` results stay BRD-only (project-scoped queries still
        match fixture rows scoped to ``MOCK_DEFAULT_PROJECT_ID`` or legacy
        ``project_id is None``).

        Deduplication is by canonical SMILES — the first occurrence wins.
        IDs are derived deterministically from the canonical SMILES so that
        the same ligand always gets the same ID across test runs.
        """
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors
        except ImportError:
            return

        seen_smiles: set[str] = set()
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        def _ingest_mol(
            mol: Chem.Mol,
            *,
            ligand_id: str | None = None,
            mol_file_remote: str | None = None,
        ) -> None:
            """Convert an RDKit Mol into a ligand record and store it."""
            canonical = Chem.MolToSmiles(mol)
            if canonical in seen_smiles:
                return
            seen_smiles.add(canonical)

            name = mol.GetProp("_Name") if mol.HasProp("_Name") else "Unknown"
            if ligand_id is None:
                ligand_id = self._make_ligand_id(canonical)

            record: dict[str, Any] = {
                "id": ligand_id,
                "version": 1,
                "valid_from": now_ts,
                "valid_to": None,
                "modified_by": "mock-server",
                "deleted": False,
                "project_id": MOCK_DEFAULT_PROJECT_ID,
                "subtable_name": "ligands",
                "smiles": canonical,
                "canonical_smiles": canonical,
                "name": name,
                "molecular_weight": Descriptors.ExactMolWt(mol),
                "inchi_key": None,
                "inchi": None,
                "log_p": None,
                "structure_key": None,
                "formal_charge": Chem.GetFormalCharge(mol),
                "hbond_donor_count": Descriptors.NumHDonors(mol),
                "hbond_acceptor_count": Descriptors.NumHAcceptors(mol),
                "rotatable_bond_count": Descriptors.NumRotatableBonds(mol),
                "tpsa": Descriptors.TPSA(mol),
            }
            # Align with production search rows: mol_file so sync() can set remote_path
            # when matching pre-seeded BRD ligands (fixtures under files/testing/).
            if mol_file_remote is not None:
                record["mol_file"] = mol_file_remote
            self._ligands[ligand_id] = record

        def _ingest_sdf(path: Path, *, use_stem_as_id: bool = False) -> None:
            """Parse all molecules from an SDF file."""
            supplier = Chem.SDMolSupplier(str(path), removeHs=True)
            mol_file_remote = f"testing/{path.stem}.sdf" if use_stem_as_id else None
            for mol in supplier:
                if mol is None:
                    continue
                try:
                    lid = path.stem if use_stem_as_id else None
                    _ingest_mol(mol, ligand_id=lid, mol_file_remote=mol_file_remote)
                except Exception:
                    continue

        brd_dir = Path(__file__).parent.parent.parent / "src" / "data" / "brd"
        if brd_dir.exists():
            for sdf_file in sorted(brd_dir.glob("*.sdf")):
                _ingest_sdf(sdf_file, use_stem_as_id=True)

        for sdf_name in ("ligands-brd-all.sdf", "brd-7.sdf"):
            sdf_path = self._fixtures_dir / sdf_name
            if sdf_path.exists():
                _ingest_sdf(sdf_path)

        for json_path in sorted(self._fixtures_dir.glob("ligand_*.json")):
            with open(json_path) as f:
                data: dict[str, Any] = json.load(f)
            canonical = data.get("canonical_smiles", "")
            if canonical and canonical not in seen_smiles:
                seen_smiles.add(canonical)
                if data.get("project_id") is None:
                    data = {**data, "project_id": MOCK_DEFAULT_PROJECT_ID}
                self._ligands[data["id"]] = data

    def _ordered_brd_ligand_ids(self, *, limit: int = 8) -> list[str]:
        """Return up to ``limit`` BRD ligand ids (``brd-2`` …) in stable file order."""
        brd_dir = Path(__file__).parent.parent.parent / "src" / "data" / "brd"
        stems: list[str] = []
        if brd_dir.is_dir():
            for sdf in sorted(brd_dir.glob("brd-*.sdf")):
                stems.append(sdf.stem)
        if len(stems) >= limit:
            return stems[:limit]
        fallback = sorted(k for k in self._ligands if k.startswith("brd-"))
        return fallback[:limit] if len(fallback) >= limit else fallback

    def _sanitize_bulk_docking_result_explorer_records(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Normalize bulk-docking pose rows for the local mock (IDs, pocket, paths).

        Expects poses in file order: 16 rows per ligand for eight BRD ligands
        (``brd-2`` … ``brd-9`` from ``src/data/brd``), 128 rows total.
        """
        brd_ids = self._ordered_brd_ligand_ids(limit=8)
        if not brd_ids:
            return

        poses_per_ligand = 16
        sdf_path = MOCK_BULK_DOCKING_POSES_SDF_PATH

        for i, row in enumerate(records):
            row["compute_job_id"] = MOCK_BULK_DOCKING_EXECUTION_ID
            if row.get("tool_key") is None:
                row["tool_key"] = "deeporigin.bulk-docking"
            row.setdefault("result_type", "pose")

            lig_index = min(i // poses_per_ligand, len(brd_ids) - 1)
            ligand_id = brd_ids[lig_index]

            data = row.get("data")
            if not isinstance(data, dict):
                data = {}
                row["data"] = data

            data["pocket_id"] = MOCK_CANONICAL_POCKET_ID
            data["protein_id"] = MOCK_CANONICAL_PROTEIN_ID
            data["ligand_id"] = ligand_id
            data["file_path"] = sdf_path

    def _load_result_explorer_fixtures(self) -> None:
        """Load result-explorer fixture files into the in-memory results store.

        Scans ``tests/fixtures/result-explorer-*.json`` for files containing a
        ``data`` list and appends all records.

        Files whose names start with ``result-explorer-bulk-docking`` are
        post-processed for mock-local pocket/protein/ligand ids and a shared
        ``file_path`` to ``MOCK_BULK_DOCKING_POSES_SDF_PATH``.
        """
        for json_path in sorted(self._fixtures_dir.glob("result-explorer-*.json")):
            with open(json_path) as f:
                fixture: dict[str, Any] = json.load(f)
            rows = fixture.get("data", [])
            if json_path.name.startswith("result-explorer-bulk-docking"):
                self._sanitize_bulk_docking_result_explorer_records(rows)
            self._results.extend(rows)

    def _seed_canonical_mock_protein(self) -> None:
        """Ensure one stable protein row exists for sync/register and get_protein."""
        if MOCK_CANONICAL_PROTEIN_ID not in self._proteins:
            self._proteins[MOCK_CANONICAL_PROTEIN_ID] = copy.deepcopy(
                _base_canonical_protein_record()
            )

    def _seed_default_project(self) -> None:
        """Ensure one stable project row exists so projects.current() resolves it."""
        if MOCK_DEFAULT_PROJECT_ID not in self._projects:
            self._projects[MOCK_DEFAULT_PROJECT_ID] = copy.deepcopy(
                _base_default_project_record()
            )

    def _setup_routes(self) -> None:
        """Set up all API routes."""
        # Include file-related routes
        files_router = files.create_files_router(self._file_storage, self._fixtures_dir)
        self.app.include_router(files_router)

        # Include data-platform routes
        dp_router = data_platform.create_data_platform_router(
            ligands=self._ligands,
            proteins=self._proteins,
            projects=self._projects,
            results=self._results,
            executions=self._executions,
            load_fixture=self._load_fixture,
        )
        self.app.include_router(dp_router)

        # Include tools routes
        tools_router = tools.create_tools_router(
            executions=self._executions,
            execution_start_times=self._execution_start_times,
            mock_execution_durations=self._mock_execution_durations,
            docking_speed=self.docking_speed,
            fixtures_dir=self._fixtures_dir,
            load_fixture=self._load_fixture,
            results=self._results,
        )
        self.app.include_router(tools_router)

        # Include entities routes
        entities_router = entities.create_entities_router()
        self.app.include_router(entities_router)

        # Include billing routes
        billing_router = billing.create_billing_router()
        self.app.include_router(billing_router)

        @self.app.get("/health")
        def health() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "ok"}

    def start(self) -> tuple[str, int]:
        """Start the test server.

        Returns:
            Tuple of (host, port) where the server is running.
        """
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",  # Suppress uvicorn logs during tests
        )
        self.server = uvicorn.Server(config)

        def run_server():
            self.server.run()

        self.thread = threading.Thread(target=run_server)
        self.thread.daemon = True
        self.thread.start()

        # Wait for server to start

        max_wait = 5.0
        waited = 0.0
        while not self.server.started and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1

        if not self.server.started:
            raise RuntimeError("Test server failed to start")

        # Store host and port (port is already known since we set it)
        self.host = "127.0.0.1"

        return ("127.0.0.1", self.port)

    def stop(self) -> None:
        """Stop the test server."""
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=2.0)
