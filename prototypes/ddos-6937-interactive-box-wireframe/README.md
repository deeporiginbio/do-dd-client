# PROTOTYPE — DDOS-6937 Interactive docking box wireframe

**Throwaway.** Do not import from production code. Validates the notebook iframe →
molstar box → Apply → Python AnyWidget bridge before full SDK / molstarLib work.

**Question:** Does an AnyWidget-hosted iframe deliver a `rotation_deg` payload to
Python after the user adjusts an interactive molstar box in both JupyterLab and
Cursor/VS Code?

The earlier arbitrary output JavaScript + raw `ipykernel.comm.Comm` attempt is
rejected: modern notebook frontends do not expose their kernel to output scripts.

## Run

From the repo root (JupyterLab or VS Code notebook, using this package's `.venv`):

```bash
make jupyter-lab NOTEBOOK=prototypes/ddos-6937-interactive-box-wireframe/wireframe.ipynb
```

Or open `wireframe.ipynb` in that environment and run all cells.

## What to try

1. Run cell 1 — molstar viewer loads with protein + yellow docking box.
2. Click the **gear icon** (viewport toolbar) → **Settings** → expand **Docking Box**
   and rotate with sliders or canvas drag (same UI as platform-ui).
3. Optionally adjust the **wireframe rotation sliders** in the bottom overlay (stand-in
   until `viewer.api.getDockingBox()` ships in molstarLib).
4. Click **Apply to notebook** — cell output below should print the committed dict
   with `center`, `box_size`, and `rotation_deg`.

## Artifacts

| File | Role |
|------|------|
| `comm_bridge.py` | AnyWidget + postMessage bridge (candidate for `notebook.py`) |
| `interactive_box_html.py` | Iframe HTML with molstar + Apply overlay |
| `wireframe.ipynb` | Two-cell manual smoke test |

Branch: `research/DDOS-6937-interactive-box-wireframe` (throwaway; not merged to main).
