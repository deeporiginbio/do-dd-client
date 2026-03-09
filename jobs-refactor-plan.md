This document describes a proposed redesign of the client.

# Current design and user flow

```python

# user creates Proteins and Ligands
protein = Protein(...)
ligands = LigandSet(...)
ligand = ligands[0]

# find pockets
result = protein.find_pockets(...)
pocket = result.pockets[0]

# dock a single molecule (using functions)
result = protein.dock(pocket=pocket, ligand=ligand)
poses = result.poses

# view poses
protein.show(poses=poses)

# dock a large batch set of molecules
# to dock a large batch, we are forced to create a Complex object
sim = Complex(protein=protein, ligands=ligands)
jobs = sim.docking.run(pocket=pocket)
# jobs is of type JobList

# to view status, we inspect the JobList
jobs
# and/or
jobs.status

# to view results (when complete, we need to):
poses = sim.docking.get_poses()
protein.show(poses=poses)
# note: no way to get results from a job

# prepare a system
# the only way to prepare a system is to use a Complex
result = sim.prepare(ligand=ligands[0])
system = result.prepared_systems[0]
system.show()

# quote an ABFE
# there's a hidden dependency on system preparation here
# a system must be prepared in order to quote a ABFE job
jobs = sim.abfe.run(ligand=ligands[0], quote=True)

# start an ABFE run
jobs.confirm()

# (coming back after another a day, in a new python session )
# retrieve past jobs/results
# note that if we want to see the results and status of the jobs we ran,
# the natural thing to do is to first find the Jobs, and try to get results...
jobs = JobList.list(tool_key="deeporigin.abfe-end-to-end", ...)
# need to filter jobs and inspect to check if they're complete
# but now we have no direct way of getting the results
# we are forced to re-create the Complex object to use the helper methods:
# like:

sim = Complex(protein=protein, ligands=ligands)
results = sim.abfe.get_results()
```

## Shortcomings and weaknesses

- Single-ligand and multi-ligand docking use different APIs (`Protein.dock(...)` vs `Complex.docking.run(...)`), which creates an inconsistent user journey for very similar tasks.
- Bulk docking is job-oriented (`JobList`) while single docking is result-oriented (`FunctionResult.poses`), so result retrieval patterns differ substantially across scale.
- Bulk docking result retrieval is not explicitly keyed by selected job IDs in the primary helper path (`sim.docking.get_poses()` / `sim.docking.get_results()`), which weakens job-to-result traceability.
- ABFE has a strict hidden dependency on prior system preparation; `sim.abfe.run(...)` fails unless each ligand hash exists in the in-memory `sim._prepared_systems`.
- Prepared-system state is stored on the `Complex` instance only, so returning in a new Python session breaks continuity unless the user re-prepares or reconstructs state.
- Recovering ABFE results from historical jobs is indirect: users can list/filter `JobList`, but the convenient result table is exposed via `sim.abfe.get_results()` and depends on reconstructing matching `Complex` context.
- Quoting and execution control have branching behavior (`quote=True` + `confirm()` on `Job`/`JobList`) that is powerful but increases cognitive overhead in common end-to-end workflows.
- Terrible "next day" ergonomics -- when a user starts something and comes back the next day to view results, UX is clunky and confusing

# Proposed redesign

We leverage the fact that `Protein` and `Ligand` objects have IDs, and the system is aware of them (client+platform). We can therefore refer to these objects by ID, and don't have to mess around with hashes.

## Class skeletons

On the platform side, executions come in two modes: sync (functions) and async (long-running tools).
Different tools expose different capabilities: some are sync-only (e.g. `PocketFinder`), some are async-only (e.g. `ABFE`), and some support both (e.g. `Docking`).
We use mixins to represent these capabilities in one unified client API, so classes compose only the execution behaviors they actually support.

### PlatformStatus

```python
PlatformStatus = Literal[
    "Quoted",
    "Created",
    "Queued",
    "Running",
    "Succeeded",
    "Failed",
    "Cancelled",
    "InsufficientFunds",
    "FailedQuotation",
]
```

