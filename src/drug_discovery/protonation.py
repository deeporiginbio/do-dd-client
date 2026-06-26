"""Synchronous ligand protonation via ``client.executions.create``."""

from __future__ import annotations

from typing import Any

from beartype import beartype
from rdkit import Chem

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import number


def _execution_outputs_dict(dto: dict) -> dict[str, Any]:
    """Return ``jobOutputs`` from a protonation execution DTO as a dict.

    The protonation tool returns a single dict in ``jobOutputs`` with keys
    ``smiles``, ``pH``, ``filter_percentage``, and ``protonation_states``.
    """
    jo = dto.get("jobOutputs")
    if isinstance(jo, dict):
        return jo
    if isinstance(jo, list) and jo and isinstance(jo[0], dict):
        return jo[0]
    return {}


class Protonation(Execution, SyncExecutableMixin):
    """Run ligand protonation through the platform tools API (sync)."""

    tool_key: str = TOOL_KEYS_AND_VERSIONS["protonation"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["protonation"]["tool_version"]
    ligands: LigandSet

    @beartype
    def __init__(
        self,
        *,
        smiles: str | None = None,
        ligand: Ligand | None = None,
        ligands: LigandSet | None = None,
        ph: number = 7.4,
        filter_percentage: number = 1.0,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a protonation job from exactly one of ``smiles``, ``ligand``, or ``ligands``.

        Each form is normalized to :attr:`ligands` as a :class:`LigandSet` with exactly
        one :class:`Ligand` before calling the executions API.
        """
        provided = sum(x is not None for x in (smiles, ligand, ligands))
        if provided != 1:
            raise ValueError(
                "Exactly one of smiles, ligand, or ligands must be provided."
            )

        if ligand is not None:
            self.ligands = LigandSet(ligands=[ligand])
            self._merge_first_state_into_primary = True
        elif ligands is not None:
            if len(ligands) != 1:
                raise ValueError(
                    "Protonation accepts a single ligand; pass ligand= or a "
                    "LigandSet with exactly one ligand."
                )
            self.ligands = ligands
            self._merge_first_state_into_primary = True
        else:
            assert smiles is not None
            self.ligands = LigandSet(ligands=[Ligand.from_smiles(smiles)])
            self._merge_first_state_into_primary = False

        first = self.ligands.ligands[0]
        if not first.smiles:
            raise ValueError("A non-empty SMILES string is required for protonation.")

        self._input_smiles = first.smiles

        super().__init__(client=client)
        self._ph = ph
        self._filter_percentage = float(filter_percentage)
        self._responses: list[dict] = []

    @property
    def smiles(self) -> str:
        """SMILES of the input ligand (fixed at construction)."""
        return self._input_smiles

    @property
    def ph(self) -> number:
        return self._ph

    def _make_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` matching the protonation tool input schema."""
        primary = self.ligands.ligands[0]
        ligand_payload: dict[str, Any] = {"smiles": self._input_smiles}
        if primary.id is not None:
            ligand_payload["id"] = primary.id
        return {
            "ligand": ligand_payload,
            "pH": self._ph,
            "filter_percentage": self._filter_percentage,
        }

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._make_inputs(),
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
        tag: str | None = None,
        billing: str | None = None,
    ) -> Any:
        """Execute protonation via the platform tools API.

        Pass ``quote=True`` (or ``approve_amount=0``) to request a cost estimate
        only. In that case the platform returns a ``Quoted`` DTO, the instance
        is updated with ``estimate`` and ``status="Quoted"``, and ``None`` is
        returned.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            :class:`~deeporigin.drug_discovery.structures.ligand.LigandSet` whose
            ``ligands`` are the filtered protonation species (most abundant first).
            When the job was constructed with ``ligand=`` or ``ligands=``, the
            first entry is that input :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`
            updated in place to the primary species; further entries are new
            ``Ligand`` instances for other states. With ``smiles=`` only, every
            species is a new ``Ligand`` instance.
        """
        input_first = self.ligands.ligands[0]
        resolved_amount = 0 if quote else approve_amount

        with self._execution_tags(tag=tag, billing=billing):
            response = self._create_execution(
                data=self._make_payload(approve_amount=resolved_amount, sync=True),
            )

        outputs = _execution_outputs_dict(response)
        if outputs.get("pH") != self._ph:
            raise ValueError(
                f"Protonation failed. Expected pH {self._ph}, got {outputs.get('pH')}"
            )

        self._responses = [response]
        cost = Execution._quotation_total(response)
        if cost is not None and cost > 0:
            self._cost = cost
        exec_id = response.get("executionId") or response.get("id")
        if exec_id is not None:
            self._id = exec_id

        states = outputs.get("protonation_states") or {}
        smiles_list = states.get("smiles_list") or []
        if not smiles_list:
            raise ValueError(
                "Protonation response missing protonation_states.smiles_list"
            )

        base_name = input_first.name or ""
        ligands_out: list[Ligand] = []
        n_states = len(smiles_list)
        for i, smi in enumerate(smiles_list):
            if i == 0 and self._merge_first_state_into_primary:
                inp = input_first
                new_mol = Chem.MolFromSmiles(smi)
                if new_mol is None:
                    raise ValueError(f"Invalid protonated SMILES from API: {smi!r}")
                inp.mol = new_mol
                inp.smiles = smi
                inp.protonated_at_ph = float(self._ph)
                ligands_out.append(inp)
                continue
            if n_states == 1:
                nm = base_name
            elif base_name:
                nm = f"{base_name} ({i + 1})"
            else:
                nm = f"state_{i + 1}"
            child = Ligand.from_smiles(smi, name=nm)
            child.protonated_at_ph = float(self._ph)
            ligands_out.append(child)

        result = LigandSet(ligands=ligands_out)
        self.ligands = result
        return result

    @property
    def responses(self) -> list[dict]:
        """Raw API responses (one dict after ``run`` or ``quote``)."""
        return self._responses
