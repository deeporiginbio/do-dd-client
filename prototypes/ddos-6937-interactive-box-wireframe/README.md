# PROTOTYPE — DDOS-6937 Interactive docking box wireframe

**Throwaway.** Do not import from production code. Validates the notebook iframe →
molstar box → Apply → Python Comm bridge before full SDK / molstarLib work.

**Question:** Does the postMessage + `ipykernel.comm.Comm` bridge deliver a
`rotation_deg` payload to Python after the user adjusts an interactive molstar box?

## Run

From the `do-dd-client` repo root (JupyterLab or VS Code notebook):

```bash
make prototype-ddos-6937
```

Or open `wireframe.ipynb` manually and run all cells.

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
| `comm_bridge.py` | Portable Comm + postMessage bridge (candidate for `notebook.py`) |
| `interactive_box_html.py` | Iframe HTML with molstar + Apply overlay |
| `wireframe.ipynb` | Two-cell manual smoke test |

Branch: `research/DDOS-6937-interactive-box-wireframe` (throwaway; not merged to main).