### JobBase

```python
class JobBase():
    # ----- user-visible read-only attributes -----
    # Users cannot assign these directly. They are mutated only by lifecycle methods.
    id: str | None
    estimate: float | None
    cost: float | None

    tool_key: str
    tool_version: str

    # ----- internal mutation gate -----
    _internal_write: bool
    _allowed_transitions: dict[str, set[str]]

    def __setattr__(self, name, value):
        """Block direct user writes to read-only public fields."""
        ...

    @contextmanager
    def _system_update(self):
        """Allow internal, scoped mutation in lifecycle methods only."""
        ...

    def _set_status(self, new_status: str):
        """Validate and apply state transition."""
        ...
```

### QuoteMixin

```python
class QuoteMixin():
    def quote(self):
        """Mode-agnostic quote.

        For async classes, may set status=Quoted.
        For sync-only classes, updates estimate only.
        """
        ...
```

### SyncExecutableMixin

```python
class SyncExecutableMixin():
    def run(self):
        """Synchronous, blocking execution."""
        raise NotImplementedError
```

### JupyterVizMixin

```python
class JupyterVizMixin():
	 def __repr__(self):
	     """viz functions for showing this job object in jupyter notebooks"""
	     raise NotImplementedError
```

### AsyncExecutableMixin

```python
class AsyncExecutableMixin():
    # status contract for async-capable classes:
    # - None before execution is created
    # - PlatformStatus once execution exists
    status: PlatformStatus | None

    def start(self):
        """Allowed before execution is started, or from Quoted. Assigns ID and starts execution."""
        ...

    def cancel(self):
        """Allowed from Created/Queued/Running."""
        ...

    def refresh(self):
        """Sync status/cost/estimate from platform."""
        ...

    @classmethod
    def from_id(cls, id: str) -> Self:
        """Construct from an existing execution ID."""
        ...

    @classmethod
    def list(cls) -> "JobList":
        """List jobs from platform (generic)."""
        ...
```

### JobList

```python
class JobList():
    jobs: list[JobBase]

    @classmethod
    def list(cls) -> Self:
        """get list of jobs from API"""
        ...

    def filter(self, ...) -> Self:
        """filter function, supports method chaining"""
        ...
```

### PocketFinder

```python
class PocketFinder(JobBase, QuoteMixin, SyncExecutableMixin):
    """Pocket finder supports sync execution only."""

    tool_key = "deeporigin.pocketfinder"
    tool_version = "0.1.0"

    # immutable
    protein: Protein
    

    def quote(self):
        """Uses functions API for quote; does not mutate status."""
        ...

    def run(self) -> list[Pocket]:
        """blocking execution"""
        ...
```

### Docking

```python
class Docking(JobBase, QuoteMixin, SyncExecutableMixin, AsyncExecutableMixin):
    """Docking supports both sync and async execution paths."""

    tool_key = "deeporigin.bulk-docking"
    tool_version = "0.2.0"

    # immutable user config (set in constructor only)
    smiles_list: list[str] | None
    protein: Protein
    ligands: LigandSet | None
    pocket: Pocket

    def run(self) -> LigandSet:
        """run docking using sync blocking execution"""
        ...

    def get_results(self) -> LigandSet:
        ...
        
        
    def get_top_results(self, filter_by...) -> LigandSet:
       ...
```

### ABFE

```python
class ABFE(JobBase, QuoteMixin, AsyncExecutableMixin):
    """ABFE supports async execution."""

    tool_key = "deeporigin.abfe-end-to-end"
    tool_version = "0.2.0"

    # immutable user config (set in constructor only)
    protein: Protein
    ligand: Ligand

    # system-managed fields (read-only to user, mutable internally)
    solvation_xml_path: str | None
    binding_xml_path: str | None

    def prepare(self):
        # allowed before execution is started; internally sets xml paths
        ...

    def get_results(self) -> pd.DataFrame:
        ...
```

## Execution semantics

This API supports two execution modes:

