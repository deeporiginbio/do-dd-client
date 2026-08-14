# DDOS-6929: Audit molstarLib IIFE for interactive docking box controls

**Ticket:** Audit whether the hosted `molstarLib` IIFE used by CLI notebook embeds mounts
interactive docking-box UI, how rotation is applied, and what programmatic readback exists
today.

**Primary sources:**

- `/Users/srinivas/code/platform-ui/packages/molstar` — bundle source, UI components, API
- `/Users/srinivas/code/do-dd-client/src/viz/molstar_html.py` — notebook HTML generator

**Bundle entry:** `packages/molstar/src/index.ts` → esbuild IIFE with `globalName: 'molstarLib'`
(`esbuild.config.js`).

---

## 1. Does `initViewer()` mount SettingsPanel / DockingBoxControls in the IIFE?

**Yes — both are bundled and mounted, but the docking-box UI is hidden by default and only
appears after user interaction.**

### Mount chain

`molstarLib.initViewer(id)` creates a `MolstarViewer`, calls `init()`, which:

1. Builds a `PluginUISpec` via `createViewerSpec()` — registers `SettingsPanel` as the right
   layout region and `CustomViewportControls` as viewport controls.
2. Renders the full Mol* React `Plugin` tree into the container.

```5:8:platform-ui/packages/molstar/src/index.ts
const initViewer = async (id: string) => {
  const viewer = new MolstarViewer(id);
  await viewer.init();
  return viewer;
};
```

```43:61:platform-ui/packages/molstar/src/view/molstar-viewer.tsx
  async init(options?: ViewerOptions) {
    const mergedOptions = { ...options };

    const spec = createViewerSpec(mergedOptions);

    this.plugin = new PluginUIContext(spec);
    await this.plugin.init();
    // ...
    createRoot(this.container).render(
      <ThemeProvider>
        <Plugin plugin={this.plugin} />
      </ThemeProvider>
    );
  }
```

```57:71:platform-ui/packages/molstar/src/config/viewer-config.ts
        components: {
            ...defaultSpec.components,
            ...options?.spec?.components,
            remoteState: 'none',
            viewport: {
                ...defaultSpec.components?.viewport,
                controls: CustomViewportControls,
            },
            controls: {
                left: 'none',
                right: SettingsPanel,
                top: SequenceViewerPanel,
                bottom: 'none',
            },
        },
```

`SettingsPanel` renders `RepresentationControls`, which always includes `DockingBoxControls`:

```13:22:platform-ui/packages/molstar/src/components/settings-panel.tsx
export class SettingsPanel extends PluginUIComponent {
  render() {
    return (
      <div className="mol-settings-panel">
        <TrajectoryPlayer />
        <RepresentationControls />
        <Divider />
        <LigandFilters />
      </div>
    );
  }
}
```

```211:215:platform-ui/packages/molstar/src/components/representation-controls.tsx
        <Collapse in={isSectionOpen}>
          <Stack gap={0}>
            {components.map((c) => this.renderLayer(c))}
            <DockingBoxControls />
          </Stack>
```

### Visibility caveats for notebook embeds

| Layer | Default state | User action required |
|-------|---------------|----------------------|
| Right settings panel | `regionState.right: 'hidden'` | Click Settings icon in viewport toolbar |
| DockingBoxControls card | Renders `null` until `hasBox: true` | Call `viewer.api.renderBoundingBox(...)` first |

```44:54:platform-ui/packages/molstar/src/config/viewer-config.ts
        layout: {
            initial: {
                isExpanded: false,
                showControls: true,
                controlsDisplay: 'landscape',
                regionState: {
                    left: 'hidden',
                    right: 'hidden',
                    top: 'hidden',
                    bottom: 'hidden',
                },
            },
        },
```

```54:65:platform-ui/packages/molstar/src/components/custom-viewport-controls.tsx
  toggleSettingsPanel = (e?: React.MouseEvent<HTMLButtonElement>) => {
    const regionState = this.plugin.layout.state.regionState;
    PluginCommands.Layout.Update(this.plugin, {
      state: {
        regionState: {
          ...regionState,
          right: regionState.right === 'hidden' ? 'full' : 'hidden',
        },
      },
    });
```

```477:477:platform-ui/packages/molstar/src/components/docking-box-controls.tsx
    if (!hasBox) return null;
```

