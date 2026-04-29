# `SyncFunctionResponses`

Synchronous calls to the platform **functions** API (``functions.run``) return a
`SyncFunctionResponses` object. It wraps one or more raw JSON payloads and
exposes **status**, **id**, **estimate**, **cost**, and **function_outputs**
accessors. Batch helpers aggregate multiple function responses in one instance.

Tools that use **``client.executions.create``** return execution DTOs instead;
those flows use :class:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin`
parsing (`quotationResult`, `executionId`, `status`) and do not go through
`SyncFunctionResponses`.

For higher-level workflow classes, prefer each execution object’s own fields
(`estimate`, `cost`, `id`) and domain return types from `run()` where applicable.
`Molprops` and `Protonation` may still use `SyncFunctionResponses` via the
functions API; `Docking`, `PocketFinder`, and `SystemPrep` use the executions
API.

::: deeporigin.drug_discovery.sync_function_responses.SyncFunctionResponses
