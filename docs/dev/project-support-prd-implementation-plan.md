# Project support in the DO Python client — implementation plan

This document summarizes the PRD [**Project Support in DO Python Client - PRD**](https://deeporigin.atlassian.net/wiki/spaces/PR/pages/685441037/Project+Support+in+DO+Python+Client+-+PRD) (Confluence, space PR) and proposes how to implement it in the `cli` repository. Revise this plan before engineering; several items depend on platform, data platform, UFA, and Mason work that is not owned by this repo alone.

---

## 1. PRD summary

### 1.1 Goal

Support a first-class **Project** concept in the Python client so users can **create, read, load, update, delete (TBD), and list** projects within their organization.

A project builds on the **Data Service** and is intended to include:

- A **unique project name/ID**
- A **unique Data Service table entry or tag** (e.g. for proteins, ligands, and other entities)
- **UFA-backed storage** (one UFA instance per org) for:
  - Outputs from tools, functions, and long-running Mason jobs
  - Parameters associated with those calculations
- **Metadata** about jobs run in a named project (who, when, result)
- An **executions** model/table for atomic, entity-aware runs

Users should create or open a project, run analyses, and have results **scoped to that project**. Each org has a **default project** (not explicitly user-named); work is associated with it unless the user selects another project.

The PRD also positions this as supporting **billing/auditing** and scientific organization.

### 1.2 Path / namespace notes (from PRD)

The PRD references evolving path conventions:

- Existing examples: `/tool-executions/{tool}/{protein_hash}/{ligand_hash}`, `/tool-executions/{execution-id}/`
- **Proposed**: `/{domain}/{op}/{tool}/{executionId}/{fileName}` (example: `/chem/extractions/do-patent/executionId/fileName`)

**Srinivas’s addition (PRD):** UFA should support a namespace where **tools may write**, **users may read**, but **users cannot write or delete**; suggest a **`/tool-executions`** root; tools should write under a **templated** path such as `/tool-executions/{execution-id}` with **`execution-id` supplied by Mason** when not overridden.

### 1.3 Functional requirements (condensed)

| Area | Expected behavior |
|------|-------------------|
| **Create** | e.g. `from deeporigin import projects` → `project = projects.create(name='…', load=True)`. Enforce **unique name** within org; optional **load in same call**. Creating a project implies a new **`subtable_tag`** (tag = project name) in Data Service; scoped work uses that tag. **Roles/permissions**: out of scope for this PRD. |
| **Load / read** | e.g. `project = projects.load(name='…')`, then `project.get_ligands()`, `project.get_proteins()`, etc. (illustrative). |
| **Update / usage** | After load/create, uploads and tool runs should **record results under the project**. PRD gives narrative examples (ligand tables, docking, dynamic columns). **All** platform work must be associated with **some** project (default or named). |
| **Durable storage** | Uploaded and created data copied into a **read-only** (from user perspective) area under a **DO-specified UFA location** per project/org for auditability. |
| **Executions table** | **Entity-aware** executions: track atomic executions (not only Mason job rows), with columns such as execution id, ligand/protein paths, parameters, job type, variant flag — for audit, failure analysis, data-service sync, and variant tracking. |
| **List** | e.g. `Projects.list_all()` → names; later **metadata** per project (created, updated, created by). |

### 1.4 PRD sections left blank

On the version retrieved (v11, 2026-03-17), **Potential Risks & Dependencies**, **Out of Scope & Potential Feature Enhancements**, and the **Project Plan** table were placeholders. Fill those in on Confluence as the design firms up.

---

## 2. Current state in `cli` (baseline)

This is a snapshot to align the plan with the codebase; it will drift.

| Capability | Today |
|------------|--------|
| **`DeepOriginClient.projects`** | [`Projects`](../../src/platform/projects.py) exposes **`list()`** only, calling `POST /data-platform/{org_key}/projects/search`. |
| **Public API style** | Primary entry is `from deeporigin.platform.client import DeepOriginClient` and namespaces like `client.entities`, `client.tools`, etc. The PRD’s `from deeporigin import projects` is **not** implemented as a top-level module yet. |
| **Client `tag`** | `DeepOriginClient` supports a **`tag`** used in **function** payloads (see [`functions.py`](../../src/platform/functions.py)), distinct from a full **project** model. |
| **Entities** | Ligand/protein flows can pass **`project_id`** in API-oriented code paths (see [`entities.py`](../../src/platform/entities.py)). |
| **Executions** | [`Executions`](../../src/platform/executions.py) wraps **tools-service** execution create/list/status — **job-level** tool runs, not the PRD’s separate **entity-aware executions registry**. |
| **Docs** | [`docs/platform/ref/projects.md`](../platform/ref/projects.md) documents listing projects only. |
| **Mock server** | Local mock implements **projects/search** with an empty list ([`data_platform.py`](../../tests/mock_server/routers/data_platform.py)). |

---

## 3. Design principles for the Python client

1. **Single active project context** — Most notebook and script flows should resolve “current project” without threading `project_id` through every call. Options: client-level **`project_id`** (or tag) analogous to `tag`, **context manager**, or **explicit** parameter on high-level APIs. Pick one primary pattern and document it.
2. **Default project** — Client must default to the org’s **default** project when the user has not set one; behavior must match backend semantics (create if missing vs fixed id).
3. **Backend-first** — CRUD, tagging, UFA paths, and executions persistence require **data-platform**, **file/UFA**, **tools/execution** services, and **Mason** contracts. The client should be a thin, typed wrapper over stable HTTP APIs.
4. **Compatibility** — Introduce project APIs without breaking existing code paths; deprecate or alias **`tag`** vs **project** if they converge.

---

## 4. Proposed implementation phases

Phases are ordered by dependency. Several phases are **blocked** until API contracts exist.

### Phase A — API contract & data model (platform; client participates)

- Finalize **project** resource: id, name, slug, org scoping, **default** flag, timestamps, created-by.
- Define how **Data Service** associates rows with a project (**`project_id`** vs **subtable_tag** vs both); align with existing entity columns.
- Define **list/create/get/update/delete** HTTP routes (or GraphQL if applicable) under data-platform.
- Document **error codes** (duplicate name, not found, forbidden).

**Client deliverable:** OpenAPI or internal spec reviewed; no large code until stable.

### Phase B — Minimal client CRUD + context

- Extend [`Projects`](../../src/platform/projects.py): **`create`**, **`get`/`load`**, **`list`** (enhanced), optional **`update`**, optional **`delete`** (per product decision on PRD question).
- Add **`project_id`** (or equivalent) to **`DeepOriginClient`** construction and/or setter, and propagate to:
  - **Entity** create/search when the API expects project scope
  - **Tool/function** payloads if the platform adds `projectId` / `projectTag`
- Decide top-level exports: either **`from deeporigin.platform.projects import …`** only, or implement **`from deeporigin import projects`** via `deeporigin/__init__.py` re-exports (package structure permitting).

**Tests:** Unit tests against mock server; extend mock routes for new endpoints.

**Docs:** Update [`docs/platform/ref/projects.md`](../platform/ref/projects.md) and tutorial “getting started” if needed.

### Phase C — Executions awareness (entity-level)

Depends on backend **executions** store described in the PRD (separate from tools-service job ids if needed).

- Add client methods to **record** or **query** entity-aware executions if the API is write/read from the client; if **server-side only**, add **read** helpers only.
- Link **tool execution id** ↔ **entity execution** rows for progress UI and debugging.

**Tests:** Fixtures for list/filter by project, ligand, protein.

### Phase D — UFA paths and file helpers

Depends on UFA **policy** (tool-writable, user read-only) and **canonical path templates**.

- Expose **resolved output paths** or **prefixes** on the client where the API returns them after job creation.
- Optionally add helpers to **download** or **open** read-only artifacts by execution id (wrapping existing [`Files`](../../src/platform/files.py) if applicable).

### Phase E — Drug-discovery ergonomics

- **`Project`**-like object with **`get_ligands` / `get_proteins`** if those are thin wrappers over **scoped entity search** (PRD examples).
- Ensure **docking / ABFE / notebook** flows pass **project context** consistently ([`execution_mixins`](../../src/drug_discovery/execution_mixins.py), etc.).

### Phase F — Polish

- **List with metadata** (`Projects.list_all` rich dict) once API returns it.
- **Migration guide**: from **`tag`**-only workflows to **project**-scoped workflows.
- Performance: caching project list, avoiding extra round-trips.

---

## 5. Cross-cutting concerns

| Concern | Plan |
|--------|------|
| **Auth / RBAC** | PRD defers; client should forward **403/404** clearly and avoid leaking existence across tenants. |
| **Billing / audit** | Largely server-side; client sends **project id** on billable operations as required by API. |
| **Mason / toolbox** | Align default output paths with **`/tool-executions/{execution-id}`** and domain-specific prefixes; coordinate with toolbox Docker/runner changes (**toolbox** repo). |
| **Deletion** | Product must decide whether **delete project** is allowed and whether it is soft-delete; client implements accordingly. |

---

## 6. Open questions (for review)

1. Should the user-facing API be **`deeporigin.projects`** vs **`DeepOriginClient().projects`** only? The PRD shows both styles; consistency matters.
2. Is **`subtable_tag`** exactly the **project name**, or a separate stable id with optional display name?
3. How does **`tag`** on **`DeepOriginClient`** relate to **project** — merge, deprecate, or keep for non-project use cases?
4. Single **executions** model: extend existing tools executions API or a new **data-platform** executions resource?
5. What is the **minimum viable** phase for release: **B only**, or **B + D** once UFA paths are live?

---

## 7. Suggested success criteria

- User can **set active project** and run at least one **entity + tool** flow with results **scoped** and **listable** under that project.
- **Default project** behavior matches backend and is covered by tests.
- Documentation and type hints allow IDE discovery of **`Projects.create` / `load` / `list`** (and equivalents).

---

## 8. References

- PRD: [Project Support in DO Python Client - PRD](https://deeporigin.atlassian.net/wiki/spaces/PR/pages/685441037/Project+Support+in+DO+Python+Client+-+PRD)
- Timeline link from PRD: [DDOS board timeline](https://deeporigin.atlassian.net/jira/software/c/projects/DDOS/boards/30/timeline)
