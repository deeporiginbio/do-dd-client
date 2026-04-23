# `SyncFunctionResponses`

Synchronous calls to the platform ``functions.run`` API return a `SyncFunctionResponses` object. It wraps one or more raw JSON payloads and exposes **status**, **id**, **estimate**, **cost**, and **function_outputs** accessors. Batch helpers (for example docking multiple ligands in a loop) aggregate multiple responses in one instance and sum costs and estimates when every response is in a consistent billing state.

For higher-level workflow classes (`Docking`, `PocketFinder`, `SystemPrep`, `Molprops`, `Protonation`), prefer the execution object’s own fields (`estimate`, `cost`, `id`) and domain return types from `run()` where applicable.

:::: deeporigin.drug_discovery.sync_function_responses.SyncFunctionResponses
