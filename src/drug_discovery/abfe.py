"""This module encapsulates methods to run ABFE and show ABFE results on Deep Origin.

The ABFE object instantiated here is contained in the Complex class is meant to be used within that class."""

from pathlib import Path
from typing import Literal, Optional

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery import utils
from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.workflow_step import WorkflowStep
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import file_api
from deeporigin.tools.job import Job, get_dataframe
from deeporigin.utils.notebook import get_notebook_environment

LOCAL_BASE = Path.home() / ".deeporigin"


class ABFE(WorkflowStep):
    """class to handle ABFE-related tasks within the Complex class.

    Objects instantiated here are meant to be used within the Complex class."""

    """tool version to use for ABFE"""
    tool_version = "0.2.18"
    _tool_key = tool_mapper["ABFE"]

    _max_atom_count: int = 100_000

    def __init__(self, parent):
        super().__init__(parent)

        self._params.end_to_end = utils._load_params("abfe_end_to_end")

    def get_results(self) -> pd.DataFrame | None:
        """get ABFE results and return in a dataframe.

        This method returns a dataframe showing the results of ABFE runs associated with this simulation session. The ligand file name and ΔG are shown, together with user-supplied properties"""

        df = self.get_jobs_df(include_outputs=True)

        results_files = []

        for _, row in df.iterrows():
            file_path = row["user_outputs"]["abfe_results_summary"]["key"]
            results_files.append(file_path)

        if len(results_files) == 0:
            print("No ABFE results found for this protein.")
            return None

        results_files = dict.fromkeys(results_files, None)

        results_files = file_api.download_files(
            results_files,
            client=self.parent.client,
            skip_errors=True,
        )

        ligand_mapper = {}
        for ligand in self.parent.ligands:
            ligand_mapper[ligand.to_hash()] = ligand.smiles

        # read all the CSV files using pandas and
        # set Ligand1 column to ligand name (parent dir of results.csv)
        dfs = []
        for file in results_files:
            df = pd.read_csv(file, nrows=1)  # we only expect one row per ABFE run

            # extract ligand hash from file path
            ligand_hash = str(Path(file).parent.stem)
            df["SMILES"] = ligand_mapper[ligand_hash]

            dfs.append(df)
        df1 = pd.concat(dfs)

        df1.drop(columns=["Ligand"], inplace=True)

        df2 = self.parent.ligands.to_dataframe()

        df = pd.merge(df1, df2, on="SMILES", how="inner")

        return df

    def show_results(self):
        """Show ABFE results in a dataframe.

        This method returns a dataframe showing the results of ABFE runs associated with this simulation session. The ligand file name, 2-D structure, and ΔG are shown."""

        df = self.get_results()

        if df is None or len(df) == 0:
            return

        from rdkit.Chem import PandasTools

        PandasTools.AddMoleculeColumnToFrame(df, smilesCol="SMILES", molCol="Structure")
        PandasTools.RenderImagesInAllDataFrames()

        # show structure first
        new_order = ["Structure"] + [col for col in df.columns if col != "Structure"]

        # re‑index DataFrame
        df = df[new_order]

        if get_notebook_environment() == "marimo":
            import marimo as mo

            return mo.plain(df)

        else:
            return df

    def get_jobs_df(
        self,
        *,
        include_metadata: bool = False,
        include_outputs: bool = False,
    ):
        """get jobs for this workflow step"""
        df = super().get_jobs_df(include_outputs=include_outputs)

        ligand_hashes = [ligand.to_hash() for ligand in self.parent.ligands]

        # filter df by ligand_hash
        df = df[df["metadata"].apply(lambda d: d.get("ligand_hash") in ligand_hashes)]

        # make a new column called ligand_smiles using the metadata column
        df["ligand_smiles"] = df["metadata"].apply(
            lambda d: d.get("ligand_smiles") if isinstance(d, dict) else None
        )

        # make a new column called protein_file using the metadata column
        df["protein_name"] = df["metadata"].apply(
            lambda d: d.get("protein_name") if isinstance(d, dict) else None
        )

        # make a new column called ligand_file using the metadata column
        df["ligand_name"] = df["metadata"].apply(
            lambda d: d.get("ligand_name") if isinstance(d, dict) else None
        )

        if not include_metadata:
            df.drop(columns=["metadata"], inplace=True)

        return df

    @beartype
    def set_test_run(self, value: int = 1):
        """set test_run parameter in abfe parameters"""

        utils._set_test_run(self._params.end_to_end, value)

    @beartype
    def _get_ligands_to_run(
        self,
        *,
        ligands: list[Ligand] | LigandSet,
        re_run: bool,
    ) -> list[Ligand]:
        """Helper method to determine which ligands need to be run based on already run jobs and re_run flag."""

        if isinstance(ligands, LigandSet):
            ligands = ligands.ligands

        if re_run:
            # we're re-running, so we need to re-run all ligands
            return ligands

        df = get_dataframe(
            tool_key=tool_mapper["ABFE"],
            only_with_status=["Succeeded", "Running", "Queued", "Created"],
            include_metadata=True,
            resolve_user_names=False,
            client=self.parent.client,
        )

        # Build set of ligand names that have already been run
        if len(df) > 0:
            ligand_hashes_already_run = {
                ligand_hash
                for ligand_hash in df["metadata"].apply(
                    lambda d: d.get("ligand_hash") if isinstance(d, dict) else None
                )
                if isinstance(ligand_hash, str) and ligand_hash
            }
        else:
            ligand_hashes_already_run = set()

        print(ligand_hashes_already_run)

        # no re-run, remove already run ligands
        ligands_to_run = [
            ligand
            for ligand in ligands
            if ligand.to_hash() not in ligand_hashes_already_run
        ]
        return ligands_to_run

    @beartype
    def check_dt(self):
        """Validate that every "dt" in params is numeric and within allowed bounds.

        Traverses the nested parameters dictionary and validates that each
        occurrence of a key named "dt" has a numeric value within the
        inclusive range [min_dt, max_dt]. If any non-numeric or out-of-range
        values are found, an error is raised listing all offending paths.

        Raises:
            DeepOriginException: If any "dt" value is non-numeric or outside
                the allowed range.
        """
        min_dt = 0.001
        max_dt = 0.004

        def is_number(value) -> bool:
            return isinstance(value, (int, float))

        def find_dt_violations(obj, path: list[str]) -> list[str]:
            """Return list of JSON-like paths with invalid dt values."""
            violations: list[str] = []
            if isinstance(obj, dict):
                for key, value in obj.items():
                    next_path = path + [str(key)]
                    if key == "dt" and (
                        not is_number(value) or not (min_dt <= float(value) <= max_dt)
                    ):
                        violations.append(".".join(next_path))
                    # Recurse into nested structures
                    if isinstance(value, (dict, list, tuple)):
                        violations.extend(find_dt_violations(value, next_path))
            elif isinstance(obj, (list, tuple)):
                for idx, value in enumerate(obj):
                    next_path = path + [str(idx)]
                    if isinstance(value, (dict, list, tuple)):
                        violations.extend(find_dt_violations(value, next_path))
            return violations

        violations = find_dt_violations(self._params, ["_params"])
        if violations:
            paths = ", ".join(violations)
            raise DeepOriginException(
                f"Found invalid dt values; must be numeric and within range [{min_dt}, {max_dt}]. Offending paths: {paths}"
            ) from None

    @beartype
    def run(
        self,
        *,
        ligands: Optional[list[Ligand] | LigandSet] = None,
        ligand: Optional[Ligand] = None,
        re_run: bool = False,
        output_dir_path: Optional[str] = None,
        approve_amount: Optional[int] = 0,
        quote: bool = False,
    ) -> list[Job] | None:
        """Method to run an end-to-end ABFE run.

        Args:
            ligands: List of ligand to run. Defaults to None. When None, all ligands in the object will be run. To view a list of valid ligands, use the `.show_ligands()` method
            ligand: A single ligand to run. Defaults to None. When None, all ligands in the object will be run.
            re_run: Whether to re-run the job if it already exists.
            output_dir_path: Path to the output directory.
            approve_amount: Dollar amount under which a job will be approved automatically.
            quote: Whether to run or quote the job. When True, the job will be quoted and not run.
        """

        # check that dt in params is valid
        self.check_dt()

        if quote:
            approve_amount = 0
            re_run = True  # if we want a quote, it's irrelevant whether this has already been run or not

        if ligands is None and ligand is None:
            ligands = self.parent.ligands
        elif ligands is None:
            ligands = [ligand]

        if isinstance(ligands, LigandSet):
            ligands = ligands.ligands

        for ligand in ligands:
            if ligand.is_charged():
                raise DeepOriginException(
                    title="Cannot run ABFE: charged ligand",
                    message=f"Ligand {ligand.name} with SMILES {ligand.smiles} is charged. ABFE does not currently support charged ligands.",
                ) from None

        # check that there is a prepared system for each ligand
        for ligand in ligands:
            if ligand.to_hash() not in self.parent._prepared_systems:
                raise DeepOriginException(
                    title="Cannot run ABFE: unprepared ligand",
                    message=f"Complex with Ligand {ligand.name} is not prepared.",
                    fix="Use the `prepare` method of Complex to prepare the system.",
                    level="danger",
                ) from None

        # TODO -- re-implement this check once we have a way to get the number of atoms in a prepared system
        # # check that for every prepared system, the number of atoms is less than the max atom count
        # for ligand_name, prepared_system in self.parent._prepared_systems.items():
        #     if prepared_system.num_atoms > self._max_atom_count:
        #         raise ValueError(
        #             f"System with {ligand_name} has too many atoms. It has {prepared_system.num_atoms} atoms, but the maximum allowed is {self._max_atom_count}."
        #         )

        self.parent._sync_protein_and_ligands()

        ligands_to_run = self._get_ligands_to_run(ligands=ligands, re_run=re_run)

        if len(ligands_to_run) == 0:
            print(
                "All requested ligands have already been run, or are queued to run. To re-run, set re_run=True"
            )
            return

        if self.jobs is None:
            self.jobs = []

        jobs_for_this_run = []

        # TODO -- parallelize this
        for ligand in ligands_to_run:
            metadata = {
                "protein_hash": self.parent.protein.to_hash(),
                "ligand_hash": ligand.to_hash(),
                "ligand_smiles": ligand.smiles,
                "protein_name": self.parent.protein.name,
                "ligand_name": ligand.name,
            }

            try:
                prepared_system = self.parent._prepared_systems[ligand.to_hash()]

                output_files = prepared_system["output_files"]

                binding_xml = [
                    file for file in output_files if file.endswith("bsm_system.xml")
                ][0]
                solvation_xml = [
                    file for file in output_files if file.endswith("solvation.xml")
                ][0]

                params = self._params.end_to_end

                params["binding_xml"] = {
                    "$provider": "ufa",
                    "key": binding_xml,
                }
                params["solvation_xml"] = {
                    "$provider": "ufa",
                    "key": solvation_xml,
                }

            except Exception as e:
                raise DeepOriginException(
                    "There is an error with the prepared system. Please prepare the system using the `prepare` method of Complex."
                ) from e

            if output_dir_path is None:
                output_dir_path = f"tool-runs/ABFE/{self.parent.protein.to_hash()}.pdb/{ligand.to_hash()}.sdf/"

            job_id = utils._start_tool_run(
                metadata=metadata,
                params=params,
                tool="ABFE",
                tool_version=self.tool_version,
                client=self.parent.client,
                output_dir_path=output_dir_path,
                approve_amount=approve_amount,
            )

            job = Job.from_id(job_id, client=self.parent.client)

            self.jobs.append(job)
            jobs_for_this_run.append(job)

        return jobs_for_this_run

    @beartype
    def show_trajectory(
        self,
        *,
        ligand: Ligand,
        step: Literal["md", "binding"],
        window: int = 1,
    ):
        """Show the system trajectory FEP run.

        Args:
            job: The job to show the trajectory for.
            step (Literal["md", "abfe"]): The step to show the trajectory for.
            window (int, optional): The window number to show the trajectory for.
        """

        if window < 1:
            raise DeepOriginException(
                title="Invalid window number",
                message="Window number must be greater than 0",
                fix="Please specify a window number greater than 0",
            ) from None

        df = self.get_jobs_df(include_outputs=True)
        df = df.loc[df["ligand_smiles"] == ligand.smiles]

        if len(df) == 0:
            raise DeepOriginException(
                title="No job found for this ligand",
                message="No job found for this ligand",
            ) from None

        remote_base = Path(df.iloc[0]["user_outputs"]["output_file"]["key"])

        remote_pdb_file = remote_base / "protein/ligand/systems/complex/system.pdb"
        files_to_download = [remote_pdb_file]

        if step == "binding":
            # Check for valid windows

            # figure out valid windows
            files = file_api.list_files_in_dir(
                file_path=str(remote_base),
                client=self.parent.client,
            )
            xtc_files = [
                file
                for file in files
                if file.endswith("Prod_1/_allatom_trajectory_40ps.xtc")
                and "binding/binding" in file
            ]

            import re

            valid_windows = [
                int(re.search(r"window_(\d+)", path).group(1)) for path in xtc_files
            ]

            if window not in valid_windows:
                raise DeepOriginException(
                    title="Invalid window number",
                    message=f"Valid windows are: {sorted(valid_windows)}",
                ) from None

            remote_xtc_file = (
                remote_base
                / f"protein/ligand/binding/binding/window_{window}/Prod_1/_allatom_trajectory_40ps.xtc"
            )

        else:
            remote_xtc_file = (
                remote_base
                / "protein/ligand/simple_md/simple_md/prod/_allatom_trajectory_40ps.xtc"
            )

        files_to_download.append(remote_xtc_file)
        files_to_download = dict.fromkeys(map(str, files_to_download), None)

        file_api.download_files(
            files_to_download,
            client=self.parent.client,
            lazy=True,
        )

        from deeporigin_molstar.src.viewers import ProteinViewer

        protein_viewer = ProteinViewer(
            data=str(LOCAL_BASE / remote_pdb_file), format="pdb"
        )
        html_content = protein_viewer.render_trajectory(
            str(LOCAL_BASE / remote_xtc_file)
        )

        from deeporigin_molstar import JupyterViewer

        JupyterViewer.visualize(html_content)