Box detection scans the Mol* state tree for cells whose transformer id equals
`ms-plugin.bounding-box-3d` (created by `renderBoundingBox`):

```89:96:platform-ui/packages/molstar/src/components/docking-box-controls.tsx
  private detectBox = () => {
    const cells = this.plugin.state.data.cells;
    let found = false;

    cells.forEach((cell, ref) => {
      if (cell.transform?.transformer?.id === BOUNDING_BOX_TRANSFORM_ID) {
        found = true;
        this.boxRef = ref;
```

**Conclusion:** Notebook embeds that call `render_docking_box_html` / `renderBoundingBox` get
the full interactive UI in the bundle. Users must open Settings → Docking Box section to
resize, recenter, rotate, or change appearance.

---

## 2. How is box rotation applied (`DockingBoxControls.applyRotation`)?

**Visual-only transform on the shape representation — not persisted to box geometry params.**

`applyRotation` builds a 4×4 matrix (translate to center → Rx → Ry → Rz → translate back) and
applies it directly to the representation object:

```320:349:platform-ui/packages/molstar/src/components/docking-box-controls.tsx
  private applyRotation = (degX: number, degY: number, degZ: number) => {
    if (!this.boxRef) return;

    const center = this.state.center;
    const radX = (degX * Math.PI) / 180;
    const radY = (degY * Math.PI) / 180;
    const radZ = (degZ * Math.PI) / 180;

    const negCenter = Vec3.negate(Vec3(), center);
    const toOrigin = Mat4.fromTranslation(Mat4(), negCenter);
    const rX = Mat4.fromRotation(Mat4(), radX, Vec3.create(1, 0, 0));
    const rY = Mat4.fromRotation(Mat4(), radY, Vec3.create(0, 1, 0));
    const rZ = Mat4.fromRotation(Mat4(), radZ, Vec3.create(0, 0, 1));
    const fromOrigin = Mat4.fromTranslation(Mat4(), center);

    const rot = Mat4.mul(Mat4(), rZ, Mat4.mul(Mat4(), rY, rX));
    const combined = Mat4.mul(
      Mat4(),
      fromOrigin,
      Mat4.mul(Mat4(), rot, toOrigin)
    );

    const cell = this.plugin.state.data.cells.get(this.boxRef);
    const repr = cell?.obj?.data?.repr;
    if (!repr) return;

    repr.setState({ transform: combined });
    this.plugin.canvas3d?.update(repr);
    this.plugin.canvas3d?.commit();
    this.plugin.canvas3d?.requestDraw();
  };
```

### Implications

- **`bottomLeft` / `topRight` in the state-tree transform params are unchanged** by rotation.
  Size/center edits go through `updateBoxParams` and rewrite those corners; rotation is
  re-applied afterward from React state if non-zero:

```162:180:platform-ui/packages/molstar/src/components/docking-box-controls.tsx
  private updateBoxParams = async (newParams: Record<string, any>) => {
    if (!this.boxRef) return;
    // ...
    await this.plugin.state.data
      .build()
      .to(this.boxRef)
      .update({ ...oldParams, ...newParams })
      .commit();

    if (
      this.state.rotX !== 0 ||
      this.state.rotY !== 0 ||
      this.state.rotZ !== 0
    ) {
      this.applyRotation(this.state.rotX, this.state.rotY, this.state.rotZ);
    }
  };
```

- The underlying mesh geometry remains an **axis-aligned** box from `getBoxMesh`; rotation is
  a canvas-level `repr` transform only.
- Interactive canvas drag rotation uses the same `applyRotation` path
  (`onWindowMouseMove`, lines 388–414).

---

## 3. Is rotation state readable programmatically today? Any API exports?

**No public API.** Rotation lives exclusively in `DockingBoxControls` React component state
(`rotX`, `rotY`, `rotZ`). Nothing is exported from `molstarLib` or `viewer.api` for box
orientation.

| State | Where stored | Readable via API? |
|-------|--------------|-------------------|
| Euler angles (deg) | `DockingBoxControls.state` | No |
| Axis-aligned center/size | Component state + state-tree `bottomLeft`/`topRight` | Partially — params in state tree, no getter |
| 4×4 transform matrix | `repr.state.transform` (runtime only) | No — requires internal cell/ref access |
| Visibility, color, radius, alpha | Component state + state-tree params | No getter |

