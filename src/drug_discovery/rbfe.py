"""This module encapsulates methods to run RBFE and show RBFE results on Deep Origin.

The RBFE object instantiated here is contained in the Complex class is meant to be used within that class."""

import os
from pathlib import Path
from typing import Optional

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery import utils
from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.workflow_step import WorkflowStep
from deeporigin.exceptions import DeepOriginException
from deeporigin.tools.job import Job
from deeporigin.utils.core import PrettyDict
from deeporigin.utils.notebook import get_notebook_environment

LOCAL_BASE = Path.home() / ".deeporigin"


class RBFE(WorkflowStep):
    """class to handle RBFE-related tasks within the Complex class.

    Objects instantiated here are meant to be used within the Complex class."""

    """tool version to use for RBFE"""
    tool_version = "0.2.8"
    _tool_key = tool_mapper["RBFE"]

    _max_atom_count: int = 100_000

    def __init__(self, parent):
        super().__init__(parent)
        self._params = PrettyDict()
        self._params.end_to_end = utils._load_params("rbfe_end_to_end")

    def get_results(self) -> pd.DataFrame | None:
        """get RBFE results and return in a dataframe.

        This method returns a dataframe showing the results of RBFE runs associated with this simulation session. The ligand file name and ΔG are shown, together with user-supplied properties"""

        files = utils.find_files_on_ufa(
            tool="RBFE",
            protein=self.parent.protein.file_path.name,
            client=self.parent.client,
        )

        results_files = [file for file in files if file.endswith("/results.csv")]
        results_files = {file: None for file in results_files}

        if len(results_files) == 0:
            print("No RBFE results found for this protein.")
            return None

        self.parent.client.files.download_files(
            results_files,
        )

        # read all the CSV files using pandas and
        # set Ligand1 column to ligand name (parent dir of results.csv)
        dfs = []
        for file in results_files:
            df = pd.read_csv(LOCAL_BASE / file)

            protein_name = file.split("/")[2]
            ligand1_name = file.split("/")[3]
            ligand2_name = file.split("/")[4]
            df["Protein"] = protein_name
            df["Ligand1"] = ligand1_name
            df["Ligand2"] = ligand2_name
            dfs.append(df)
        df1 = pd.concat(dfs)

        df2 = self.parent.ligands.to_dataframe()

        # Merge to get SMILES1
        df1 = df1.merge(
            df2[["File", "initial_smiles"]],
            left_on="Ligand1",
            right_on="File",
            how="left",
        )
        df1.rename(columns={"initial_smiles": "SMILES1"}, inplace=True)
        df1.drop("File", axis=1, inplace=True)

        # Merge to get SMILES2
        df1 = df1.merge(
            df2[["File", "initial_smiles"]],
            left_on="Ligand2",
            right_on="File",
            how="left",
        )
        df1.rename(columns={"initial_smiles": "SMILES2"}, inplace=True)
        df1.drop("File", axis=1, inplace=True)

        return df1

    def show_results(self):
        """Show RBFE results in a dataframe.

        This method returns a dataframe showing the results of RBFE runs associated with this simulation session. The ligand file name, 2-D structure, and ΔG are shown."""

        df = self.get_results()

        if df is None or len(df) == 0:
            return

        from rdkit.Chem import PandasTools

        PandasTools.AddMoleculeColumnToFrame(
            df, smilesCol="SMILES1", molCol="Structure1"
        )
        PandasTools.AddMoleculeColumnToFrame(
            df, smilesCol="SMILES2", molCol="Structure2"
        )
        PandasTools.RenderImagesInAllDataFrames()

        # show structure first
        new_order = ["Structure2"] + [col for col in df.columns if col != "Structure2"]
        df = df[new_order]
        new_order = ["Structure1"] + [col for col in df.columns if col != "Structure1"]
        df = df[new_order]

        if get_notebook_environment() == "marimo":
            import marimo as mo

            return mo.plain(df)

        else:
            return df

    @beartype
    def set_test_run(self, value: int = 1):
        """set test_run parameter in RBFE parameters"""

        utils._set_test_run(self._params.end_to_end, value)

    @beartype
    def run_ligand_pair(
        self,
        *,
        ligand1: Ligand,
        ligand2: Ligand,
        re_run: bool = False,
        _output_dir_path: Optional[str] = None,
        return_job: bool = True,
    ) -> Job | None | str:
        """Method to run an end-to-end RBFE run.

        Args:
            ligand1: First ligand to run.
            ligand2: Second ligand to run.
            re_run: Whether to re-run the job if it already exists.
            _output_dir_path: Path to the output directory.
        """

        # check that there is a prepared system for each ligand
        for ligand in [ligand1, ligand2]:
            if ligand.name not in self.parent._prepared_systems:
                raise DeepOriginException(
                    f"Complex with Ligand {ligand.name} is not prepared. Please prepare the system using the `prepare` method of Complex."
                ) from None

        # check that for every prepared system, the number of atoms is less than the max atom count
        for ligand_name, prepared_system in self.parent._prepared_systems.items():
            from deeporigin.drug_discovery.external_tools.utils import (
                count_atoms_in_pdb_file,
            )

            num_atoms = count_atoms_in_pdb_file(prepared_system)

            if num_atoms > self._max_atom_count:
                raise ValueError(
                    f"System with {ligand_name} has too many atoms. It has {num_atoms} atoms, but the maximum allowed is {self._max_atom_count}."
                )

        self.parent._sync_protein_and_ligands()

        if self.jobs is None:
            self.jobs = []

        metadata = dict(
            protein_file=os.path.basename(self.parent.protein._remote_path),
            ligand1_file=os.path.basename(ligand1._remote_path),
            ligand2_file=os.path.basename(ligand2._remote_path),
            ligand1_smiles=ligand1.smiles,
            ligand2_smiles=ligand2.smiles,
        )

        job_id = utils._start_tool_run(
            metadata=metadata,
            ligand1_path=ligand1._remote_path,
            ligand2_path=ligand2._remote_path,
            protein_path=self.parent.protein._remote_path,
            params=self._params.end_to_end,
            tool="RBFE",
            tool_version=self.tool_version,
            client=self.parent.client,
            _output_dir_path=_output_dir_path,
        )

        if return_job:
            job = Job.from_id(job_id, client=self.parent.client)

            self.jobs.append(job)
            return job
        else:
            return job_id

    @beartype
    def run_network(self, *, re_run: bool = False) -> Job:
        """
        Run RBFE for the ligand pairs in the network in the ligand set in the Complex.

        Args:
            re_run (bool, optional): If True, re-run jobs even if results already exist. Defaults to False.

        Returns:
            Job: The Job object representing the network run.
        """
        if "edges" not in self.parent.ligands.network.keys():
            raise DeepOriginException(
                "Network not mapped yet. Please map the network first using `map_network()`."
            )

        job_ids = []

        from tqdm import tqdm

        # Wrap the edge iteration in a tqdm progress bar
        for edge in tqdm(
            self.parent.ligands.network["edges"], desc="Starting RBFE network..."
        ):
            ligand1_name = edge["source"]
            ligand2_name = edge["target"]

            ligand1 = [
                ligand for ligand in self.parent.ligands if ligand.name == ligand1_name
            ]

            if len(ligand1) == 0:
                raise DeepOriginException(
                    f"Ligand {ligand1_name} not found in the network."
                )

            ligand1 = ligand1[0]

            ligand2 = [
                ligand for ligand in self.parent.ligands if ligand.name == ligand2_name
            ]

            if len(ligand2) == 0:
                raise DeepOriginException(
                    f"Ligand {ligand2_name} not found in the network."
                )

            ligand2 = ligand2[0]

            job_id = self.run_ligand_pair(
                ligand1=ligand1,
                ligand2=ligand2,
                re_run=re_run,
                return_job=False,
            )

            job_ids.append(job_id)

        return Job.from_id(job_ids[0], client=self.parent.client)

    def get_jobs(self) -> None:
        """Get the jobs for jobs corresponding to this network and save to self.jobs"""

        if self.parent.ligands.network.get("edges", None) is None:
            # no network mapped. use the default get_jobs method
            return super().get_jobs()

        # at this point, we know that the network is mapped
        # so we need to get the jobs for each ligand pair
        df = self.get_jobs_df()

        ligand_dict = {ligand.smiles: ligand.name for ligand in self.parent.ligands}
        edges = self.parent.ligands.network["edges"]
        valid_job_ids = []
        for _, row in df.iterrows():
            metadata = row["metadata"]
            if "ligand1_smiles" not in metadata.keys():
                continue
            if "ligand2_smiles" not in metadata.keys():
                continue
            edge = dict(
                source=ligand_dict[metadata["ligand1_smiles"]],
                target=ligand_dict[metadata["ligand2_smiles"]],
            )
            if edge in edges:
                valid_job_ids.append(row["id"])

        job = Job.from_id(
            valid_job_ids[0],
            client=self.parent.client,
        )
        self.jobs = [job]
