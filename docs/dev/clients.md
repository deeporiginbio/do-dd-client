# Using platform APIs using Deep Origin Platform Client

This document describes how to use the Deep Origin Platform Client. 

## Background

The typical way an end-user would use the Deep Origin python package would be to simply call functions. These functions call various APIs on the Deep Origin platform, using tokens and config information that is read from disk. This approach offers convenience for users who are taking actions as themselves on the platform, within a single organization.  

## Multi-user, multi-org

To make actions in multiple organizations, or as multiple users, a `client` can be passed to every function. 

First, construct a client using:


```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get(token="my-secret-token", org_key="my-org")
```

Now, we can list tools using:

```{.python notest}
tools = client.tools.list()
```

## Configuration via environment variables

You can omit constructor arguments and configure the client via environment variables:

- `DO_AUTH_TOKEN`: API token
- `DO_ENV`: Target environment (one of `prod`, `staging`, `dev`). Defaults to `prod` when unset
- `DO_ORG_KEY`: Organization key

Example:

```bash
export DO_AUTH_TOKEN="my-secret-token"
export DO_ENV="staging"
export DO_ORG_KEY="my-org"
```

Then construct a client without arguments:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get()
```

## Creating a client from environment files

You can also create a client that reads configuration from disk files using the `from_env` class method:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.from_env(env="prod")
```

This method:
- Reads the access token from `~/.DeepOrigin/api_tokens.json` using the specified environment key
- Reads the organization key from the config file (`~/.DeepOrigin/config.json`)
- Requires you to specify the environment explicitly (e.g., `"prod"`, `"staging"`, `"dev"`)

This is useful when you want to ensure the client reads from the configuration files rather than environment variables.

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
client = DeepOriginClient.get(max_retries=0)

# Customize retry attempts and backoff
client = DeepOriginClient.get(
    max_retries=5,
    retry_backoff_factor=0.5,  # Delay = 0.5 * (2 ** attempt_number)
)

# Customize which status codes trigger retries
client = DeepOriginClient.get(
    max_retries=3,
    retryable_status_codes={429, 500, 502, 503, 504, 408},  # Include 408 (Request Timeout)
)
```

### Retry Parameters

- `max_retries`: Maximum number of retry attempts (default: 3). Set to 0 to disable retries.
- `retryable_status_codes`: Set of HTTP status codes that should trigger a retry (default: `{429, 500, 502, 503, 504}`).
- `retry_backoff_factor`: Multiplier for exponential backoff between retries. The delay before retry attempt `n` is calculated as `retry_backoff_factor * (2 ** n)` seconds. Default: 1.0.

### Example: Handling Rate Limits

When dealing with rate-limited APIs, you can increase retries and customize the backoff:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

# Configure client to handle rate limits more gracefully
client = DeepOriginClient.get(
    max_retries=5,
    retry_backoff_factor=2.0,  # Longer delays between retries
    retryable_status_codes={429, 500, 502, 503, 504},
)

# The client will automatically retry on 429 errors with increasing delays
tools = client.tools.list()
```