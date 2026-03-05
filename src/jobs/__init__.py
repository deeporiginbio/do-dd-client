"""Jobs-centric API for computational workflows.

Provides unified execution classes composed from mixins:

- ``PocketFinder`` -- sync-only pocket detection
- ``Docking`` -- sync + async molecular docking
- ``ABFE`` -- async absolute binding free energy
"""

from deeporigin.jobs.abfe import ABFE
from deeporigin.jobs.base import Execution, PlatformStatus
from deeporigin.jobs.docking import Docking
from deeporigin.jobs.mixins import (
    AsyncExecutableMixin,
    JupyterVizMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.jobs.pocket_finder import PocketFinder

__all__ = [
    "ABFE",
    "Execution",
    "PlatformStatus",
    "QuoteMixin",
    "SyncExecutableMixin",
    "AsyncExecutableMixin",
    "JupyterVizMixin",
    "PocketFinder",
    "Docking",
]
