"""Base class for workflow steps like ABFE, RBFE, and Docking."""

from beartype import beartype
import pandas as pd

from deeporigin.tools.job import Job, get_dataframe
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
        include_outputs: bool = True,
    ) -> pd.DataFrame:
        """Get the jobs for this workflow step as a dataframe"""

        df = get_dataframe(
            client=self.parent.client,
            resolve_user_names=False,
            include_metadata=True,
            include_outputs=include_outputs,
            only_with_status=["Running", "Queued", "Created", "Succeeded", "Quoted"],
        )

        if len(df) == 0:
            return df

        # filter by tool key
        df = df[df["tool_key"].str.contains(self._tool_key)]

        # filter by protein file
        df = df[
            df["metadata"].apply(
                lambda x: isinstance(x, dict)
                and x.get("protein_hash") == self.parent.protein.to_hash()
            )
        ]

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
