"""Platform client module.

Provides the `DeepOriginClient` used to interact with the Deep Origin platform.

This module supports configuration via keyword arguments or the following
environment variables when keywords are omitted:

- `DEEPORIGIN_TOKEN`
- `DEEPORIGIN_ENV` (defaults to "prod" if not provided)
- `DEEPORIGIN_ORG_KEY`

Use `DeepOriginClient.get()` to get a cached singleton instance that reuses
connection pools across notebook cells.
"""

from deeporigin.platform.client import DeepOriginClient

__all__ = ["DeepOriginClient"]