### What `viewer.api` exposes for docking boxes

Only **`renderBoundingBox`** (write). No read or subscribe methods:

```108:182:platform-ui/packages/molstar/src/api/docking.ts
export const renderBoundingBox = async (
  plugin: PluginUIContext,
  structure: StateObjectRef<SO.Molecule.Structure>,
  box: Box3D,
  params?: BoundingBoxParams
) => {
  // ... creates StructureBoundingBox3D transform, commits to state tree
  const result = await plugin
    .build()
    .to(structure)
    .apply(StructureBoundingBox3D)
    .commit();
  return result;
};
```

### Theoretical escape hatch (unsupported)

A determined embed author could call `viewer.getPlugin()` and walk
`plugin.state.data.cells` for `BOUNDING_BOX_TRANSFORM_ID`, then read
`cell.transform.params` (geometry) and `cell.obj.data.repr.state.transform` (visual rotation).
This is fragile, undocumented, and still would not yield Euler angles without decomposing the
matrix.

---

## 4. What's on `molstarLib` global vs duck-typed in CLI?

### IIFE public surface (`molstarLib.*`)

esbuild bundles `src/index.ts` as IIFE `globalName: 'molstarLib'`:

```22:28:platform-ui/packages/molstar/esbuild.config.js
esbuild
  .build({
    entryPoints: [path.join(__dirname, 'src/index.ts')],
    bundle: true,
    outfile,
    globalName: 'molstarLib',
    format: 'iife',
```

**Top-level exports** (from `index.ts`):

| Export | Purpose |
|--------|---------|
| `initViewer(id)` | Create viewer + mount full UI |
| `createBox3D(min, max)` | Build real Mol* `Box3D` from `[x,y,z]` tuples |
| `MolstarViewer` | Viewer class |
| `LigandManager`, `ViewParamsState` | State managers |
| `ItemCarouselShell` | Carousel UI shell |
| Types/constants | TS types (erased at runtime), `DEFAULT_LIGAND_COLORS`, etc. |

```11:44:platform-ui/packages/molstar/src/index.ts
export { createBox3D } from './api/docking';
// ... types, LigandManager, ViewParamsState, MolstarViewer ...
export { initViewer };
```

**Not exported at top level:** `Box3D`, `Vec3`, `Mat4`, `DockingBoxControls`, `SettingsPanel`,
or any docking-box readback helpers. Internal Mol* paths (`molstar/lib/...`) are bundled but
not reachable as globals.

**Runtime API** (on returned viewer instance):

```55:55:platform-ui/packages/molstar/src/view/molstar-viewer.tsx
    this.api = createMolstarAPI(this.plugin);
```

CLI embeds use `viewer.api.*` — e.g. `loadFromRawContent`, `renderBoundingBox`,
`visualizeDockedLigands`, `renderStructureAndPockets`, etc.

### CLI usage (`molstar_html.py`)

All embeds follow the same pattern:

```619:636:do-dd-client/src/viz/molstar_html.py
    script_body = f"""const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = atob("{pdb_b64}");
      const structureRef = await viewer.api.loadFromRawContent(
        proteinData,
        "pdb",
        "protein",
        "cartoon",
      );
      // Duck-typed Box3D: molstarLib IIFE does not export Box3D/Vec3 yet.
      const box = {{ min: {min_json}, max: {max_json} }};
      await viewer.api.renderBoundingBox(structureRef, box, {{
        radius: {radius},
        color: {color},
      }});
    }};"""
```

| Concern | CLI today | Source truth |
|---------|-----------|--------------|
| Box geometry input | Duck-typed `{ min, max }` arrays | `createBox3D` now exported in source; ADR PUI-2203 tracks migrating CLI |
| Box orientation output | Not consumed | No API |
| Settings / docking UI | Loaded implicitly via `initViewer` | User must open Settings panel |
| Bundle URL | `https://os.dev.deeporigin.io/molstar/latest/index.js` | May lag source until publish |

Reference: `docs/adr/0001-docking-box-without-exported-box3d.md`.

---

## 5. Minimum platform-ui changes for orientation readback + commit callback

