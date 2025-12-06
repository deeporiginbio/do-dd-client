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

- `DEEPORIGIN_TOKEN`: API token
- `DEEPORIGIN_ENV`: Target environment (one of `prod`, `staging`, `dev`). Defaults to `prod` when unset
- `DEEPORIGIN_ORG_KEY`: Organization key

Example:

```bash
export DEEPORIGIN_TOKEN="my-secret-token"
export DEEPORIGIN_ENV="staging"
export DEEPORIGIN_ORG_KEY="my-org"
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