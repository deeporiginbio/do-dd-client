# Progress Reports API

The Progress Reports API provides access to execution progress data from the data platform.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()

# Get progress reports for an execution
reports = client.progress_reports.get(execution_id="26744bee-bb66-4f59-aa68-2592e57927a2")
```


::: src.platform.progress_reports.ProgressReports
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
        - "!^_"
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true
