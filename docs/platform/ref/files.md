# Files API

Use `DeepOriginClient().files` to list, upload, download, and delete objects in your organization’s file storage.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
```

Example:

```{.python notest}
keys = client.files.list(remote_path="entities/")
```

Remote paths may be stored with a leading slash (for example `/seeded/proteins/BRD.pdb`
from the data platform). The client strips leading slashes before calling the
file-service API so signed URLs and direct downloads resolve correctly.

## Choosing a method

Use this table to pick the right call. The client uses **two upload styles** (multipart via the platform API vs. signed URLs to object storage) and **two download styles** (signed URL streaming vs. direct GET through the API).

### Listing and metadata

| Method | Use when |
|--------|----------|
| **`list(..., metadata=False)`** | You only need remote **keys** (paths) under a prefix — default for scripts and discovery. |
| **`list(..., metadata=True)`** | You need **Size**, **ETag**, **LastModified**, etc., from the API for each object. |
| **`stat(remote_path)`** | You need **headers** for a **single** file (HEAD) without listing a directory. |

### Uploads

| Method | Use when |
|--------|----------|
| **`upload(local, remote)`** | **One** file; body goes through the platform as **multipart** (`PUT /files/...`). Simple and authenticated like any other API call. |
| **`upload_many(files={local: remote, ...})`** | **Many** files with **explicit** local→remote paths; each file uploaded in parallel via the same **multipart** path as `upload`. |
| **`upload_tree(local_path, remote_dir)`** | A **directory** (recursive) or a **list** of local files; files go to `remote_dir` preserving relative paths. Uses **signed URLs** and parallel PUTs — better for large trees and heavy parallelism (bytes skip the app server). Each file is **streamed** from disk (not fully buffered in memory); failed PUTs request a **fresh presigned URL** on retry; parallel workers schedule **largest files first** to reduce idle time at the end of a batch. |
| **`upload_from_url(remote_path, source_url=...)`** | The **server** should fetch a public URL and store the object; bytes never pass through your machine. |

### Downloads

| Method | Use when |
|--------|----------|
| **`download(remote_path, ...)`** (default) | **One** file; default path uses a **signed URL** and **streams** to disk — preferred for **large** files. |
| **`download(..., direct=True)`** | **One** file via **GET** through the platform API; response body is read into memory — fine for **small** files or when you want a single hop through the gateway. |
| **`download_stream(remote_path)`** | **One** file as a **streaming** handle — process data while the download is in flight, without writing to disk. Supports chunk iteration and file-like `read()`. |
| **`download_many(files=...)`** | **Many** remote paths (dict of remote→local or list of remotes); parallel `download` calls; returns **`dict[remote, local]`** (only successes when `skip_errors`). |
| **`download_zip(remote_path, ...)`** | You want a **directory** as a **single ZIP** download. |

### Deletes

| Method | Use when |
|--------|----------|
| **`delete(remote_path)`** | Remove **one** object. |
| **`delete_many(remote_paths=[...])`** | Remove **many** objects in parallel. |

### Other

| Method | Use when |
|--------|----------|
| **`signed_url(remote_path, upload=False/True)`** | You need the raw **presigned URL** yourself (custom client, browser, `curl`, etc.). |
| **`health()` / `version()`** | Service checks or debugging. |

---

::: src.platform.files.Files
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

::: src.platform.files.FileStream
    options:
      heading_level: 2
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      members_order: source
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true
