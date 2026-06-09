# Tools on Deep Origin

Deep Origin tools are available through small Python classes that wrap platform
executions. Each class represents one tool, such as [`PocketFinder`](../ref/pocket_finder.md)
or [`Docking`](../ref/docking.md), and provides a consistent way to prepare
inputs, estimate cost, submit work, and retrieve results.

Some tools finish quickly and can be run synchronously. Others may run for
longer and are better submitted asynchronously, so your notebook or script can
continue while the execution runs on Deep Origin.

## Common workflow

Most tool classes follow the same lifecycle:

1. Create a tool object with the required inputs.
2. Estimate cost with `run(quote=True)` or `start(quote=True)`.
3. Confirm the execution when required.
4. Run immediately with `run()`, or submit asynchronously with `start()`.
5. Track progress with `watch()` or wait for completion with `wait()`.
6. Retrieve results from the completed execution.

For example, a tool usually starts with a local object:

```{.python notest}
tool = SomeTool(...)
tool.run(quote=True)
tool.estimate # contains estimate
tool.confirm()
result = tool.get_results()
```

After `run(quote=True)`, inspect `tool.estimate` to review the estimated cost
before confirming the execution.

For long-running tools, use the asynchronous flow:

```{.python notest}
tool = SomeTool(...)
tool.start()
tool.wait()
result = tool.get_results()
```

The exact inputs and result types depend on the tool. See the individual tool
pages for examples.

## Working with existing executions

Tool objects can also be reconstructed from executions that already exist on
the platform. This is useful when you want to inspect a previous run, reconnect
to an in-progress execution, or fetch results in a later session.

```{.python notest}
# By execution id:
tool = SomeTool.from_id("<executionId>")

# Or resume the most recently created run of this tool type:
tool = SomeTool.from_last_run()

tool.sync()
result = tool.get_results()
```

Most tool classes also provide a way to list previous executions for that tool.

## API surface

The commonly available methods are:

- `run(quote=True)` or `start(quote=True)` estimates cost before running.
- `run()` submits and waits for a synchronous result, when supported.
- `start()` submits an asynchronous execution and returns immediately.
- `wait()` waits for an asynchronous execution to complete.
- `watch()` displays progress for tools that report progress.
- `sync()` refreshes the local object from the platform.
- `cancel()` cancels an asynchronous execution, when supported.
- `get_results()` retrieves outputs after completion.
- `from_id()` reconstructs a tool object from an execution ID.
- `from_last_run()` reconstructs a tool object from the most recently created
  execution of that tool type.

Not every method is available on every tool. The tool-specific pages document
the supported execution modes, inputs, outputs, and examples.