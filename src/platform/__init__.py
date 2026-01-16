"""Platform client module.

Provides the `DeepOriginClient` used to interact with the Deep Origin platform.

This module supports configuration via keyword arguments or the following
environment variables when keywords are omitted:

- `DEEPORIGIN_TOKEN`
- `DEEPORIGIN_ENV` (defaults to "prod" if not provided)
- `DEEPORIGIN_ORG_KEY`

The client automatically caches instances based on (base_url, token, org_key, tag),
so calling `DeepOriginClient()` multiple times with the same parameters returns
the same cached instance, reusing connection pools.

Example:
    client = DeepOriginClient()  # Uses singleton cache automatically
    client.tag = "my-tag"  # Set tag for all function runs
"""

from deeporigin.platform.client import DeepOriginClient

__all__ = ["DeepOriginClient"]
