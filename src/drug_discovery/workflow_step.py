"""Base class for workflow steps like ABFE, RBFE, and Docking."""

from beartype import beartype
import pandas as pd

from deeporigin.platform.job import Job, JobList
from deeporigin.utils.core import PrettyDict


class WorkflowStep:
    """Base class for workflow steps that handle jobs."""

    """
    If True, the jobs will be fused into a single job.
    This is useful for workflow steps that are run in parallel in batches,
    such as Docking.
    """
    _tool_key: str = ""  # To be overridden by derived classes
    parent = None
    jobs: list[Job] | None = None

    def __init__(self, parent):
        self.parent = parent
        self._params = PrettyDict()

    def get_jobs_df(
        self,
        *,
        include_metadata: bool = True,
        include_inputs: bool = False,
        include_outputs: bool = True,
        status: list[str] | None = None,
    ) -> pd.DataFrame:
        """Get the jobs for this workflow step as a dataframe

        Args:
            include_metadata: Whether to include metadata column in the dataframe
            include_inputs: Whether to include user_inputs column in the dataframe
            include_outputs: Whether to include user_outputs column in the dataframe
            status: List of job statuses to filter by. If None, uses default non-failed states.
        """
        if status is None:
            status = ["Running", "Queued", "Created", "Succeeded", "Quoted"]

        jobs = JobList.list(
            client=self.parent.client,
        )
        # Always include metadata for filtering purposes, even if not requested in output
        df = jobs.filter(
            tool_key=self._tool_key if self._tool_key else None,
            status=status,
            require_metadata=True,
        ).to_dataframe(
            include_metadata=True,  # Always include for filtering
            include_inputs=include_inputs,
            include_outputs=include_outputs,
            resolve_user_names=False,
            client=self.parent.client,
        )

        if len(df) == 0:
            return df

        # filter by tool key (if not already filtered by JobList.filter)
        if self._tool_key and "tool_key" in df.columns:
            df = df[df["tool_key"].str.contains(self._tool_key)]

        # filter by protein file (only if metadata column exists)
        if "metadata" in df.columns:
            df = df[
                df["metadata"].apply(
                    lambda x: isinstance(x, dict)
                    and x.get("protein_hash") == self.parent.protein.to_hash()
                )
            ]

        # Drop metadata column if not requested in output
        if not include_metadata and "metadata" in df.columns:
            df = df.drop(columns=["metadata"])

        df = df.reset_index(drop=True)

        return df

    @beartype
    def get_jobs(self) -> None:
        """Get the jobs for this workflow step and save to self.jobs"""
        df = self.get_jobs_df()

        job_ids = df["id"].tolist()

        self.jobs = [
            Job.from_id(
                job_id,
                client=self.parent.client,
            )
            for job_id in job_ids
        ]
