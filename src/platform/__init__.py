"""Platform client module.

Provides the `DeepOriginClient` used to interact with the Deep Origin platform.

This module supports configuration via keyword arguments or the following
environment variables when keywords are omitted:

- `DO_AUTH_TOKEN`
- `DO_ENV` (defaults to "prod" if not provided)
- `DO_ORG_KEY`
- `DO_PROJECT_ID` (optional data platform project id)

The client automatically caches instances based on
(base_url, token, org_key, _app, _session),
so calling `DeepOriginClient()` multiple times with the same parameters returns
the same cached instance, reusing connection pools.

Example:
    client = DeepOriginClient()  # Uses singleton cache automatically
    client.tag = "my-tag"  # Set tag for all tool executions
"""

from deeporigin.platform.client import DeepOriginClient

__all__ = ["DeepOriginClient"]
