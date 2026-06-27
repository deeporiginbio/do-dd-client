# Using platform APIs using Deep Origin Platform Client

This document describes how to use the Deep Origin Platform Client.

## Background

The typical way an end-user would use the Deep Origin python package would be to simply call functions. These functions call various APIs on the Deep Origin platform, using tokens and config information that is read from disk. This approach offers convenience for users who are taking actions as themselves on the platform, within a single organization.

## Construction: four entry points

There are four ways to construct a `DeepOriginClient`:

| Entry point | Where config comes from | Use case |
|---|---|---|
| `DeepOriginClient()` | OS env: token + org (base URL optional); else `~/.deeporigin/` | Default — works in tests and interactive use |
| `DeepOriginClient.from_headers(headers)` | HTTP request headers | Inside a served tool handler |
| `DeepOriginClient.from_env_variables()` | OS environment variables only (fails fast if any missing) | Provisioned container / CI |
| `DeepOriginClient.from_disk(env=...)` | `~/.deeporigin/` config files | Interactive Jupyter / CLI, explicit disk read |

### No-arg constructor — `DeepOriginClient()`

The no-arg constructor uses a priority chain:

1. If `DO_AUTH_TOKEN` and `DO_ORG_KEY` are set → uses `from_env_variables()` (if
   `DO_BASE_URL` is unset, the API URL is inferred from the JWT issuer)
2. Else if `DO_ENV=local` → uses `from_local()` (points to a locally running mock server)
3. Otherwise → uses `from_disk()`

This means code that calls `DeepOriginClient()` works correctly in all contexts:
- **Tests (local mock)**: `DO_ENV=local` routes to `from_local()` automatically
- **CI / containers**: token and org set, so `from_env_variables()` is used (`DO_BASE_URL` optional)
- **Interactive use**: no env vars set, so disk config is used transparently

```python
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
```

### From HTTP request headers — served tool

```{.python notest}
client = DeepOriginClient.from_headers(request.headers)
```

Required headers: `X-Do-Auth-Token`, `X-Do-Org-Key`, `X-Do-Base-Url`.
Optional header: `X-Do-Project-Id`.

### From OS environment variables — provisioned container

```{.python notest}
client = DeepOriginClient.from_env_variables()
```

Reads `DO_AUTH_TOKEN`, `DO_ORG_KEY`, and optionally `DO_PROJECT_ID`. `DO_BASE_URL`
is optional when `DO_AUTH_TOKEN` is set (the URL is inferred from the token).
Raises `ValueError` immediately if `DO_AUTH_TOKEN` or `DO_ORG_KEY` is missing.

```bash
export DO_AUTH_TOKEN="my-secret-token"
export DO_ORG_KEY="my-org"
export DO_BASE_URL="https://api.deeporigin.io"
```

### From disk config files — interactive use

```{.python notest}
client = DeepOriginClient.from_disk(env="prod")
```

Reads the access token from `~/.deeporigin/api_tokens.json` and the org key from
`~/.deeporigin/config.json`. The `env` parameter selects which environment's token
to load.

## Multi-user, multi-org

To make actions in multiple organizations, or as multiple users, a `client` can be
passed to every function.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.from_disk(env="prod")
tools = client.tools.list()
```

## The four core fields

`base_url` is fixed after construction. `org_key` may be reassigned on the
client (e.g. `client.org_key = "my-org"`) or persisted via `config.set_org`.
`token` and `project_id` are mutable via setters:

- `client.base_url` — API base URL (read-only after construction)
- `client.token` — authentication token; the setter also refreshes the `Authorization` header
- `client.org_key` — organization key (mutable; does not persist unless you use `config.set_org`)
- `client.project_id` — data platform project id (may be `None`; updated by `projects.load()`)

The `env` property is computed from `base_url` and returns one of `"prod"`, `"staging"`, `"dev"`, `"local"`.

Optional mutable attributes can be set after construction:

```{.python notest}
client.tag = "my-experiment"
client.billing_tag = "runtime-billing"
client.max_retries = 5
client.record = True
```

### Execution billing tags

Set ``client.tag`` and/or ``client.billing_tag`` once on the client. Every
``executions.create`` call (including tool ``run()`` / ``start()``) sends those
values as the platform ``tag`` and ``billing`` fields when present. There is no
per-run override on tool methods. Advanced callers may still set ``tag`` or
``billing`` explicitly inside the ``data`` payload passed to
``executions.create``.

## Retry Configuration

The `DeepOriginClient` includes built-in retry logic to handle transient network errors and server issues. By default, the client will retry failed requests up to 3 times with exponential backoff.

### Default Retry Behavior

The client automatically retries requests that fail with:
- Network errors (connection failures)
- Timeout errors
- HTTP status codes: 429 (Rate Limit), 500 (Internal Server Error), 502 (Bad Gateway), 503 (Service Unavailable), 504 (Gateway Timeout)

The client does not retry on client errors (4xx status codes except 429), as these typically indicate issues with the request itself rather than transient server problems.

### Configuring Retries

You can customize retry behavior when creating a client:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

# Disable retries
client = DeepOriginClient.from_disk(env="prod")
client.max_retries = 0

# Customize retry attempts and backoff (set at construction)
client = DeepOriginClient.from_disk(env="prod", max_retries=5, retry_backoff_factor=0.5)
```

### Retry Parameters

- `max_retries`: Maximum number of retry attempts (default: 3). Set to 0 to disable retries.
- `retry_backoff_factor`: Multiplier for exponential backoff between retries. The delay before retry attempt `n` is calculated as `retry_backoff_factor * (2 ** n)` seconds. Default: 1.0.
- `max_retry_delay`: Maximum delay in seconds between retries. Default: 60.0.

### Example: Handling Rate Limits

When dealing with rate-limited APIs, you can increase retries and customize the backoff:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.from_disk(
    env="prod",
    max_retries=5,
    retry_backoff_factor=2.0,
)

# The client will automatically retry on 429 errors with increasing delays
tools = client.tools.list()
```
