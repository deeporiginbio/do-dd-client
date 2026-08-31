"""Data Platform entity API wrapper (ligands, proteins, and generic entity search)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.platform.tags import merge_entity_tags, stamp_batch_row_tags
from deeporigin.utils.constants import (
    DEFAULT_SEARCH_PAGE_SIZE,
    ENTITY_SEARCH_TIMEOUT_SECONDS,
    LIGAND_MOLPROPS_SET_FIELDS,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def _writable_ligand_set_fields(set_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a ligand create/update ``set`` payload without molprops fields.

    Molecular descriptors such as ``molecular_weight`` and ``hbond_donor_count``
    are populated by the molprops tool on the platform, not on ligand create.
    """
    return {
        key: value
        for key, value in set_dict.items()
        if key not in LIGAND_MOLPROPS_SET_FIELDS
    }


# Minimal returning for proteins batch create (triggers require INSERT path, not COPY).
PROTEIN_BATCH_CREATE_RETURNING_FIELDS = ["id"]

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
    "structure_key",
    "tags",
]

PROTEIN_RETURNING_FIELDS = [
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
]


class Entities:
    """Data Platform entity API wrapper.

    Provides access to ligand, protein, and generic entity endpoints
    through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Entities wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client
        self._models: dict | None = None

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
            timeout=ENTITY_SEARCH_TIMEOUT_SECONDS,
        )

    def get(self, *, entity: str, entity_id: str) -> dict:
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

    def delete(self, *, entity: str, entity_id: str) -> dict:
        """Delete an entity by ID.

        Args:
            entity: The entity type (e.g., "ligands", "proteins").
            entity_id: The ID of the entity to delete.

        Returns:
            Dictionary containing the deletion result (e.g., ``{"deleted": 1}``).
        """
        return self._c.delete_json(
            f"/data-platform/{self._c.org_key}/{entity}/{entity_id}"
        )

    def batch_create(
        self,
        entity: str,
        *,
        rows: list[dict[str, Any]],
        returning: list[str] | None = None,
    ) -> dict:
        """Batch create entity rows.

        Calls ``POST /data-platform/{orgKey}/{entity}/batch/create``.

        This method is intentionally generic so tools can persist dataset rows
        into arbitrary target tables (e.g. result tables), not only the built-in
        convenience entities like ligands.

        Args:
            entity: Entity (table) name to batch-create.
            rows: List of row dicts to persist.
            returning: Optional list of fields to include in the response.
                For ``ligands`` and ``proteins``, defaults to an INSERT-safe
                returning list when omitted (avoids the platform COPY ingest path).

        Returns:
            Dictionary containing the batch creation response.
        """
        effective_returning = returning
        if effective_returning is None:
            if entity == "ligands":
                effective_returning = LIGAND_RETURNING_FIELDS
            elif entity == "proteins":
                effective_returning = PROTEIN_BATCH_CREATE_RETURNING_FIELDS

        body: dict[str, Any] = {"rows": stamp_batch_row_tags(self._c, rows)}
        if effective_returning is not None:
            body["returning"] = effective_returning

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/{entity}/batch/create",
            body=body,
        )

    def update(
        self,
        entity: str,
        entity_id: str,
        *,
        set_dict: dict[str, Any],
        returning: list[str] | None = None,
    ) -> dict:
        """Update an entity row by ID.

        Calls ``PATCH /data-platform/{orgKey}/{entity}/{id}``. Updates on
        immutable-versioned entities (ligands, proteins) create a new version
        row; the ID is stable.

        Args:
            entity: Entity (table) name to update.
            entity_id: Friendly or hex ID of the row to update.
            set_dict: Fields to set (snake_case keys).
            returning: Optional list of fields to include in the response.

        Returns:
            Parsed JSON body from the PATCH response. When ``returning`` is
            set, the payload includes updated row data under ``data``; the
            platform may also include ``meta`` (e.g. ``affected``).

        Raises:
            ValueError: If ``set_dict`` is empty.
        """
        if not set_dict:
            raise ValueError("set_dict must contain at least one field to update")

        body: dict[str, Any] = {"set": set_dict}
        if returning is not None:
            body["returning"] = returning

        return self._c._patch(
            f"/data-platform/{self._c.org_key}/{entity}/{entity_id}",
            json=body,
        ).json()

    def batch_update(
        self,
        entity: str,
        *,
        updates: list[dict[str, Any]],
        returning: list[str] | None = None,
    ) -> dict:
        """Batch update entity rows.

        Calls ``PATCH /data-platform/{orgKey}/{entity}/batch/update``. Each
        entry in ``updates`` must have ``id`` and ``set`` keys.

        Args:
            entity: Entity (table) name to update.
            updates: List of ``{"id": ..., "set": {...}}`` dicts.
            returning: Optional list of fields to include per updated row.

        Returns:
            Parsed JSON body from the batch PATCH response. Typically
            includes ``data`` (updated rows) and ``meta.affected`` when
            ``returning`` is set; shape matches the platform endpoint.

        Raises:
            ValueError: If ``updates`` is empty or any entry lacks ``id``/``set``.
        """
        if not updates:
            raise ValueError("updates must be a non-empty list")

        for i, entry in enumerate(updates):
            if "id" not in entry:
                raise ValueError(f"updates[{i}] must include 'id'")
            if not entry.get("set"):
                raise ValueError(f"updates[{i}]['set'] must contain at least one field")

        body: dict[str, Any] = {"updates": updates}
        if returning is not None:
            body["returning"] = returning

        return self._c._patch(
            f"/data-platform/{self._c.org_key}/{entity}/batch/update",
            json=body,
        ).json()

    # ---- Ligands ----

    def search_ligands(
        self,
        *,
        filter_dict: dict[str, Any] | None = None,
        smiles: str | None = None,
        smiles_list: list[str] | None = None,
        canonical_smiles: str | None = None,
        min_molecular_weight: float | int | None = None,
        max_molecular_weight: float | int | None = None,
        limit: int | None = 100,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Search ligands entity with automatic cursor-based pagination.

        Convenience method that calls search(entity="ligands") and iterates
        through all pages using cursor-based pagination, returning all matching
        records in a single response.

        Args:
            filter_dict: Additional filter criteria as a dictionary.
            smiles: Filter by a single SMILES string (exact match).
            smiles_list: Filter by multiple SMILES strings. Uses an "in"
                filter on canonical_smiles. Mutually exclusive with smiles
                and canonical_smiles.
            canonical_smiles: Filter by canonical SMILES string.
            min_molecular_weight: Minimum molecular weight filter (inclusive).
            max_molecular_weight: Maximum molecular weight filter (inclusive).
            limit: Maximum total number of results to return across all pages.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing all search results across pages, with ``data``
            holding the full list of records and ``meta`` from the final response.

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

        if smiles_list is not None and len(smiles_list) == 0:
            return {"data": [], "count": 0}

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

        all_data: list[dict[str, Any]] = []
        cursor: str | None = None
        is_first_page = True
        response: dict[str, Any] = {}

        if limit is not None:
            page_size = min(limit, DEFAULT_SEARCH_PAGE_SIZE)
        else:
            page_size = DEFAULT_SEARCH_PAGE_SIZE

        while True:
            response = self.search(
                "ligands",
                cursor=cursor,
                filter_dict=filter_dict,
                limit=page_size,
                offset=offset if is_first_page else None,
                select=select,
                sort=sort,
            )
            all_data.extend(response.get("data", []))
            is_first_page = False

            if limit is not None and len(all_data) >= limit:
                all_data = all_data[:limit]
                break

            cursor = response.get("meta", {}).get("nextCursor")
            if not cursor:
                break

        response["data"] = all_data
        return response

    def get_ligand(self, id: str) -> dict:
        """Get a ligand by ID.

        Args:
            id: The ID of the ligand to retrieve.

        Returns:
            Dictionary containing the ligand data.
        """
        return self.get(entity="ligands", entity_id=id)

    def get_ligands(self, ids: list[str]) -> list[dict]:
        """Get multiple ligands by their IDs in a single search request.

        Sends one ``POST /ligands/search`` with an ``{"id": {"in": ids}}``
        filter and ``limit = len(ids)``, bypassing :meth:`search_ligands` so
        no default pagination limit applies. The platform translates the
        ``id`` filter to the canonical-id column and decodes the string IDs
        to buffers server-side (see ``coerceCanonicalIdInFilter`` in
        data-platform-service).

        The filter includes ``deleted: false`` for parity with :meth:`search`.
        Non-current versions may still be excluded server-side depending on
        platform rules. Callers that need soft-deleted or historical rows
        should fall back to per-ID :meth:`get_ligand` calls.

        Args:
            ids: List of ligand IDs to retrieve.

        Returns:
            List of dictionaries for the matching ligands. Missing IDs are
            omitted; callers should diff returned IDs against ``ids`` when
            completeness matters.
        """
        if len(ids) == 0:
            return []

        unique_ids = list(dict.fromkeys(ids))

        response = self._c.post_json(
            f"/data-platform/{self._c.org_key}/ligands/search",
            body={
                "filter": {"id": {"in": unique_ids}, "deleted": False},
                "limit": len(unique_ids),
            },
        )
        return response.get("data", [])

    def create_ligand(
        self,
        *,
        smiles: str,
        project_id: str | None = None,
        name: str | None = None,
        mol_file: str | None = None,
        variant_name_tag: str = "",
        tags: dict[str, Any] | None = None,
        # Deprecated: these are now server-computed from SMILES and are ignored.
        molecular_weight: float | None = None,
        formal_charge: int | None = None,
        hbond_donor_count: int | None = None,
        hbond_acceptor_count: int | None = None,
        rotatable_bond_count: int | None = None,
        tpsa: float | None = None,
    ) -> dict:
        """Create a new ligand.

        Args:
            smiles: SMILES string (required).
            project_id: Project ID for the ligand.
            name: Name of the ligand.
            mol_file: Path to the molecule file (e.g., SDF file) in remote storage.
            variant_name_tag: Variant name tag. Defaults to empty string.
            tags: Data-platform metadata tags (jsonb object). Provenance
                ``app`` / ``session`` are merged from the client automatically.
            molecular_weight: Deprecated. Server-computed from SMILES; ignored.
            formal_charge: Deprecated. Server-computed from SMILES; ignored.
            hbond_donor_count: Deprecated. Server-computed from SMILES; ignored.
            hbond_acceptor_count: Deprecated. Server-computed from SMILES; ignored.
            rotatable_bond_count: Deprecated. Server-computed from SMILES; ignored.
            tpsa: Deprecated. Server-computed from SMILES; ignored.

        Returns:
            Dictionary containing the created ligand data.
        """
        set_dict: dict[str, Any] = {
            "subtable_name": "ligands",
            "smiles": smiles,
            "variant_name_tag": variant_name_tag,
        }

        if project_id is not None:
            set_dict["project_id"] = project_id
        if name is not None:
            set_dict["name"] = name
        if mol_file is not None:
            set_dict["mol_file"] = mol_file
        set_dict["tags"] = merge_entity_tags(self._c, tags, always=True)

        body: dict[str, Any] = {
            "set": _writable_ligand_set_fields(set_dict),
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
            "rows": [
                _writable_ligand_set_fields(row)
                for row in stamp_batch_row_tags(self._c, rows)
            ],
            "returning": LIGAND_RETURNING_FIELDS,
        }

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/ligands/batch/create",
            body=body,
        )

    def update_ligand(
        self,
        id: str,
        *,
        smiles: str | None = None,
        project_id: str | None = None,
        name: str | None = None,
        mol_file: str | None = None,
        variant_name_tag: str | None = None,
        tags: dict[str, Any] | None = None,
        # Deprecated: these are now server-computed from SMILES and are ignored.
        molecular_weight: float | None = None,
        formal_charge: int | None = None,
        hbond_donor_count: int | None = None,
        hbond_acceptor_count: int | None = None,
        rotatable_bond_count: int | None = None,
        tpsa: float | None = None,
    ) -> dict:
        """Update an existing ligand by ID.

        Creates a new immutable version row on the platform. Only non-``None``
        keyword arguments are sent in the ``set`` payload.

        Args:
            id: Ligand ID to update.
            smiles: Updated SMILES string.
            project_id: Project ID for the ligand.
            name: Name of the ligand.
            mol_file: Path to the molecule file in remote storage.
            variant_name_tag: Variant name tag.
            tags: Data-platform metadata tags (jsonb object). When provided,
                provenance ``app`` / ``session`` are merged from the client.
            molecular_weight: Deprecated. Server-computed from SMILES; ignored.
            formal_charge: Deprecated. Server-computed from SMILES; ignored.
            hbond_donor_count: Deprecated. Server-computed from SMILES; ignored.
            hbond_acceptor_count: Deprecated. Server-computed from SMILES; ignored.
            rotatable_bond_count: Deprecated. Server-computed from SMILES; ignored.
            tpsa: Deprecated. Server-computed from SMILES; ignored.

        Returns:
            Dictionary containing the updated ligand data.

        Raises:
            ValueError: If no fields are provided to update.
        """
        set_dict: dict[str, Any] = {}
        if smiles is not None:
            set_dict["smiles"] = smiles
        if project_id is not None:
            set_dict["project_id"] = project_id
        if name is not None:
            set_dict["name"] = name
        if mol_file is not None:
            set_dict["mol_file"] = mol_file
        if variant_name_tag is not None:
            set_dict["variant_name_tag"] = variant_name_tag
        merged_tags = merge_entity_tags(self._c, tags, always=False)
        if merged_tags is not None:
            set_dict["tags"] = merged_tags

        return self.update(
            "ligands",
            id,
            set_dict=_writable_ligand_set_fields(set_dict),
            returning=LIGAND_RETURNING_FIELDS,
        )

    # ---- Proteins ----

    def get_protein(self, id: str) -> dict:
        """Get a protein by ID.

        Args:
            id: The ID of the protein to retrieve.

        Returns:
            Dictionary containing the protein data.
        """
        return self.get(entity="proteins", entity_id=id)

    def search_proteins(
        self,
        *,
        cursor: str | None = None,
        pdb_id: str | None = None,
        file_path: str | None = None,
        project_id: str | None = None,
        min_molecular_weight: float | int | None = None,
        max_molecular_weight: float | int | None = None,
        sequence: str | None = None,
        limit: int | None = 100,
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
            project_id: Filter by data platform project id.
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
        if project_id is not None:
            filter_dict["project_id"] = project_id

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

    def create_protein(
        self,
        *,
        file_path: str,
        gene_symbol: str | None = None,
        pdb_id: str | None = None,
        uniprot_accession: str | None = None,
        fasta_sequence: str | None = None,
        protein_name: str | None = None,
        protein_length: int | None = None,
        project_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> dict:
        """Create a new protein.

        Args:
            file_path: Path to the protein file (required).
            gene_symbol: Gene symbol.
            pdb_id: PDB ID.
            uniprot_accession: UniProtKB accession.
            fasta_sequence: FASTA sequence.
            protein_name: Protein name.
            protein_length: Protein length.
            project_id: Project ID for the protein.
            tags: Data-platform metadata tags (jsonb object). When provided,
                provenance ``app`` / ``session`` are merged from the client.

        Returns:
            Dictionary containing the created protein data.
        """
        set_dict: dict[str, Any] = {
            "file_path": file_path,
        }

        if project_id is not None:
            set_dict["project_id"] = project_id
        if gene_symbol is not None:
            set_dict["gene_symbol"] = gene_symbol
        if pdb_id is not None:
            set_dict["pdb_id"] = pdb_id
        if uniprot_accession is not None:
            set_dict["uniprot_accession"] = uniprot_accession
        if fasta_sequence is not None:
            set_dict["fasta_sequence"] = fasta_sequence
        if protein_name is not None:
            set_dict["protein_name"] = protein_name
        if protein_length is not None:
            set_dict["protein_length"] = protein_length
        set_dict["tags"] = merge_entity_tags(self._c, tags, always=True)

        body: dict[str, Any] = {
            "set": set_dict,
            "returning": PROTEIN_RETURNING_FIELDS,
        }

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/proteins",
            body=body,
        )

    def update_protein(
        self,
        id: str,
        *,
        file_path: str | None = None,
        gene_symbol: str | None = None,
        pdb_id: str | None = None,
        uniprot_accession: str | None = None,
        fasta_sequence: str | None = None,
        protein_name: str | None = None,
        protein_length: int | None = None,
        project_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> dict:
        """Update an existing protein by ID.

        Creates a new immutable version row on the platform. Only non-``None``
        keyword arguments are sent in the ``set`` payload.

        Args:
            id: Protein ID to update.
            file_path: Path to the protein structure file in remote storage.
            gene_symbol: Gene symbol.
            pdb_id: PDB ID.
            uniprot_accession: UniProtKB accession.
            fasta_sequence: FASTA sequence.
            protein_name: Protein name.
            protein_length: Protein length.
            project_id: Project ID for the protein.
            tags: Data-platform metadata tags (jsonb object). When provided,
                provenance ``app`` / ``session`` are merged from the client.

        Returns:
            Dictionary containing the updated protein data.

        Raises:
            ValueError: If no fields are provided to update.
        """
        set_dict: dict[str, Any] = {}
        if file_path is not None:
            set_dict["file_path"] = file_path
        if project_id is not None:
            set_dict["project_id"] = project_id
        if gene_symbol is not None:
            set_dict["gene_symbol"] = gene_symbol
        if pdb_id is not None:
            set_dict["pdb_id"] = pdb_id
        if uniprot_accession is not None:
            set_dict["uniprot_accession"] = uniprot_accession
        if fasta_sequence is not None:
            set_dict["fasta_sequence"] = fasta_sequence
        if protein_name is not None:
            set_dict["protein_name"] = protein_name
        if protein_length is not None:
            set_dict["protein_length"] = protein_length
        merged_tags = merge_entity_tags(self._c, tags, always=False)
        if merged_tags is not None:
            set_dict["tags"] = merged_tags

        return self.update(
            "proteins",
            id,
            set_dict=set_dict,
            returning=PROTEIN_RETURNING_FIELDS,
        )
