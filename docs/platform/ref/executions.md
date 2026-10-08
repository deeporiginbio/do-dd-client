# Tools API.

The DeepOriginClient can be used to access the tools API using:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
```

Then, the following methods can be used, for example:

```{.python notest}
tools = client.executions.list()
```

To block until an execution's results are available on the data platform, use
`wait_for_ingestion`. It is woken by change notifications, and also re-checks
the execution about every 90 seconds, so it still finishes if a notification is
lost. While notifications are unavailable it checks every 2 seconds instead. It
returns the execution record once the execution has finished (completed, failed
or cancelled), so check its `status`. On a backend that cannot return hidden
executions, it returns `{}` for a hidden execution once its results appear, or
after about two minutes:

```{.python notest}
row = client.executions.wait_for_ingestion(execution_id, project_id=project_id)
if row["status"] != "Completed":
    ...
```

See the [wait-for-ingestion notebook](../../notebooks/clean/wait-for-ingestion.ipynb)
for a full example.


::: src.platform.executions.Executions
    options:
      heading_level: 2
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true