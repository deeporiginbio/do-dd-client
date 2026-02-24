"""Local test server that mimics the DeepOrigin Platform API.

This server runs locally during tests to provide mock responses for all
API endpoints used by the DeepOriginClient.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any

from fastapi import FastAPI
import uvicorn

from .routers import billing, data_platform, entities, files, tools


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
            docking_speed: Number of dockings to simulate per second for bulk-docking
                executions. Default is 1.0.
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
        # Tool-specific mock execution durations (in seconds)
        self._mock_execution_durations: dict[str, float] = {
            "deeporigin.abfe-end-to-end": 30.0,  # seconds
        }
        self.docking_speed = docking_speed
        self._load_execution_fixtures()
        self._load_ligand_fixtures()
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
        3. ``tests/fixtures/42-ligands.sdf``
        4. ``tests/fixtures/brd-7.sdf``
        5. ``tests/fixtures/ligand_*.json``

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

        def _ingest_mol(mol: Chem.Mol) -> None:
            """Convert an RDKit Mol into a ligand record and store it."""
            canonical = Chem.MolToSmiles(mol)
            if canonical in seen_smiles:
                return
            seen_smiles.add(canonical)

            name = mol.GetProp("_Name") if mol.HasProp("_Name") else "Unknown"
            ligand_id = self._make_ligand_id(canonical)

            self._ligands[ligand_id] = {
                "id": ligand_id,
                "version": 1,
                "valid_from": now_ts,
                "valid_to": None,
                "modified_by": "mock-server",
                "deleted": False,
                "project_id": None,
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

        def _ingest_sdf(path: Path) -> None:
            """Parse all molecules from an SDF file."""
            supplier = Chem.SDMolSupplier(str(path), removeHs=True)
            for mol in supplier:
                if mol is None:
                    continue
                try:
                    _ingest_mol(mol)
                except Exception:
                    continue

        brd_dir = Path(__file__).parent.parent.parent / "src" / "data" / "brd"
        if brd_dir.exists():
            for sdf_file in sorted(brd_dir.glob("*.sdf")):
                _ingest_sdf(sdf_file)

        for sdf_name in ("ligands-brd-all.sdf", "42-ligands.sdf", "brd-7.sdf"):
            sdf_path = self._fixtures_dir / sdf_name
            if sdf_path.exists():
                _ingest_sdf(sdf_path)

        for json_path in sorted(self._fixtures_dir.glob("ligand_*.json")):
            with open(json_path) as f:
                data: dict[str, Any] = json.load(f)
            canonical = data.get("canonical_smiles", "")
            if canonical and canonical not in seen_smiles:
                seen_smiles.add(canonical)
                self._ligands[data["id"]] = data

    def _setup_routes(self) -> None:
        """Set up all API routes."""
        # Include file-related routes
        files_router = files.create_files_router(self._file_storage, self._fixtures_dir)
        self.app.include_router(files_router)

        # Include data-platform routes
        dp_router = data_platform.create_data_platform_router(
            ligands=self._ligands,
            proteins=self._proteins,
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
