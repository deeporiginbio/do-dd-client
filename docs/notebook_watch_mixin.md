# Notebook watch (ABFE and other async executions)

`NotebookWatchMixin` adds `watch()`, `watch_async()`, `stop_watching()`, and `show()` for live HTML updates in Jupyter while polling the platform. It reuses the same rendering as the legacy `Job` widget and does **not** use `nest_asyncio`.

- **Non-blocking cell (like legacy `Job.watch()`):** `task = await abfe.watch()` — the cell returns immediately; the widget keeps updating while you run other cells.
- **Block until the job finishes:** `await abfe.watch_async()` — the cell does not finish until the execution reaches a terminal state.
- **Scripts:** `asyncio.run(abfe.watch_async())` to block until finished. For a background-style script, use an `async def main()` that `await`s `watch()` then `await task`, and run that with `asyncio.run(main())`.

See also: [ABFE tutorial](dd/tutorial/abfe.md).
