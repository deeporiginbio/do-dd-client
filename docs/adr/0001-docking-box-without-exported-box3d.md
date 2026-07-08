# Duck-type Box3D for docking search box HTML

CLI Jupyter embeds load the hosted molstarLib IIFE (`globalName: molstarLib`).
`viewer.api.renderBoundingBox` expects a Mol* `Box3D`, but the IIFE public surface
does not export `Box3D` / `Vec3` (Storybook imports them from `molstar/lib/...`).

We generate a duck-typed `{ min: [x,y,z], max: [x,y,z] }` in
`render_docking_box_html` because the transform only reads those fields today.
That is fragile if Mol* starts calling real `Box3D` methods.

**Proper fix (platform-ui):** [PUI-2203](https://deeporigin.atlassian.net/browse/PUI-2203) —
export `molstarLib.createBox3D(min, max)` (preferred) or re-export `Box3D`/`Vec3`
from the IIFE, publish `molstar/latest`, then CLI replaces the duck-typed object.
