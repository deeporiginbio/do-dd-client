# Notebook watch (ABFE and other async executions)

> **Deprecated:** The legacy `deeporigin.platform.job` module was removed; the old `Job.watch()`-style flow described in comparisons below refers to that API, now implemented under `deeporigin.platform.tool_jobs`.

`NotebookWatchMixin` adds `watch()`, `stop_watching()`, and `show()` for live HTML updates in Jupyter while polling the platform. Executions rehydrated with `from_id` / `from_dto` get the same watch-related instance state as objects constructed with `__init__`. The HTML view is built with [`ExecutionDisplay`](platform/ref/execution_display.md) (Bootstrap card: progress bar from `progressReport.complete`, execution id, name, status). It does **not** use `nest_asyncio`.

- **Non-blocking cell (like legacy `Job.watch()`):** `task = await abfe.watch()` — the cell returns immediately; the widget keeps updating while you run other cells.
- **Block until the job finishes:** use the execution object's `wait()` method.
- **Scripts:** use `wait()` to block until finished. For a background-style script, use an `async def main()` that `await`s `watch()` then `await task`, and run that with `asyncio.run(main())`.

See also: [ABFE tutorial](dd/tutorial/abfe.md).
