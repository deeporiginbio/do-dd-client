# Notebook watch (ABFE and other async executions)

`NotebookWatchMixin` adds `watch()`, `stop_watching()`, and `show()` for live HTML updates in Jupyter while polling the platform. Executions rehydrated with `from_id` / `from_dto` get the same watch-related instance state as objects constructed with `__init__`. The HTML view is built with [`ExecutionDisplay`](platform/ref/execution_display.md) (Bootstrap card with execution id, name, status, and progress). When the tools API returns a v2 `progressReport` tree, the card body shows an indented HTML/SVG step tree with per-node status colors and optional completion rings; legacy flat `complete` shapes still use the Bootstrap progress bar. It does **not** use `nest_asyncio`.

- **Non-blocking cell (default):** `task = await abfe.watch()` — the cell returns immediately; the widget keeps updating while you run other cells.
- **Block until the job finishes (live widget):** `await abfe.watch(blocking=True)` or set `JOB_WATCH_BLOCK=1` (also `true`, `yes`, `on`; case-insensitive). Used by doc notebook CI (`scripts/build_docs.sh`) and `nbconvert --execute`.
- **Block without live widget:** use the execution object's `wait()` method.

See also: [ABFE tutorial](dd/tutorial/abfe.md), [job widget / `JOB_WATCH_BLOCK`](dev/job-widget.md).
