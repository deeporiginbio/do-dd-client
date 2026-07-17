---
name: make-viz
description: Generate or update the standalone Mol* visualization HTML files under docs/images/ that the docs embed via <iframe>. Use when adding, updating, or migrating a molecular visualization (protein, pockets, ligands, docked poses, docking box, trajectory) shown in the CLI docs, or when a docs/images/*.html viewer needs regenerating after a viz-engine change.
---

# make-viz — docs Mol* visualizations

The CLI docs embed 3D molecular viewers as standalone HTML files in
`docs/images/*.html`, referenced from Markdown with an `<iframe>`:

```html
<iframe
    src="../../images/brd-protein.html"
    width="100%"
    height="630"
    style="border:none;"
    title="Protein visualization"
></iframe>
```

Each `docs/images/*.html` file is a single `<iframe src="data:text/html;base64,…">`
tag — the exact markup a Jupyter cell emits when you call `.show()` on a
structure. This skill produces those files **without** the manual
notebook → nbconvert → copy-the-iframe round trip.

## How the viewers are built (the engine)

`.show()` methods (e.g. `Protein.show()`, `Ligand.show()`) build a complete,
self-contained HTML document with one of the builders in
`src/viz/molstar_html.py`, then wrap it in an iframe via
`render_html()` (`src/utils/notebook.py`). The current engine is the hosted
`molstarLib` bundle (`molstarLib.initViewer` / `loadFromRawContent`), which
replaced the legacy `deeporigin-molstar` engine (`renderStructureExplicitly`).

Key builders in `deeporigin.viz.molstar_html` (all return a full HTML document):

| Builder | Viewer |
|---|---|
| `render_protein_html` | protein only |
| `render_protein_with_pockets_html` | protein + binding pockets |
| `render_ligand_html` | single ligand (SDF) |
| `render_protein_with_poses_html` | protein + docked poses |
| `render_protein_with_pockets_and_poses_html` | protein + pockets + poses |
| `render_docking_box_html` | protein + docking search box |
| `render_protein_with_box_and_poses_html` | protein + box + poses |

`render_html(document_html, height=H, return_iframe_string=True)` returns the
iframe string to write into `docs/images/<name>.html`.

See `docs/notebooks/clean/molstar-visualization-catalog.ipynb` for the full
catalog and migration status of every viewer.

## Preferred workflow: the generator script

`scripts/build_docs_viz.py` is the single source of truth for how each docs
image is produced. It holds a `VIZ_REGISTRY` mapping a docs-image name to a
builder call and iframe height, and writes `docs/images/<name>.html`.

```bash
# from the repo root
uv run python skills/make-viz/scripts/build_docs_viz.py --list
uv run python skills/make-viz/scripts/build_docs_viz.py brd-protein
uv run python skills/make-viz/scripts/build_docs_viz.py brd-protein brd-pocket
```

### Add or update a visualization

1. **Add a registry entry.** In `scripts/build_docs_viz.py`, write a
   `_build_<name>()` function that returns a full HTML document from a
   `molstar_html` builder, then register it:

```python
def _build_brd_protein() -> str:
    from deeporigin.viz.molstar_html import render_protein_html
    return render_protein_html(pdb_path=_brd_pdb())

VIZ_REGISTRY["brd-protein"] = VizSpec(build=_build_brd_protein, height=600)
```

   Use bundled example data (`BRD_DATA_DIR`) or repo test fixtures
   (`tests/fixtures/…`) as inputs so generation needs no network or live org.

2. **Generate the file:**
   `uv run python skills/make-viz/scripts/build_docs_viz.py <name>`

3. **Verify it decodes to the current engine** (not the legacy one):

```bash
uv run python -c "import base64,re,pathlib; \
s=pathlib.Path('docs/images/<name>.html').read_text(); \
h=base64.b64decode(re.search(r'base64,([^\"]+)',s).group(1)).decode(); \
print('molstarLib', 'molstarLib' in h); \
print('legacy', 'renderStructureExplicitly' in h)"
```

   Expect `molstarLib True` and `legacy False`.

4. **Visually confirm** by opening the file in a browser, or by running the
   matching cell in `molstar-visualization-catalog.ipynb`. The hosted
   `molstarLib` bundle loads over the network, so the viewer needs internet to
   render (the generated HTML itself is self-contained apart from the bundle).

5. **Embed in the docs.** Reference the file from the relevant Markdown page
   (path is relative to the page; tutorial pages use `../../images/<name>.html`).
   Set the outer iframe `height` a little larger than the builder height (the
   docs use `height=630` for a 600px viewer) so nothing is clipped.

### Choosing the iframe height

Match the existing convention: 600 for most viewers, 800 for large MD
trajectories. The outer `<iframe height=…>` in the Markdown should be ~30px
taller than the builder height.

## Fallback: manual notebook workflow

Only use this if a viewer is not yet exposed by a `molstar_html` builder (e.g. a
legacy `LigandSet.show()` multi-molecule view):

1. Create a dirty notebook `docs/notebooks/dirty/<name>.ipynb` (gitignored;
   never edit `docs/notebooks/clean/` directly — see the repo rules).
2. Add a cell that calls the relevant `.show()` and produces the viewer.
3. Export: `uvx jupyter nbconvert --to html --no-input docs/notebooks/dirty/<name>.ipynb`.
4. From the exported HTML, copy the single `<iframe …></iframe>` element for the
   viewer into `docs/images/<name>.html`.
5. Embed and verify as above.

Prefer adding a `molstar_html` builder + a registry entry over this manual path
whenever possible — it makes the docs image reproducible with one command.

## Anti-patterns

- Do **not** hand-edit the base64 blob inside a `docs/images/*.html` file —
  regenerate it.
- Do **not** create or edit notebooks in `docs/notebooks/clean/` directly.
- Do **not** leave a docs image on the legacy `renderStructureExplicitly`
  engine when a `molstarLib` builder exists — migrate it.
