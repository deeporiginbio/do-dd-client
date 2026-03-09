"""This module encapsulates methods to run docking and show docking results on Deep Origin"""

import concurrent.futures
import logging
import math
import os
from typing import Literal, Optional

from beartype import beartype
from deeporigin_molstar import JupyterViewer
import more_itertools
import numpy as np
import pandas as pd
from tqdm import tqdm

from deeporigin.drug_discovery import LigandSet, utils
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.workflow_step import WorkflowStep
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import (
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
    NON_FAILED_STATES,
)
from deeporigin.platform.job import Job, JobList
from deeporigin.utils.env import _ensure_do_folder

logger = logging.getLogger(__name__)

Number = float | int
LOCAL_BASE = _ensure_do_folder()


class Docking(WorkflowStep):
    """class to handle Docking-related tasks within the Complex class.

    Objects instantiated here are meant to be used within the Complex class."""

    """tool version to use for Docking"""
    tool_version = DOCKING_TOOL_VERSION
    _tool_key = DOCKING_TOOL_KEY

    def __init__(self, parent):
        super().__init__(parent)
        self._fuse_jobs = True

    def show_results(self):
        """show results of bulk Docking run in a table, rendering 2D structures of molecules"""

        df = self.get_results()

        if (df is None) or (len(df) == 0):
            # no results available yet
            return

        from IPython.display import HTML, display
        from rdkit.Chem import PandasTools

        PandasTools.AddMoleculeColumnToFrame(df, smilesCol="SMILES", molCol="Structure")
        PandasTools.RenderImagesInAllDataFrames()

        df.drop("SMILES", axis=1, inplace=True)

        # Reorder columns to put Structure first
        cols = df.columns.tolist()
        cols.remove("Structure")
        df = df[["Structure"] + cols]

        display(HTML(df.to_html(escape=False)))

    def show_poses(self):
        """show docked ligands with protein in 3D"""

        file_paths = self.get_results(file_type="sdf")

        if file_paths is None:
            # no results available yet
            return

        from deeporigin_molstar.src.viewers import DockingViewer

        docking_viewer = DockingViewer()
        html_content = docking_viewer.render_with_separate_crystal(
            protein_data=str(self.parent.protein.file_path),
            protein_format="pdb",
            ligands_data=file_paths,
            ligand_format="sdf",
            paginate=True,
        )
        JupyterViewer.visualize(html_content)

    def get_poses(self, *, include_legacy_results: bool = True) -> LigandSet | None:
        """Get all docked poses as a ``LigandSet``.

        Tries :meth:`get_results_using_id` first (result-explorer API), then
        optionally includes results from the legacy :meth:`get_results`
        directory listing. SDF paths from both sources are merged and
        deduplicated before loading.

        Args:
            include_legacy_results: If True, also fetch results via the legacy
                directory-listing method and merge them. Defaults to True.

        Returns:
            A LigandSet of docked poses, or None if no results are available.
        """
        remote_paths: list[str] = []
        try:
            df = self.get_results_using_id()
            if df is not None:
                remote_paths = df["file_path"].dropna().unique().tolist()
        except DeepOriginException:
            logger.debug(
                "Result-explorer lookup failed; falling back to legacy results"
            )

        id_local_paths: list[str] = []
        if remote_paths:
            id_local_paths = self.parent.client.files.download_files(
                files=remote_paths,
                lazy=True,
            )

        legacy_paths: list[str] = []
        if include_legacy_results:
            legacy_paths = self.get_results(file_type="sdf") or []

        all_paths = list(dict.fromkeys(id_local_paths + legacy_paths))

        if len(all_paths) == 0:
            return None

        ligands = LigandSet()
        for file in all_paths:
            ligands.ligands += LigandSet.from_sdf(file).ligands

        smiles_in_complex = self.parent.ligands.to_smiles()

        ligands.ligands = [
            ligand for ligand in ligands if ligand.smiles in smiles_in_complex
        ]

        return ligands

    @beartype
    def get_results(
        self,
        *,
        file_type: Literal["csv", "sdf"] = "csv",
    ) -> pd.DataFrame | None | list[str]:
        """return a list of paths to CSV and SDF files that contain the results from docking

        Args:
            file_type (str): "csv" or "sdf". Defaults to "csv".

        Returns:
            pd.DataFrame | None | list[str]: DataFrame of results, None if no results found, or list of file paths.
        """

        files = self.parent.client.files.list_files_in_dir(
            remote_path="tool-runs/docking/" + self.parent.protein.to_hash() + "/",
        )

        if file_type == "csv":
            results_files = [file for file in files if file.endswith("/results.csv")]
        elif file_type == "sdf":
            results_files = [file for file in files if file.endswith(".sdf")]
            results_files = [
                file for file in results_files if not file.endswith("top_results.sdf")
            ]  # exclude this for now, we'll filter client side

        if len(results_files) == 0:
            print("No Docking results found for this protein.")
            return None

        # Convert list to dict where each file path is a key with None as value
        results_files_dict = dict.fromkeys(results_files)

        self.parent.client.files.download_files(
            files=results_files_dict,
        )

        all_df = []

        deeporigin_base = _ensure_do_folder()

        local_paths = [str(deeporigin_base / file) for file in results_files]

        if file_type == "csv":
            for local_path in local_paths:
                from deeporigin.utils.filesystem import fix_embedded_newlines_in_csv

                fix_embedded_newlines_in_csv(local_path)

                df = pd.read_csv(local_path)
                all_df.append(df)

            df = pd.concat(all_df, ignore_index=True)
            return df
        else:
            return local_paths

    @beartype
    def get_results_using_id(
        self,
    ) -> pd.DataFrame | None:
        """Retrieve docking results as a flat DataFrame via the result-explorer API.

        Queries the result-explorer endpoint filtered by protein ID and tool ID,
        then flattens nested ``data`` fields into a single tabular structure.

        Returns:
            DataFrame with columns ``id``, ``tool_id``, ``tool_version``,
            ``ligand_id``, ``protein_id``, ``binding_energy``, ``pose_score``,
            and ``file_path``. Returns None if no results were found.

        Raises:
            DeepOriginException: If the protein has no ID.
        """
        protein_id = self.parent.protein.id
        if protein_id is None:
            raise DeepOriginException(
                title="Protein has no ID",
                message="Cannot fetch results by ID because the protein has not been synced.",
                fix="Call <code>protein.sync(client=client)</code> first, or use <code>get_results()</code> instead.",
            )

        response = self.parent.client.results.get_poses(
            protein_id=protein_id,
        )

        records = response.get("data", [])
        if len(records) == 0:
            print("No docking results found for this protein.")
            return None

        rows = []
        for record in records:
            data = record.get("data", {})
            rows.append(
                {
                    "id": record.get("id"),
                    "tool_id": record.get("tool_id"),
                    "tool_version": record.get("tool_version"),
                    "ligand_id": data.get("ligand_id"),
                    "protein_id": data.get("protein_id"),
                    "binding_energy": data.get("binding_energy"),
                    "pose_score": data.get("pose_score"),
                    "file_path": data.get("file_path"),
                }
            )

        return pd.DataFrame(rows)

    @beartype
    def get_jobs_df(
        self,
        *,
        pocket_center: Optional[tuple[Number, Number, Number] | list[Number]] = None,
        box_size: Optional[tuple[Number, Number, Number] | list[Number]] = None,
    ):
        """search for all jobs that match this protein and ligands in the Job DB, and return a dataframe of the results

        Args:
            pocket_center: Optional tuple of (x, y, z) coordinates to filter by pocket center
            box_size: Optional tuple of (x, y, z) dimensions to filter by box size
        """
        # Use parent method with docking-specific parameters
        df = super().get_jobs_df(
            include_metadata=True,
            include_inputs=True,
            include_outputs=True,
            status=list(NON_FAILED_STATES),
        )

        if len(df) == 0:
            return df

        # Apply docking-specific filters
        if pocket_center is not None:
            mask = df["user_inputs"].apply(
                lambda x: isinstance(x, dict)
                and "pocket_center" in x
                and bool(np.all(np.isclose(pocket_center, x["pocket_center"])))
            )
            df = df[mask]

        if box_size is not None:
            mask = df["user_inputs"].apply(
                lambda x: isinstance(x, dict)
                and "box_size" in x
                and bool(np.all(np.isclose(box_size, x["box_size"])))
            )
            df = df[mask]

        # Filter by ligands - only keep jobs where at least one ligand matches
        if "user_inputs" in df.columns and len(df) > 0:
            smiles_strings = [ligand.smiles for ligand in self.parent.ligands]
            mask = df["user_inputs"].apply(
                lambda x: isinstance(x, dict)
                and (
                    # Handle old format (smiles_list)
                    (
                        "smiles_list" in x
                        and any(s in smiles_strings for s in x["smiles_list"])
                    )
                    # Handle new format (ligands array)
                    or (
                        "ligands" in x
                        and isinstance(x["ligands"], list)
                        and any(
                            ligand.get("smiles", "") in smiles_strings
                            for ligand in x["ligands"]
                        )
                    )
                )
            )
            df = df[mask]

        return df

    @beartype
    def run(
        self,
        *,
        pocket: Optional[Pocket] = None,
        box_size: Optional[tuple[Number, Number, Number]] = None,
        pocket_center: Optional[tuple[Number, Number, Number]] = None,
        batch_size: Optional[int] = 32,
        n_workers: Optional[int] = None,
        output_dir_path: Optional[str] = None,
        use_parallel: bool = True,
        approve_amount: Optional[int] = None,
        quote: bool = False,
        re_run: bool = False,
    ) -> JobList | None:
        """Run bulk docking on Deep Origin. Ligands will be split into batches based on the batch_size argument, and will run in parallel on Deep Origin clusters.

        Args:
            pocket (Pocket): pocket object. This can be generated using the pocket finder function.
            box_size (tuple[float, float, float]): box size
            pocket_center (tuple[float, float, float]): pocket center
            batch_size (int, optional): batch size. Defaults to 30.
            n_workers (int, optional): number of workers. Defaults to None.
            output_dir_path (str, optional): path to output directory. Defaults to None.
            use_parallel (bool, optional): whether to run jobs in parallel. Defaults to True.
            approve_amount (int, optional): amount to approve for the jobs. Defaults to None.
            quote (bool, optional): whether to request a quote for the jobs. Defaults to False.
            re_run (bool, optional): whether to re-run jobs. Defaults to False.

        Returns:
            JobList: A JobList containing all the created docking jobs.
        """

        if quote:
            approve_amount = 0
            re_run = True  # if we want a quote, it's irrelevant whether this has already been run or not

        if pocket is None and box_size is None and pocket_center is None:
            raise DeepOriginException(
                title="Cannot run Docking: no pocket specified",
                message="Specify a pocket, or a box size and pocket center.",
                fix="Use the pocket finder function to find a pocket, or specify a box size and pocket center.",
                level="danger",
            ) from None

        protein_basename = os.path.basename(self.parent.protein.file_path)

        if output_dir_path is None:
            output_dir_path = "tool-runs/docking/" + self.parent.protein.to_hash() + "/"

        # Sync protein and ligands to ensure they have IDs
        self.parent.protein.sync(client=self.parent.client)
        self.parent.ligands.sync(client=self.parent.client)

        metadata = {
            "protein_file": protein_basename,
            "protein_hash": self.parent.protein.to_hash(),
        }

        if batch_size is None and n_workers is None:
            raise DeepOriginException(
                "Either batch_size or n_workers must be specified."
            ) from None
        elif batch_size is not None and n_workers is not None:
            print(
                "Both batch_size and n_workers are specified. Using n_workers to determine batch_size..."
            )

        if n_workers is not None:
            batch_size = math.ceil(len(self.parent.ligands) / n_workers)
            print(f"Using a batch size of {batch_size}")

        if pocket is not None:
            box_size = float(2 * np.cbrt(pocket.volume))
            box_size = [box_size, box_size, box_size]
            pocket_center = pocket.get_center().tolist()

        # Get all ligands and filter out already docked ones
        all_ligands = list(self.parent.ligands)

        df = self.get_jobs_df(pocket_center=pocket_center, box_size=box_size)

        already_docked_smiles = set()

        if not re_run:
            for _, row in df.iterrows():
                user_inputs = row.get("user_inputs", {})
                # Handle both old format (smiles_list) and new format (ligands array)
                if "smiles_list" in user_inputs:
                    already_docked_smiles.update(user_inputs["smiles_list"])
                elif "ligands" in user_inputs:
                    already_docked_smiles.update(
                        ligand.get("smiles", "") for ligand in user_inputs["ligands"]
                    )

        # Filter ligands to only include those not already docked
        ligands_to_dock = [
            ligand
            for ligand in all_ligands
            if ligand.smiles not in already_docked_smiles
        ]

        # Sort ligands by SMILES for consistent batching
        ligands_to_dock = sorted(ligands_to_dock, key=lambda ligand: ligand.smiles)

        job_ids = []

        chunks = list(more_itertools.chunked(ligands_to_dock, batch_size))

        def process_chunk(chunk):
            params = {
                "box_size": list(box_size),
                "pocket_center": list(pocket_center),
                "protein": {
                    "file_path": self.parent.protein._remote_path,
                },
                "ligands": [
                    {
                        "smiles": ligand.smiles,
                    }
                    for ligand in chunk
                ],
            }

            # Include protein ID if available
            if self.parent.protein.id is not None:
                params["protein"]["id"] = self.parent.protein.id

            # Include ligand IDs if available
            for i, ligand in enumerate(chunk):
                if ligand.id is not None:
                    params["ligands"][i]["id"] = ligand.id

            # Include pocket_id if pocket is provided and has an ID
            if pocket is not None and hasattr(pocket, "id") and pocket.id is not None:
                params["pocket_id"] = pocket.id

            execution_dto = utils._start_tool_run(
                params=params,
                metadata=metadata,
                tool="Docking",
                tool_version=self.tool_version,
                client=self.parent.client,
                approve_amount=approve_amount,
            )
            return execution_dto

        if len(ligands_to_dock) > 0:
            if use_parallel:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # Submit all chunks to the executor
                    future_to_chunk = {
                        executor.submit(process_chunk, chunk): chunk for chunk in chunks
                    }

                    # Process results with progress bar
                    for future in tqdm(
                        concurrent.futures.as_completed(future_to_chunk),
                        total=len(chunks),
                        desc="Starting docking jobs",
                    ):
                        execution_dto = future.result()
                        if execution_dto is not None:
                            job_ids.append(execution_dto)
            else:
                for chunk in tqdm(
                    chunks, total=len(chunks), desc="Starting docking jobs"
                ):
                    execution_dto = process_chunk(chunk)
                    if execution_dto is not None:
                        job_ids.append(execution_dto)
        else:
            raise DeepOriginException(
                title="Cannot run Docking: no new ligands to dock",
                message="No new ligands to dock. All ligands have already been docked.",
                fix=" If you want to re-run the docking, set <code>re_run=True</code>.",
                level="warning",
            ) from None

        jobs = [
            Job.from_dto(execution_dto, client=self.parent.client)
            for execution_dto in job_ids
        ]

        self.jobs = JobList(jobs)

        return self.jobs
