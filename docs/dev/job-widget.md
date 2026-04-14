# Job widget (Shadow DOM)

> **Deprecated:** The legacy `deeporigin.platform.job` module was removed; job widgets are implemented in `src/platform/tool_jobs.py` (classes `Job` / `JobList`).

The job status widget is rendered via a single Shadow DOM-based template (`src/templates/job_widget.html`). This isolates CSS/JS so it works consistently across JupyterLab, classic Notebook, VS Code notebooks, marimo, and web front-ends.

Key details:

- Uses a custom element `do-job-widget` which attaches an open shadow root.
- Loads Bootstrap 5 (CSS) inside the shadow via CDN, avoiding conflicts with legacy Bootstrap shipped by notebooks.
- Tabs are implemented with a small vanilla JavaScript controller inside the shadow; JavaScript is required.
- The Python code in `src/platform/tool_jobs.py` renders this template in all environments.

CSP and offline notes:

- By default, assets load from `https://cdn.jsdelivr.net`. If your environment has a strict CSP or is offline, vendor these assets and update the `<link>` in the template accordingly.

Usage:

- In Python: `Job.from_id("<execution_id>").show()` or `.watch()`.

## Blocking watch mode

By default, the `watch()` method on `Job` and `JobList` returns immediately after starting a background monitoring task, allowing execution to continue while the job status updates are displayed. This is ideal for interactive use in Jupyter notebooks.

For automated notebook execution (e.g., running notebooks top-to-bottom via scripts), you can enable blocking mode by setting the `JOB_WATCH_BLOCK` environment variable to a truthy value. When enabled, `watch()` will block until the job (or all jobs in a `JobList`) reaches a terminal state.

The following values are considered truthy (case-insensitive): `1`, `true`, `yes`, `on`. All other values (including `0`, `false`, `no`, `off`, and empty strings) are treated as falsy.

Example:

```bash
export JOB_WATCH_BLOCK=1
python -m nbconvert --execute notebook.ipynb
```

To disable blocking mode, you can either unset the variable or set it to a falsy value:

```bash
# Unset the variable
unset JOB_WATCH_BLOCK

# Or set it to a falsy value like 0, false, no, or off
export JOB_WATCH_BLOCK=0
```

When `JOB_WATCH_BLOCK` is set, `watch()` will:
- Start the monitoring task as usual
- Block execution until the job reaches a terminal state (Succeeded, Failed, etc.)
- Return only after the job has completed

This ensures that automated notebook execution waits for jobs to complete before proceeding to the next cell.