- `run()`: synchronous + stateless (e.g. Functions)
    - sends a blocking request to a sync execution route
    - returns results directly in the response
    - does **not** create a persisted execution record
    - does **not** assign an execution ID
    - does **not** mutate object lifecycle state
    - cannot be retrieved/recovered later via `list()` / `from_id()`
- `start()`: asynchronous + stateful
    - `start()` submits a persisted execution to the platform
    - assigns execution ID
    - status can be refreshed/polled
    - result can be retrieved later via `list()` / `filter()` / `from_id()` + `get_results()`

`quote()` is mode-agnostic and supported in both modes:

- before `run()`: quote a synchronous execution
- before `start()`: quote an asynchronous execution

Important:

- `run()` is **not** implemented as `start()+wait()+get_results()`.
- It may use a different backend API route/code path.

Recoverability rule:

- Use `quote()` / `start()` when execution traceability or later retrieval is required.

## User Flows

### Pocket finder

Pocket finder is a tool that MUST run in a blocking/sync fashion. It takes <2 min to run.

```python
pf = PocketFinder(protein)

# get a quote/estimate so i know how much it's going to cost
pf.quote()
pf.estimate # contains the estimate
pf.cost # None

# now run it
pockets = pf.run() # blocking
pf.estimate # last estimate may be kept as reference
pf.cost # contains actual cost

# status/from_id are not supported for sync-only classes
pf.status # not available (AttributeError)
PocketFinder.from_id("...") # not available (AttributeError)
```

### Docking

```python

docking = Docking(protein=protein, ligands=ligands, pocket=pocket)

# dock a single molecule (using sync function)
poses = docking.run() # this is a blocking execution

# view poses
protein.show(poses=poses)

# get an estimate on how much it would cost
docking.quote()
docking.estimate

# start it
docking.start()

# to view status
docking.status # may have to do docking.refresh()

# cancel if (if needed)
docking.cancel()

# get results
poses = docking.get_results()

# get results 
docking.get_results()

# show results
docking.show_results() # a wrapper around `protein.show(poses=poses)`

# how much did it cost?
docking.cost # actual cost incurred

# it's assigned an ID which can be tracked
docking.id

# next day ergonomics
docking = Docking.from_id(docking_id)
# from_id rehydrates the object, fetching Protein and Ligand objects
# from the platform. it can do so because the execution record contains IDs of proteins
# and ligands, and that allows it to reconstitute those entities

poses = docking.get_results()
```

### Guardrails and checks

```python
# constructing a DockingJob from entities will ALWAYS create a new instance with no platform execution backing it
docking = Docking(protein=protein, ligands=ligands, pocket=pocket)
docking.status # None (no platform execution yet)
docking.id # not be set
docking.cancel() # will raise an error, no job behind this
docking.get_results() # raise an error, no job, no ID, no status
docking.estimate # will be None

# mutating input attributes not allowed
docking.protein = new_protein # not allowed
docking.ligands = new_ligands # not allowed
docking.pocket = None # not allowed

docking.protein # inspecting attributes allowed
docking.id # unset, because this hasn't been started yet
docking.cost # unset, because this hasn't finished

# make a Job from an ID (so it exists on the platform in some state)
docking2 = Docking.from_id(...)
docking2.status # will have some status
docking2.cancel() # allowed if it's running

# mutating input attributes not allowed
docking2.protein = new_protein # not allowed
docking2.ligands = new_ligands # not allowed
docking2.pocket = None # not allowed
```

### User flows -- ABFE

```python

# make an ABFE job
abfe = ABFE(protein=protein, ligand=ligand)

# prepare the system
abfe.prepare()

# get a quote
abfe.quote()
abfe.estimate

# start the run
abfe.start()

# starting assigns an ID
abfe.id # this can be noted down for later

# next-day ergonomics:
#
# 1. get all completed ABFE runs
jobs = ABFE.list().filter(status="Succeeded")
#
# 2. get the jobs for the protein and ligand of interest
jobs = ABFE.list().filter(protein_id=protein_id, ligand_id=ligand_id)
#
# 3. from ID
abfe = ABFE.from_id(saved_id)

# get results
results = abfe.get_results()
```