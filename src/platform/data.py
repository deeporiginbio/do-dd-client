"""Data Platform API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

LIGAND_RETURNING_FIELDS = [
    "id",
    "version",
    "valid_from",
    "valid_to",
    "modified_by",
    "deleted",
    "mol_file",
    "project_id",
    "subtable_name",
    "canonical_smiles",
    "smiles",
    "inchi_key",
    "inchi",
    "name",
    "formal_charge",
    "hbond_donor_count",
    "hbond_acceptor_count",
    "rotatable_bond_count",
    "tpsa",
    "molecular_weight",
    "log_p",
    "structure_key",
]


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
        self._models: dict | None = None

    def health(self) -> dict:
        """Check the health status of the data platform.

        Returns:
            Dictionary containing the health status response.
        """
        return self._c.get_json("/data-platform/health")

    def list_models(self) -> dict:
        """List public models.

        The result is cached per instance.

        Returns:
            Dictionary containing the list of models.
        """
        if self._models is None:
            self._models = self._c.get_json(
                f"/data-platform/{self._c.org_key}/meta/models"
            )
        return self._models

    def search_ligands_with_results(
        self,
        *,
        cursor: str | None = None,
        experiments: list[dict[str, str]] | None = None,
        filter_dict: dict[str, Any] | None = None,
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
            filter_dict: Additional filter criteria as a dictionary.
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.
        """
        # Ensure deleted=False is always set in filter_dict
        if filter_dict is None:
            filter_dict = {"deleted": False}
        else:
            filter_dict = filter_dict.copy()
            filter_dict["deleted"] = False

        body: dict[str, Any] = {}
        if cursor is not None:
            body["cursor"] = cursor
        if experiments is not None:
            body["experiments"] = experiments
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
        filter_dict: dict[str, Any] | None = None,
        smiles: str | None = None,
        smiles_list: list[str] | None = None,
        canonical_smiles: str | None = None,
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
            filter_dict: Additional filter criteria as a dictionary.
            smiles: Filter by a single SMILES string (exact match).
            smiles_list: Filter by multiple SMILES strings. Uses an "in"
                filter on canonical_smiles. Mutually exclusive with smiles
                and canonical_smiles.
            canonical_smiles: Filter by canonical SMILES string.
            min_molecular_weight: Minimum molecular weight filter (inclusive).
            max_molecular_weight: Maximum molecular weight filter (inclusive).
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.

        Raises:
            ValueError: If smiles_list is used together with smiles or
                canonical_smiles, or if ligands is not a valid table name.
        """
        if smiles_list is not None and (
            smiles is not None or canonical_smiles is not None
        ):
            raise ValueError(
                "smiles_list is mutually exclusive with smiles and canonical_smiles"
            )

        filter_dict = filter_dict.copy() if filter_dict is not None else {}
        filter_dict.setdefault("deleted", False)

        if smiles is not None:
            filter_dict["smiles"] = smiles

        if canonical_smiles is not None:
            filter_dict["canonical_smiles"] = canonical_smiles

        props = []

        if smiles_list is not None:
            props.append(
                {
                    "column": "canonical_smiles",
                    "op": "in",
                    "value": smiles_list,
                }
            )

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

    def get_entity(self, *, entity: str, entity_id: str) -> dict:
        """Get an entity by ID.

        Args:
            entity: The entity type (e.g., "ligands", "proteins").
            entity_id: The ID of the entity to retrieve.

        Returns:
            Dictionary containing the entity data.
        """
        return self._c.get_json(
            f"/data-platform/{self._c.org_key}/{entity}/{entity_id}"
        )

    def get_ligand(self, id: str) -> dict:
        """Get a ligand by ID.

        Args:
            id: The ID of the ligand to retrieve.

        Returns:
            Dictionary containing the ligand data.
        """
        return self.get_entity(entity="ligands", entity_id=id)

    def get_ligands(self, ids: list[str]) -> list[dict]:
        """Get multiple ligands by their IDs.

        The data-platform search API does not support filtering by multiple
        IDs in a single request, so this method calls :meth:`get_ligand` for
        each ID.

        Args:
            ids: List of ligand IDs to retrieve.

        Returns:
            List of dictionaries, one per ligand.
        """
        return [self.get_ligand(id=lid) for lid in ids]

    def get_protein(self, id: str) -> dict:
        """Get a protein by ID.

        Args:
            id: The ID of the protein to retrieve.

        Returns:
            Dictionary containing the protein data.
        """
        return self.get_entity(entity="proteins", entity_id=id)

    def search_proteins(
        self,
        *,
        cursor: str | None = None,
        pdb_id: str | None = None,
        file_path: str | None = None,
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
            file_path: Filter by file path.
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
        if file_path is not None:
            filter_dict["file_path"] = file_path

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

    def create_ligand(
        self,
        *,
        smiles: str,
        project_id: str | None = None,
        name: str | None = None,
        mol_file: str | None = None,
        formal_charge: int = 0,
        hbond_donor_count: int | None = None,
        hbond_acceptor_count: int | None = None,
        rotatable_bond_count: int | None = None,
        tpsa: float | None = None,
        molecular_weight: float | None = None,
        variant_name_tag: str = "",
    ) -> dict:
        """Create a new ligand.

        Args:
            smiles: SMILES string (required).
            project_id: Project ID for the ligand.
            name: Name of the ligand.
            mol_file: Path to the molecule file (e.g., SDF file) in remote storage.
            formal_charge: Formal charge. Defaults to 0.
            hbond_donor_count: Number of hydrogen bond donors.
            hbond_acceptor_count: Number of hydrogen bond acceptors.
            rotatable_bond_count: Number of rotatable bonds.
            tpsa: Topological polar surface area.
            molecular_weight: Molecular weight.
            variant_name_tag: Variant name tag. Defaults to empty string.

        Returns:
            Dictionary containing the created ligand data.
        """
        # Build the set object with all ligand properties
        set_dict: dict[str, Any] = {
            "subtable_name": "ligands",
            "smiles": smiles,
            "formal_charge": formal_charge,
            "variant_name_tag": variant_name_tag,
        }

        # Add optional fields only if provided
        if project_id is not None:
            set_dict["project_id"] = project_id
        if name is not None:
            set_dict["name"] = name
        if mol_file is not None:
            set_dict["mol_file"] = mol_file
        if hbond_donor_count is not None:
            set_dict["hbond_donor_count"] = hbond_donor_count
        if hbond_acceptor_count is not None:
            set_dict["hbond_acceptor_count"] = hbond_acceptor_count
        if rotatable_bond_count is not None:
            set_dict["rotatable_bond_count"] = rotatable_bond_count
        if tpsa is not None:
            set_dict["tpsa"] = tpsa
        if molecular_weight is not None:
            set_dict["molecular_weight"] = molecular_weight

        body: dict[str, Any] = {
            "set": set_dict,
            "returning": LIGAND_RETURNING_FIELDS,
        }

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/ligands",
            body=body,
        )

    def batch_create_ligands(self, *, rows: list[dict[str, Any]]) -> dict:
        """Batch create ligands.

        Each row should contain at minimum a ``smiles`` key. Optional keys
        match the fields accepted by :meth:`create_ligand` (e.g. ``name``,
        ``formal_charge``, ``molecular_weight``, etc.).  The platform will
        compute ``canonical_smiles``, ``inchi``, and other derived fields.

        Args:
            rows: List of dicts, each describing one ligand to create.  Every
                dict must contain ``smiles`` (str).  All other keys are
                optional and mirror the ``set`` payload of ``create_ligand``.

        Returns:
            Dictionary containing the batch creation response with a ``data``
            list of created ligand records.
        """
        body: dict[str, Any] = {
            "rows": rows,
            "returning": LIGAND_RETURNING_FIELDS,
        }

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/ligands/batch/create",
            body=body,
        )

    def create_protein(
        self,
        *,
        file_path: str,
        gene_symbol: str | None = None,
        pdb_id: str | None = None,
        fasta_sequence: str | None = None,
        protein_name: str | None = None,
        protein_length: int | None = None,
        project_id: str | None = None,
    ) -> dict:
        """Create a new protein.

        Args:
            file_path: Path to the protein file (required).
            gene_symbol: Gene symbol.
            pdb_id: PDB ID.
            fasta_sequence: FASTA sequence.
            protein_name: Protein name.
            protein_length: Protein length.
            project_id: Project ID for the protein.

        Returns:
            Dictionary containing the created protein data.
        """
        # Build the set object with all protein properties
        set_dict: dict[str, Any] = {
            "file_path": file_path,
        }

        # Add optional fields only if provided
        if project_id is not None:
            set_dict["project_id"] = project_id
        if gene_symbol is not None:
            set_dict["gene_symbol"] = gene_symbol
        if pdb_id is not None:
            set_dict["pdb_id"] = pdb_id
        if fasta_sequence is not None:
            set_dict["fasta_sequence"] = fasta_sequence
        if protein_name is not None:
            set_dict["protein_name"] = protein_name
        if protein_length is not None:
            set_dict["protein_length"] = protein_length

        body: dict[str, Any] = {
            "set": set_dict,
            "returning": [
                "id",
                "version",
                "valid_from",
                "valid_to",
                "modified_by",
                "deleted",
                "project_id",
                "subtable_name",
                "uniprot_accession",
                "file_path",
                "gene_symbol",
                "pdb_id",
                "refseq_protein_id",
                "ensembl_protein_id",
                "alpha_fold_id",
                "fasta_sequence",
                "protein_name",
                "kegg_gene_id",
                "chembl_target_id",
                "binding_db_target_id",
                "drugbank_target_id",
                "pfam_id",
                "interpro_id",
                "ec_number",
                "ncbi_taxonomy_id",
                "protein_family",
                "ligandability_score",
                "protein_length",
            ],
        }

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/proteins",
            body=body,
        )

    def list_projects(self) -> dict:
        """List projects.

        Returns:
            Dictionary containing the list of projects.
        """
        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/projects/search",
            body={},
        )
