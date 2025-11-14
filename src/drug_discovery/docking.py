"""This module encapsulates methods to run docking and show docking results on Deep Origin"""

import concurrent.futures
import math
import os
from pathlib import Path
from typing import Literal, Optional

from beartype import beartype
from deeporigin_molstar import JupyterViewer
import more_itertools
import numpy as np
import pandas as pd
from tqdm import tqdm

from deeporigin.drug_discovery import LigandSet, utils
from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.workflow_step import WorkflowStep
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import NON_FAILED_STATES
from deeporigin.platform.job import Job, get_dataframe

Number = float | int
LOCAL_BASE = Path.home() / ".deeporigin"


class Docking(WorkflowStep):
    """class to handle Docking-related tasks within the Complex class.

    Objects instantiated here are meant to be used within the Complex class."""

    """tool version to use for Docking"""
    tool_version = "0.4.6"
    _tool_key = tool_mapper["Docking"]

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
        html_content = docking_viewer.render_with_seperate_crystal(
            protein_data=str(self.parent.protein.file_path),
            protein_format="pdb",
            ligands_data=file_paths,
            ligand_format="sdf",
            paginate=True,
        )
        JupyterViewer.visualize(html_content)

    def get_poses(self) -> LigandSet | None:
        """get all docked poses as a `LigandSet`"""

        file_paths = self.get_results(file_type="sdf")

        if file_paths is None:
            # no results available yet
            return
        ligands = LigandSet()
        for file in file_paths:
            ligands.ligands += LigandSet.from_sdf(file).ligands

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
            file_path="tool-runs/docking/" + self.parent.protein.to_hash() + "/",
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
        results_files_dict = {file: None for file in results_files}

        self.parent.client.files.download_files(
            files=results_files_dict,
        )

        all_df = []

        home_dir = os.path.expanduser("~")

        local_paths = [
            os.path.join(home_dir, ".deeporigin", file) for file in results_files
        ]

        if file_type == "csv":
            for local_path in local_paths:
                from deeporigin.utils.core import fix_embedded_newlines_in_csv

                fix_embedded_newlines_in_csv(local_path)

                df = pd.read_csv(local_path)
                all_df.append(df)

            df = pd.concat(all_df, ignore_index=True)
            return df
        else:
            return local_paths

    @beartype
    def _get_jobs(
        self,
        *,
        pocket_center=None,
        box_size=None,
    ):
        """search for all jobs that match this protein and ligands in the Job DB, and return a dataframe of the results"""

        df = get_dataframe(
            tool_key=tool_mapper["Docking"],
            only_with_status=NON_FAILED_STATES,
            include_metadata=True,
            include_inputs=True,
            include_outputs=True,
            client=self.parent.client,
        )

        if pocket_center is not None and len(df) > 0:
            # Filter df rows where pocket_center matches row["user_inputs"]["pocket_center"]
            mask = df["user_inputs"].apply(
                lambda x: bool(np.all(np.isclose(pocket_center, x["pocket_center"])))
            )
            df = df[mask]

        if box_size is not None and len(df) > 0:
            # Filter df rows where box_size matches row["user_inputs"]["box_size"]
            mask = df["user_inputs"].apply(
                lambda x: bool(np.all(np.isclose(box_size, x["box_size"])))
            )
            df = df[mask]

        # filter to only keep jobs that match this protein.
        if "metadata" in df.columns and len(df) > 0:
            # first, drop rows where metadata has no protein_hash key
            has_protein_hash = df["metadata"].apply(
                lambda x: isinstance(x, dict) and ("protein_hash" in x)
            )
            df = df[has_protein_hash]

            # then, keep only rows matching this protein hash
            mask = df["metadata"].apply(
                lambda x: x["protein_hash"] == self.parent.protein.to_hash()
            )
            df = df[mask]

        if "user_inputs" in df.columns and len(df) > 0:
            # only keep jobs where at least one ligand in that job matches what we have in the current complex
            smiles_strings = [ligand.smiles for ligand in self.parent.ligands]
            mask = df["user_inputs"].apply(
                lambda x: any(s in smiles_strings for s in x["smiles_list"])
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
    ):
        """Run bulk docking on Deep Origin. Ligands will be split into batches based on the batch_size argument, and will run in parallel on Deep Origin clusters.

        Args:
            box_size (tuple[float, float, float]): box size
            pocket_center (tuple[float, float, float]): pocket center
            batch_size (int, optional): batch size. Defaults to 30.
            n_workers (int, optional): number of workers. Defaults to None.
            use_parallel (bool, optional): whether to run jobs in parallel. Defaults to True.
            re_run (bool, optional): whether to re-run jobs. Defaults to False.
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

        self.parent._sync_protein_and_ligands()

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
            box_size = float(2 * np.cbrt(pocket.props["volume"]))
            box_size = [box_size, box_size, box_size]
            pocket_center = pocket.get_center().tolist()

        smiles_strings = [ligand.smiles for ligand in self.parent.ligands]

        df = self._get_jobs(pocket_center=pocket_center, box_size=box_size)

        already_docked_ligands = []

        if not re_run:
            for _, row in df.iterrows():
                this_smiles = row["user_inputs"]["smiles_list"]
                already_docked_ligands.extend(this_smiles)

        smiles_strings = set(smiles_strings) - set(already_docked_ligands)
        smiles_strings = sorted(smiles_strings)

        job_ids = []

        chunks = list(more_itertools.chunked(smiles_strings, batch_size))

        def process_chunk(chunk):
            params = dict(
                box_size=list(box_size),
                pocket_center=list(pocket_center),
                smiles_list=chunk,
            )

            params["protein"] = {
                "$provider": "ufa",
                "key": self.parent.protein._remote_path,
            }

            execution_dto = utils._start_tool_run(
                params=params,
                metadata=metadata,
                tool="Docking",
                tool_version=self.tool_version,
                client=self.parent.client,
                output_dir_path=output_dir_path,
                approve_amount=approve_amount,
            )
            return execution_dto

        if len(smiles_strings) > 0:
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

        self.jobs = [
            Job.from_dto(execution_dto, client=self.parent.client)
            for execution_dto in job_ids
        ]

        return self.jobs
