# Using platform APIs using Deep Origin Platform Client

This document describes how to use the Deep Origin Platform Client. 

## Background

The typical way an end-user would use the Deep Origin python package would be to simply call functions. These functions call various APIs on the Deep Origin platform, using tokens and config information that is read from disk. This approach offers convenience for users who are taking actions as themselves on the platform, within a single organization.  

## Multi-user, multi-org

To make actions in multiple organizations, or as multiple users, a `client` can be passed to every function. 

First, construct a client using:


```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient(token="my-secret-token", org_key="my-org")
```

Now, we can list tools using:

```{.python notest}
tools = client.tools.list()
```

## Configuration via environment variables

You can omit constructor arguments and configure the client via environment variables:

- `DEEPORIGIN_TOKEN`: API token
- `DEEPORIGIN_ENV`: Target environment (one of `prod`, `staging`, `edge`). Defaults to `prod` when unset
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

client = DeepOriginClient()
```