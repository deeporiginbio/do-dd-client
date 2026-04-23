"""Synchronous protonation via ``functions.run`` (with optional local JSON cache)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.sync_function_responses import SyncFunctionResponses
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import number
from deeporigin.utils.env import _ensure_do_folder
from deeporigin.utils.hashing import hash_dict

_CACHE_DIR = str(_ensure_do_folder() / "protonation")
os.makedirs(_CACHE_DIR, exist_ok=True)


class Protonation(Execution, QuoteMixin, SyncExecutableMixin):
    """Run ligand protonation through the platform functions API (sync, with cache)."""

    tool_key: str = TOOL_KEYS_AND_VERSIONS["mol_props"]["protonation_function_key"]

    @beartype
    def __init__(
        self,
        *,
        smiles: str,
        ph: number = 7.4,
        filter_percentage: number = 1.0,
        use_cache: bool = True,
        client: DeepOriginClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._smiles = smiles
        self._ph = ph
        self._filter_percentage = float(filter_percentage)
        self._use_cache = use_cache
        self._responses: list[dict] = []

    @property
    def smiles(self) -> str:
        return self._smiles

    @property
    def ph(self) -> number:
        return self._ph

    def _payload(self) -> dict:
        return {
            "smiles": self._smiles,
            "pH": self._ph,
            "filter_percentage": self._filter_percentage,
        }

    def _cache_path(self) -> str:
        cache_hash = hash_dict(self._payload())
        return str(Path(_CACHE_DIR) / f"{cache_hash}.json")

    def _quote_impl(self) -> None:
        """Request a cost estimate without executing (no cache read/write)."""
        response = self.client.functions.run(
            key=TOOL_KEYS_AND_VERSIONS["mol_props"]["protonation_function_key"],
            version=TOOL_KEYS_AND_VERSIONS["mol_props"]["function_version"],
            params=self._payload(),
            quote=True,
        )
        self._apply_quote_response(response)

    def _apply_quote_response(self, response: dict) -> None:
        wrapped = SyncFunctionResponses([response])
        if wrapped.estimate is None:
            raise RuntimeError(
                "Quote failed: no estimate could be parsed from the protonation response."
            )
        self._estimate = wrapped.estimate
        self._responses = [response]

    @beartype
    def run(self) -> Protonation:
        """Execute protonation (uses cache when ``use_cache`` is True)."""
        payload = self._payload()
        response_file = self._cache_path()

        if os.path.exists(response_file) and self._use_cache:
            with open(response_file) as file:
                response = json.load(file)

            if "functionOutputs" not in response:
                response = {"functionOutputs": response, "status": "Completed"}
        else:
            response = self.client.functions.run(
                key=TOOL_KEYS_AND_VERSIONS["mol_props"]["protonation_function_key"],
                version=TOOL_KEYS_AND_VERSIONS["mol_props"]["function_version"],
                params=payload,
                quote=False,
            )

            outputs = response.get("functionOutputs", {})
            if outputs.get("pH") != self._ph:
                raise ValueError(
                    f"Protonation failed. Expected pH {self._ph}, got {outputs.get('pH')}"
                )

            Path(response_file).parent.mkdir(parents=True, exist_ok=True)
            with open(response_file, "w") as file:
                json.dump(response, file)

        self._responses = [response]
        wrapped = SyncFunctionResponses(self._responses)
        if wrapped.cost is not None:
            self._cost = wrapped.cost
        exec_id = response.get("id")
        if exec_id is not None:
            self._id = exec_id
        return self

    @property
    def responses(self) -> list[dict]:
        """Raw API responses (one dict after ``run`` or ``quote``)."""
        return self._responses

    @property
    def function_outputs(self) -> list[dict]:
        return SyncFunctionResponses(self._responses).function_outputs