Goal: let notebook/SDK embeds read box geometry + rotation after user edits, and receive a
callback when the user commits a change (slider release, drag end, reset).

### Recommended approach (smallest coherent diff)

Follow the existing manager pattern (`LigandManager`, `ViewParamsState`):

#### A. Add `DockingBoxManager` (`src/utils/docking-box-manager.ts`)

- Attach in `MolstarViewer.init()` alongside other managers.
- Own canonical state: `{ ref, center, size, bottomLeft, topRight, rotationDeg: {x,y,z}, color, radius, alpha, visible }`.
- Subscribe to `plugin.state.events.object.{created,removed,updated}` for
  `BOUNDING_BOX_TRANSFORM_ID` (move detection logic out of `DockingBoxControls`).
- Centralize `applyRotation` + param updates; fire `'docking-box-changed'` on every committed
  edit.
- Expose:
  - `getState(): DockingBoxState | null`
  - `onChange(cb): () => void` (unsubscribe)

#### B. Refactor `DockingBoxControls` to delegate to manager

- Replace local `state.rotX/Y/Z` and `detectBox` with manager reads/writes.
- Keeps UI unchanged; eliminates duplicate source of truth.

#### C. Extend `MolstarAPI` (`src/api/index.ts` + `src/api/docking.ts`)

```ts
// Minimal surface for IIFE consumers
getDockingBox(): DockingBoxState | null;
onDockingBoxChange(cb: (state: DockingBoxState) => void): () => void;
```

No new top-level `molstarLib` export needed — embeds already hold `viewer.api`.

#### D. Types (`src/types/index.ts`)

```ts
interface DockingBoxState {
  center: [number, number, number];
  size: [number, number, number];
  bottomLeft: [number, number, number];
  topRight: [number, number, number];
  rotationDeg: { x: number; y: number; z: number };
  radius: number;
  color: number;       // hex
  alpha: number;
  visible: boolean;
}
```

#### E. Commit semantics

Fire callback:

- After `updateBoxParams` commit (size, center, appearance).
- On rotation slider `onChangeEnd` / mouse-up after canvas drag (not every drag frame — or
  offer both `onChange` throttled + `onCommit`).
- On reset actions.

#### F. CLI follow-up (separate ticket)

- Switch `render_docking_box_html` to `molstarLib.createBox3D(min, max)` once published
  bundle includes it.
- Add optional `onDockingBoxChange` wiring in generated HTML for notebook → Python bridge
  (postMessage or custom JS hook).

### Out of scope for minimum fix

- Persisting rotation into `bottomLeft`/`topRight` (would require computing oriented box corners
  or storing rotation in transform params).
- Auto-opening the settings panel for embeds.
- Exporting raw `Mat4` / Mol* internals on `molstarLib`.

### Estimated touch list

| File | Change |
|------|--------|
| `src/utils/docking-box-manager.ts` | **New** — state + events + rotation |
| `src/view/molstar-viewer.tsx` | Instantiate manager |
| `src/components/docking-box-controls.tsx` | Delegate to manager |
| `src/api/docking.ts` | Thin getters forwarding to manager |
| `src/api/index.ts` | Add interface methods |
| `src/types/index.ts` | `DockingBoxState` type |

---

## Recommendation

1. **Interactive controls are already present** in notebook embeds via `initViewer()` — the
   full `SettingsPanel` → `DockingBoxControls` tree ships in the IIFE. Users must click Settings
   and have called `renderBoundingBox` first.

2. **Rotation is visual-only** — applied via `repr.setState({ transform })` on the bounding-box
   mesh representation. Axis-aligned `bottomLeft`/`topRight` params do not encode orientation;
   Euler angles exist only in React component state.

3. **No programmatic readback today** — embeds cannot observe box edits. Minimum fix: add
   `DockingBoxManager` + `viewer.api.getDockingBox()` / `onDockingBoxChange()`.

4. **CLI should migrate** from duck-typed `{min,max}` to `molstarLib.createBox3D` when the
   hosted bundle is republished (source already exports it; ADR PUI-2203).

5. **For wayfinder / constrained docking workflows** needing oriented search boxes: treat
   `rotationDeg` from the new API as the authoritative user-facing orientation; document that
   downstream docking tools must consume Euler angles (or derived matrix), not raw
   `bottomLeft`/`topRight` alone.
