# DDOS-6931 — Jupyter iframe JS-to-Python communication patterns

**Ticket:** [DDOS-6931](https://deeporigin.atlassian.net/browse/DDOS-6931)  
**Status:** Research complete  
**Date:** 2026-08-03

## Problem

Wayfinder needs to read an adjusted **docking search box** (center, size, and
orientation) from an interactive Mol* viewer in a Jupyter notebook cell and use
that geometry in Python (e.g. before `Docking.run()` / constrained docking).

Today the SDK renders Mol* via `render_html()` — a base64 `data:` iframe with
`sandbox="allow-scripts allow-same-origin"`. That path is **one-way**
(Python → browser). There is no channel for the iframe to return box state to
the kernel.

## Current architecture

### `render_html()` (`src/utils/notebook.py`)

```python
# Simplified flow
iframe = f'<iframe src="data:text/html;base64,{b64}" sandbox="allow-scripts allow-same-origin" ...>'
display(HTML(iframe))  # Jupyter
# or mo.Html(iframe)   # marimo
```

Design choices that matter for bridging:

| Choice | Rationale | Bridge implication |
|--------|-----------|------------------|
| Base64 `data:` `src` (not `srcdoc`) | `srcdoc` is sandboxed without `allow-scripts`; Mol* JS would not run | Iframe is a **separate browsing context** from the notebook page |
| `allow-scripts allow-same-origin` | Mol* needs JS; same-origin allows some APIs inside the iframe doc | Parent ↔ iframe are **cross-origin** (`null` opaque origin for `data:` URIs) — must use `postMessage`, not direct DOM access |
| Trusted SDK-generated HTML only | Security model assumes we control iframe content | Bridge can validate message `type` / schema |

### `molstar_html.py` (`src/viz/molstar_html.py`)

Builds self-contained HTML documents that load the hosted `molstarLib` IIFE from
`https://os.dev.deeporigin.io/molstar/latest/index.js` and call
`molstarLib.initViewer()` + `viewer.api.*`.

Docking box today (`render_docking_box_html`, `render_protein_with_box_and_poses_html`):

- Axis-aligned box from Python `box_center` + `box_size` → min/max corners
- Calls `viewer.api.renderBoundingBox(structureRef, box, { radius, color })`
- **No interactive controls** in notebook HTML (no rotation sliders, no commit UI)

### Full UUI viewer vs notebook IIFE

In `platform-ui/packages/molstar`, `DockingBoxControls` provides geometry,
orientation (`rotX` / `rotY` / `rotZ`), and appearance editing. Rotation is
applied as a canvas transform on the box representation — it is **not** reflected
in the axis-aligned `bottomLeft` / `topRight` params alone.

Notebook HTML does **not** include `DockingBoxControls` (React/Mantine panels are
part of the UUI viewer spec, not the minimal IIFE init path). Any interactive
box editing in notebooks requires **new JS inside the generated HTML** (lightweight
controls and/or future `molstarLib` read APIs).

### Data the bridge must carry

Minimum payload for wayfinder (align with `DockingBoxControls` state and
`resolve_docking_box_geometry`):

```json
{
  "center": [x, y, z],
  "size": [sx, sy, sz],
  "rotation_deg": { "x": 0, "y": 0, "z": 0 },
  "min": [x0, y0, z0],
  "max": [x1, y1, z1]
}
```

Rotation semantics must be defined when wiring to docking tools — current
`build_pocket_tool_params` only sends axis-aligned `box_size_{x,y,z}` and pocket
center. Oriented boxes may need a follow-on platform/tool contract (out of scope
for this bridge research).

---

## Patterns evaluated

### 1. ipywidgets / AnyWidget comm

**How it works:** Custom widget model in Python; frontend widget bundle talks to
kernel via Jupyter widget comm (`@jupyter-widgets/base`).

| Pros | Cons |
|------|------|
| Mature, bidirectional, supports Lab + VS Code widgets | **New dependency** (`ipywidgets`, possibly `@anywidget` + npm build) |
| Rich UI state sync | Does **not** fit “generate HTML string → iframe” pattern |
| | Requires widget frontend asset pipeline in `do-dd-client` |
| | **marimo** support differs; not drop-in |
| | Overkill for a single “commit box geometry” action |

**Verdict:** Reject for minimal-deps goal. Revisit only if we need continuous
two-way sync (live sliders driving Python) across many viz types.

### 2. `IPython.display.Javascript` + kernel Comm

**How it works:**

1. Python opens an `ipykernel.comm.Comm` (stdlib with Jupyter; no ipywidgets).
2. Python `display(HTML(iframe))` — same as today.
3. Python `display(Javascript(...))` — parent-page script creates/forwards comm.
4. Iframe `window.parent.postMessage(payload)` on user action.
5. Parent script validates origin/source and `comm.send(payload)`.
6. Python `@comm.on_msg` handler updates a holder object / calls callback.

| Pros | Cons |
|------|------|
| **No new pip deps** (ipykernel already required for notebooks) | Two output blobs per cell (iframe + JS) |
| Keeps HTML generation in `molstar_html.py` | Requires small shared bridge JS (could live in `notebook.py`) |
| Explicit commit — user-driven, predictable | **marimo:** Comm not supported → needs fallback |
| Same pattern as many iframe-bridge notebooks | Parent script must **not** be embedded inside `HTML()` (see below) |

**Verdict:** **Recommended.**

### 3. `postMessage` only (inline script in `HTML()`)

**How it works:** Single `display(HTML('<iframe>…</iframe><script>…</script>'))`.

| Pros | Cons |
|------|------|
| One output | **JupyterLab HTML sanitizer strips `<script>` tags** from `text/html` outputs |
| | VS Code notebooks also restrict inline HTML scripts |
| | Iframe-internal scripts cannot access kernel Comm directly |

Iframe-internal JS **can** postMessage to parent, but the **parent listener**
must run in the notebook page — and that listener cannot reliably live inside
sanitized HTML.

**Verdict:** Reject as sole mechanism. Use `postMessage` **from iframe** plus
**separate** `Javascript` output for the parent listener.

### 4. Explicit commit button (clipboard / visible JSON)

**How it works:** Button inside iframe copies JSON or shows a code block; user
pastes into next cell.

| Pros | Cons |
|------|------|
| Works everywhere, zero kernel bridge | **Not programmatic** — breaks notebook automation |
| No Comm / CSP concerns | Poor UX for wayfinder workflows |
| Useful as **fallback** | Cannot `await` geometry in Python |

**Verdict:** Accept as **marimo / degraded fallback**, not primary pattern.

### 5. Polling / re-execute cell

**How it works:** User re-runs cell after editing; Python re-reads static inputs.

| Pros | Cons |
|------|------|
| Trivial | No true interactivity |
| | Does not solve orientation from viewer |

**Verdict:** Reject.

---

## Environment constraints

| Environment | iframe Mol* JS | Parent `<script>` in `HTML()` | `display(Javascript)` | `ipykernel.comm.Comm` | Notes |
|-------------|----------------|-------------------------------|------------------------|------------------------|-------|
| **JupyterLab** | ✅ | ❌ stripped | ✅ | ✅ | Primary target |
| **Classic Notebook** | ✅ | ⚠️ sometimes works | ✅ | ✅ | Prefer JS display for consistency |
| **VS Code notebooks** | ✅ | ❌ restricted | ✅ (with Jupyter ext) | ✅ for widget comm | Test on `@lv2` matrix; no `Jupyter.notebook` global — use Comm created from Python |
| **marimo** | ✅ via `mo.Html` | N/A | ❌ | ❌ | Read-only viewer or clipboard fallback |
| **nbconvert `--execute`** | ✅ static render | N/A | ⚠️ no user interaction | ⚠️ | Interactive commit N/A in CI |

References in-repo:

- `get_notebook_environment()` — `marimo` | `jupyter` | `other`
- `docs/dev/job-widget.md` — cross-environment HTML via Shadow DOM (one-way display only; no kernel callback)

---

## Recommendation

**Use: iframe `postMessage` + parent `IPython.display.Javascript` + `ipykernel.comm.Comm`.**

This is the single pattern that:

1. Preserves the existing `render_html()` / `molstar_html.py` architecture
2. Adds **zero new pip dependencies** for notebook users
3. Works in JupyterLab and VS Code (with separate JS output, not inline HTML scripts)
4. Supports an explicit **“Apply to notebook”** commit (avoids flooding the kernel)
5. Keeps untrusted-script surface limited to SDK-generated iframe + one small bridge script

### Proposed API shape (follow-up implementation)

```python
# src/utils/notebook.py (sketch)
def render_html_with_comm(
    html: str,
    *,
    comm_target: str,
    on_message: Callable[[dict], None],
    height: int = 600,
) -> CommBridgeHandle:
    """Display iframe HTML and register a one-shot / multi Comm handler."""
```

```python
# Usage in Docking.show_box_interactive() (future)
handle = render_html_with_comm(
    render_docking_box_html(..., interactive=True),
    comm_target="deeporigin.molstar.docking_box",
    on_message=lambda msg: setattr(docking, "_box_override", msg),
)
# User clicks "Apply" in iframe → on_message fires with geometry dict
```

### Bridge layout

```
┌───────────────────────────────────────────── Notebook cell output ────┐
│  [1] text/html: <iframe src="data:...">  ← molstar_html document     │
│  [2] application/javascript:                                           │
│        window.addEventListener("message", …)                         │
│        comm.send({ content: { data: payload } })  ← ipykernel Comm   │
└──────────────────────────────────────────────────────────────────────┘
         ▲ postMessage({ type, payload })
         │ (iframe.contentWindow)
┌────────┴────────────────────────────────── iframe document ──────────┐
│  molstarLib viewer + box controls + [Apply to notebook] button       │
└──────────────────────────────────────────────────────────────────────┘
```

### Message contract

```javascript
// iframe → parent
window.parent.postMessage({
  type: "deeporigin:docking-box-commit",
  bridge_id: "<uuid>",   // matches iframe data-bridge-id / comm metadata
  payload: {
    center: [number, number, number],
    size: [number, number, number],
    rotation_deg: { x: number, y: number, z: number },
    min: [number, number, number],
    max: [number, number, number],
  },
}, "*");  // parent validates event.source === iframe.contentWindow
```

Parent bridge must:

- Ignore messages whose `event.source` is not the paired iframe's `contentWindow`
- Ignore unknown `type` values
- Optionally debounce / reject malformed payloads before `comm.send`

### Changes by layer

| Layer | Change |
|-------|--------|
| `src/utils/notebook.py` | Add `render_html_with_comm()` (or optional `comm_target` on `render_html`); generate `bridge_id`; register Comm; emit `Javascript` bridge |
| `src/viz/molstar_html.py` | Add `interactive=True` to docking box builders: minimal UI (sliders + Apply), read box state from plugin, `postMessage` on commit |
| `platform-ui/packages/molstar` (optional) | Export `getDockingBoxState(viewer)` on `molstarLib` to avoid duplicating `DockingBoxControls` logic in generated HTML |
| `Docking` / `ConstrainedDocking` | New `show_box_interactive()` or parameter on `show_box`; store committed geometry on instance for `run()` |
| Tests | Unit-test message schema + Comm handler in isolation (no browser); manual catalog notebook section |
| marimo | Keep read-only `render_html()`; document clipboard fallback if interactive editing is added later |

### Security notes

- Only SDK-generated iframe documents may emit commits (trusted content).
- Parent bridge validates `event.source` and message schema.
- Do not use `eval` or inject user strings into the bridge script — pass `bridge_id` via JSON-encoded literals only.
- Keep `referrerpolicy="no-referrer"` on iframe (existing).

---

## Alternatives considered but not chosen

| Pattern | Why not primary |
|---------|-----------------|
| ipywidgets | Dependency + build overhead; mismatched with HTML-string viz pipeline |
| Inline HTML `<script>` | Stripped in JupyterLab / VS Code |
| Clipboard-only commit | Not programmatic; bad for wayfinder |
| Custom element / Shadow DOM (job-widget style) | Good for one-way HTML; still needs Comm for Python callback |

---

## Open questions (implementation tickets)

1. **Tool contract:** Does the docking tool accept oriented boxes, or only
   axis-aligned center + extents? Rotation may be visualization-only until
   platform supports it.
2. **molstarLib API:** Should box state/readback live in `platform-ui` (preferred)
   or be duplicated in `molstar_html.py` inline JS?
3. **Persistence:** Should committed geometry live on `Docking` instance, a module
   variable, or a `@user_setting`-style helper?
4. **VS Code QA:** Add a manual step to the molstar catalog notebook for VS Code
   interactive commit.

---

## References

- `src/utils/notebook.py` — `_iframe_src_for_html_document`, `render_html`
- `src/viz/molstar_html.py` — `render_docking_box_html`
- `design-docs/01-molstar-visualization-inventory.md` — viz inventory
- `platform-ui/packages/molstar/src/components/docking-box-controls.tsx` — orientation state model
- `docs/adr/0001-docking-box-without-exported-box3d.md` — duck-typed Box3D in notebook HTML
