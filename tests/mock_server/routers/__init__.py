"""Routers for the mock server.

Each module exposes a ``create_*_router(...)`` factory function instead of a
module-level ``APIRouter`` instance.  This is because route handlers need access
to shared mutable state that lives on the ``MockServer`` instance (e.g.
``_ligands``, ``_executions``, ``_file_storage``).  The factory function receives
that state as arguments and the inner route handlers close over it.
"""

from . import billing, data_platform, entities, files, tools

__all__ = ["billing", "data_platform", "entities", "files", "tools"]
