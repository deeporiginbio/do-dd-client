"""Build iframe-ready HTML for Mol* visualizations in Jupyter notebooks.

Uses the hosted molstarLib bundle from platform-ui/packages/molstar instead of
the legacy deeporigin-molstar Python package.
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import re

MOLSTAR_JS_URL = "https://os.dev.deeporigin.io/molstar/latest/index.js"
# Resolves relative asset paths in the molstar bundle (e.g. assets/icons/*.svg).
MOLSTAR_HOST_ASSET_BASE_URL = "https://os.deeporigin.io/host/"

_VIEWER_CONTAINER_ID = "DeepOriginMolstarViewer"
_DEFAULT_POCKET_SURFACE_ALPHA = 0.25
_DEFAULT_PROTEIN_SURFACE_ALPHA = 0.1
_DEFAULT_DOCKING_BOX_RADIUS = 0.2
_DEFAULT_DOCKING_BOX_COLOR = 0xFFFF00

_CSS_NAMED_COLORS: dict[str, int] = {
    "aliceblue": 0xF0F8FF,
    "black": 0x000000,
    "blue": 0x0000FF,
    "cyan": 0x00FFFF,
    "gray": 0x808080,
    "green": 0x008000,
    "grey": 0x808080,
    "lime": 0x00FF00,
    "magenta": 0xFF00FF,
    "orange": 0xFFA500,
    "purple": 0x800080,
    "red": 0xFF0000,
    "white": 0xFFFFFF,
    "yellow": 0xFFFF00,
}

_RGB_COLOR_RE = re.compile(
    r"^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$",
    re.IGNORECASE,
)
_RGBA_COLOR_RE = re.compile(
    r"^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$",
    re.IGNORECASE,
)


def _read_structure_file(path: str) -> str:
    """Read a structure file and return its text content."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Structure file not found: {path}")
    return file_path.read_text(encoding="utf-8")


def _encode_text_base64(text: str) -> str:
    """Return base64 encoding of UTF-8 text."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _json_for_script_tag(value: str) -> str:
    """JSON-encode a string for safe embedding inside a ``<script>`` tag."""
    return json.dumps(value).replace("<", "\\u003c")


def _json_value_for_script_tag(value: object) -> str:
    """JSON-encode a value for safe embedding inside a ``<script>`` tag."""
    return json.dumps(value).replace("<", "\\u003c")


def _validate_surface_alpha(name: str, value: float) -> float:
    """Validate a surface opacity value before embedding it in generated JS."""
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{name} must be a finite number in [0, 1], got {value!r}")
    return value


def _parse_rgb_channels(color: str, *, red: str, green: str, blue: str) -> int:
    """Convert validated RGB channel strings to a hex integer."""
    channels = (int(red), int(green), int(blue))
    if any(channel > 255 for channel in channels):
        raise ValueError(f"Unsupported CSS color: {color!r}")
    return (channels[0] << 16) | (channels[1] << 8) | channels[2]


def css_color_to_hex(color: str) -> int:
    """Convert a CSS color string to a hex integer for molstarLib ``PocketColor.value``.

    Supports named colors (e.g. ``red``), ``#rgb`` / ``#rrggbb``, ``rgb(r,g,b)``,
    and ``rgba(r,g,b,a)`` (alpha is validated but ignored for the hex value).

    Args:
        color: CSS color string.

    Returns:
        Hex color as an integer (e.g. ``0xFF0000`` for red).

    Raises:
        ValueError: If the color string cannot be parsed.
    """
    normalized = color.strip().lower()
    if normalized.startswith("#"):
        hex_str = normalized[1:]
        if len(hex_str) == 3:
            hex_str = "".join(ch * 2 for ch in hex_str)
        if len(hex_str) != 6 or not re.fullmatch(r"[0-9a-f]{6}", hex_str):
            raise ValueError(f"Unsupported CSS color: {color!r}")
        return int(hex_str, 16)

    rgb_match = _RGB_COLOR_RE.match(normalized)
    if rgb_match:
        return _parse_rgb_channels(
            color, red=rgb_match[1], green=rgb_match[2], blue=rgb_match[3]
        )

    rgba_match = _RGBA_COLOR_RE.match(normalized)
    if rgba_match:
        try:
            alpha = float(rgba_match[4])
        except ValueError as exc:
            raise ValueError(f"Unsupported CSS color: {color!r}") from exc
        if not math.isfinite(alpha) or alpha < 0 or alpha > 1:
            raise ValueError(f"Unsupported CSS color: {color!r}")
        return _parse_rgb_channels(
            color,
            red=rgba_match[1],
            green=rgba_match[2],
            blue=rgba_match[3],
        )

    if normalized in _CSS_NAMED_COLORS:
        return _CSS_NAMED_COLORS[normalized]

    raise ValueError(f"Unsupported CSS color: {color!r}")


def pocket_data_for_js(*, path: str, color: str, label: str) -> dict[str, object]:
    """Build a pocket payload for embedding in generated Mol* HTML.

    Args:
        path: Path to a pocket structure file on disk.
        color: CSS color string for the pocket surface.
        label: Display label for the pocket in the viewer.

    Returns:
        Dict with base64-encoded pocket data, molstarLib color config, and label.
    """
    return {
        "dataB64": _encode_text_base64(_read_structure_file(path)),
        "color": {"name": "uniform", "value": css_color_to_hex(color)},
        "label": label,
    }


def _render_viewer_html(*, script_body: str) -> str:
    """Wrap Mol* initialization JavaScript in a full HTML document."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, user-scalable=no, minimum-scale=1.0, maximum-scale=1.0">
  <base href="{MOLSTAR_HOST_ASSET_BASE_URL}" />
  <title>Mol* Viewer</title>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }}
    #{_VIEWER_CONTAINER_ID} {{
      width: 100%;
      height: 100vh;
    }}
  </style>
</head>
<body>
  <div id="{_VIEWER_CONTAINER_ID}"></div>
  <div id="molstar-error" style="display:none;color:#b00020;padding:12px;font-family:sans-serif;"></div>
  <script src="{MOLSTAR_JS_URL}"></script>
  <script>
    const showError = (error) => {{
      const el = document.getElementById("molstar-error");
      el.style.display = "block";
      el.textContent = "Mol* viewer failed to load: " + (error?.message || error);
      console.error(error);
    }};

    {script_body}

    const run = () => {{
      initViewer().catch(showError);
    }};

    if (document.readyState === "loading") {{
      document.addEventListener("DOMContentLoaded", run);
    }} else {{
      run();
    }}
  </script>
</body>
</html>"""


def render_protein_html(*, pdb_path: str, style: str = "cartoon") -> str:
    """Build iframe-ready HTML for protein-only visualization.

    Loads a PDB file, embeds its content in generated HTML, and initializes the
    hosted molstarLib viewer with a cartoon (or custom) representation.

    Args:
        pdb_path: Path to a PDB file on disk.
        style: Mol* representation type for the polymer (default ``cartoon``).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.
    """
    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    style_json = _json_for_script_tag(style)

    script_body = f"""const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = atob("{pdb_b64}");
      await viewer.api.loadFromRawContent(
        proteinData,
        "pdb",
        "protein",
        {style_json},
      );
    }};"""

    return _render_viewer_html(script_body=script_body)


def render_protein_with_pockets_html(
    *,
    pdb_path: str,
    pocket_paths: list[str],
    pocket_colors: list[str],
    pocket_labels: list[str],
    protein_style: str = "cartoon",
    protein_surface_alpha: float = _DEFAULT_PROTEIN_SURFACE_ALPHA,
    pocket_surface_alpha: float = _DEFAULT_POCKET_SURFACE_ALPHA,
) -> str:
    """Build iframe-ready HTML for protein visualization with binding pockets.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        pocket_paths: Paths to pocket structure files on disk.
        pocket_colors: CSS color strings, one per pocket.
        pocket_labels: Display labels, one per pocket.
        protein_style: Mol* representation type for the protein polymer.
        protein_surface_alpha: Surface opacity for the protein (legacy default 0.1).
        pocket_surface_alpha: Surface opacity for pockets (default 0.25).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.

    Raises:
        ValueError: If pocket path, color, and label lists differ in length.
    """
    if not (len(pocket_paths) == len(pocket_colors) == len(pocket_labels)):
        raise ValueError(
            "pocket_paths, pocket_colors, and pocket_labels must have the same length"
        )

    protein_surface_alpha = _validate_surface_alpha(
        "protein_surface_alpha", protein_surface_alpha
    )
    pocket_surface_alpha = _validate_surface_alpha(
        "pocket_surface_alpha", pocket_surface_alpha
    )

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    pocket_payloads = [
        pocket_data_for_js(path=path, color=color, label=label)
        for path, color, label in zip(
            pocket_paths, pocket_colors, pocket_labels, strict=True
        )
    ]
    pockets_json = _json_value_for_script_tag(pocket_payloads)
    protein_style_json = _json_for_script_tag(protein_style)

    script_body = f"""const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = atob("{pdb_b64}");
      const pocketPayloads = {pockets_json};
      const pocketDataList = pocketPayloads.map((pocket) => ({{
        data: atob(pocket.dataB64),
        color: pocket.color,
        label: pocket.label,
      }}));
      await viewer.api.renderStructureAndPockets(
        proteinData,
        "pdb",
        pocketDataList,
        "pdb",
        "gaussian-surface",
        "protein",
        {protein_style_json},
        {protein_surface_alpha},
        false,
        "ball-and-stick",
        {pocket_surface_alpha},
      );
    }};"""

    return _render_viewer_html(script_body=script_body)


def ligand_data_for_js(*, path: str, label: str | None = None) -> dict[str, object]:
    """Build a docked-ligand payload for embedding in generated Mol* HTML.

    Args:
        path: Path to an SDF file on disk.
        label: Optional display label for the ligand in the viewer.

    Returns:
        Dict with base64-encoded SDF data and an optional label.
    """
    payload: dict[str, object] = {
        "dataB64": _encode_text_base64(_read_structure_file(path)),
    }
    if label is not None:
        payload["label"] = label
    return payload


def _decode_ligand_payloads_js(variable_name: str = "ligandPayloads") -> str:
    """Return JS that maps base64 ligand payloads to ``DockedLigandData`` objects."""
    return f"""const ligands = {variable_name}.map((ligand) => {{
        const entry = {{ data: atob(ligand.dataB64) }};
        if (ligand.label !== undefined) {{
          entry.label = ligand.label;
        }}
        return entry;
      }});"""


def render_ligand_html(*, sdf_path: str, style: str = "ball-and-stick") -> str:
    """Build iframe-ready HTML for a single-ligand SDF.

    For multi-ligand sets, prefer :meth:`LigandSet.show` (legacy viewer): the hosted
    molstarLib bundle does not yet split multi-molecule SDF files correctly.

    Args:
        sdf_path: Path to a single-molecule SDF file on disk.
        style: Mol* representation type for the ligand (default ``ball-and-stick``).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.
    """
    sdf_b64 = _encode_text_base64(_read_structure_file(sdf_path))
    style_json = _json_for_script_tag(style)

    script_body = f"""const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const ligandData = atob("{sdf_b64}");
      await viewer.api.loadFromRawContent(
        ligandData,
        "sdf",
        "ligand",
        {style_json},
      );
    }};"""

    return _render_viewer_html(script_body=script_body)


def render_protein_with_poses_html(
    *,
    pdb_path: str,
    ligand_payloads: list[dict[str, object]],
    protein_style: str = "cartoon",
    ligand_style: str = "ball-and-stick",
) -> str:
    """Build iframe-ready HTML for a protein with docked ligand poses.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        ligand_payloads: Per-ligand dicts from :func:`ligand_data_for_js`.
        protein_style: Mol* representation type for the protein polymer.
        ligand_style: Mol* representation type for docked ligands.

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.

    Raises:
        ValueError: If ``ligand_payloads`` is empty.
    """
    if not ligand_payloads:
        raise ValueError("ligand_payloads must be non-empty")

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    ligands_json = _json_value_for_script_tag(ligand_payloads)
    protein_style_json = _json_for_script_tag(protein_style)
    ligand_style_json = _json_for_script_tag(ligand_style)
    decode_ligands = _decode_ligand_payloads_js()

    script_body = f"""const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = atob("{pdb_b64}");
      const ligandPayloads = {ligands_json};
      {decode_ligands}
      await viewer.api.visualizeDockedLigands(
        proteinData,
        "pdb",
        ligands,
        "sdf",
        {protein_style_json},
        {ligand_style_json},
      );
    }};"""

    return _render_viewer_html(script_body=script_body)


def render_protein_with_pockets_and_poses_html(
    *,
    pdb_path: str,
    pocket_paths: list[str],
    pocket_colors: list[str],
    pocket_labels: list[str],
    ligand_payloads: list[dict[str, object]],
    protein_style: str = "cartoon",
    ligand_style: str = "ball-and-stick",
    pocket_surface_alpha: float = _DEFAULT_POCKET_SURFACE_ALPHA,
) -> str:
    """Build iframe-ready HTML for protein + pockets + docked poses.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        pocket_paths: Paths to pocket structure files on disk.
        pocket_colors: CSS color strings, one per pocket.
        pocket_labels: Display labels, one per pocket.
        ligand_payloads: Per-ligand dicts from :func:`ligand_data_for_js`.
        protein_style: Mol* representation type for the protein polymer.
        ligand_style: Mol* representation type for docked ligands.
        pocket_surface_alpha: Surface opacity for pockets.

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.

    Raises:
        ValueError: If pocket lists differ in length or ``ligand_payloads`` is empty.
    """
    if not (len(pocket_paths) == len(pocket_colors) == len(pocket_labels)):
        raise ValueError(
            "pocket_paths, pocket_colors, and pocket_labels must have the same length"
        )
    if not ligand_payloads:
        raise ValueError("ligand_payloads must be non-empty")

    pocket_surface_alpha = _validate_surface_alpha(
        "pocket_surface_alpha", pocket_surface_alpha
    )

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    pocket_payloads = [
        pocket_data_for_js(path=path, color=color, label=label)
        for path, color, label in zip(
            pocket_paths, pocket_colors, pocket_labels, strict=True
        )
    ]
    pockets_json = _json_value_for_script_tag(pocket_payloads)
    ligands_json = _json_value_for_script_tag(ligand_payloads)
    protein_style_json = _json_for_script_tag(protein_style)
    ligand_style_json = _json_for_script_tag(ligand_style)
    decode_ligands = _decode_ligand_payloads_js()

    script_body = f"""const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = atob("{pdb_b64}");
      const pocketPayloads = {pockets_json};
      const pocketDataList = pocketPayloads.map((pocket) => ({{
        data: atob(pocket.dataB64),
        color: pocket.color,
        label: pocket.label,
      }}));
      const ligandPayloads = {ligands_json};
      {decode_ligands}
      await viewer.api.renderStructureWithPocketsAndLigands(
        proteinData,
        "pdb",
        pocketDataList,
        "pdb",
        ligands,
        "sdf",
        "gaussian-surface",
        {pocket_surface_alpha},
        {protein_style_json},
        {ligand_style_json},
      );
    }};"""

    return _render_viewer_html(script_body=script_body)


def _is_finite_number(value: object) -> bool:
    """Return True if ``value`` is a finite int/float (not bool)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _validate_docking_box_geometry(
    *,
    box_center: list[float],
    box_size: list[float],
    radius: float,
) -> tuple[list[float], list[float]]:
    """Validate docking-box inputs and return ``(min_corner, max_corner)``.

    Args:
        box_center: Docking box center ``[x, y, z]`` in angstroms.
        box_size: Docking box extents ``[sx, sy, sz]`` in angstroms.
        radius: Wireframe mesh radius.

    Returns:
        Min and max corners derived from center ± half-size.

    Raises:
        ValueError: If center/size are not length-3 finite vectors, size <= 0,
            or radius is not a positive finite number.
    """
    if len(box_center) != 3 or len(box_size) != 3:
        raise ValueError("box_center and box_size must each have length 3")
    if any(not _is_finite_number(value) for value in (*box_center, *box_size)):
        raise ValueError("box_center and box_size must be finite numbers")
    if any(size <= 0 for size in box_size):
        raise ValueError(f"box_size extents must be positive, got {box_size!r}")
    if not _is_finite_number(radius) or radius <= 0:
        raise ValueError(f"radius must be a positive finite number, got {radius!r}")

    min_corner = [box_center[i] - box_size[i] / 2 for i in range(3)]
    max_corner = [box_center[i] + box_size[i] / 2 for i in range(3)]
    return min_corner, max_corner


def _validate_docking_box_color(color: object) -> int:
    """Validate a docking-box hex color for safe JS embedding.

    Args:
        color: Hex color integer in ``[0, 0xFFFFFF]``.

    Returns:
        The validated color as ``int``.

    Raises:
        ValueError: If ``color`` is not an int in range (bools rejected).
    """
    if isinstance(color, bool) or not isinstance(color, int):
        raise ValueError(f"color must be an int in [0, 0xFFFFFF], got {color!r}")
    if color < 0 or color > 0xFFFFFF:
        raise ValueError(f"color must be an int in [0, 0xFFFFFF], got {color!r}")
    return color


def _rotation_deg_script_literal(rotation_deg: list[float] | None) -> str:
    """Return a JS literal for ``rotation_deg``, or ``null`` when identity/absent."""
    from deeporigin.drug_discovery.docking_common import normalize_rotation_deg

    normalized = normalize_rotation_deg(rotation_deg)
    if normalized is None:
        return "null"
    return _json_value_for_script_tag(normalized)


def _apply_docking_box_rotation_js() -> str:
    """Return JS helper applying rotation via molstar ``DockingBoxManager``."""
    return """
const applyDockingBoxRotation = (viewer, rotationDeg) => {
  if (
    !Array.isArray(rotationDeg)
    || rotationDeg.length !== 3
    || rotationDeg.every((value) => Math.abs(Number(value)) < 1e-9)
  ) {
    return;
  }
  const manager = viewer.getPlugin?.()?.dockingBoxManager;
  if (!manager?.setRotation) {
    console.warn(
      "molstarLib dockingBoxManager.setRotation unavailable; "
      + "box shown without rotation."
    );
    return;
  }
  manager.setRotation(
    Number(rotationDeg[0]),
    Number(rotationDeg[1]),
    Number(rotationDeg[2]),
  );
};
"""


def render_docking_box_html(
    *,
    pdb_path: str,
    box_center: list[float],
    box_size: list[float],
    rotation_deg: list[float] | None = None,
    radius: float = _DEFAULT_DOCKING_BOX_RADIUS,
    color: int = _DEFAULT_DOCKING_BOX_COLOR,
) -> str:
    """Build iframe-ready HTML for a protein with a docking search box.

    Uses a duck-typed ``{{min, max}}`` object in place of Mol* ``Box3D`` because the
    hosted molstarLib IIFE does not yet export ``Box3D`` / ``Vec3``. See ADR
    ``docs/adr/0001-docking-box-without-exported-box3d.md``.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        box_center: Docking box center ``[x, y, z]`` in angstroms.
        box_size: Docking box extents ``[sx, sy, sz]`` in angstroms.
        rotation_deg: Optional ``[rx, ry, rz]`` Euler angles (degrees) applied to
            the box mesh after ``renderBoundingBox`` (Rz·Ry·Rx about center).
        radius: Wireframe mesh radius (default ``0.2``).
        color: Hex color integer for the box (default ``0xFFFF00``).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.

    Raises:
        ValueError: If center/size are not length-3 finite vectors, size <= 0,
            radius is not a positive finite number, or ``color`` is not an
            int in ``[0, 0xFFFFFF]``.
    """
    min_corner, max_corner = _validate_docking_box_geometry(
        box_center=box_center,
        box_size=box_size,
        radius=radius,
    )
    color = _validate_docking_box_color(color)

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    min_json = _json_value_for_script_tag(min_corner)
    max_json = _json_value_for_script_tag(max_corner)
    rotation_json = _rotation_deg_script_literal(rotation_deg)

    script_body = f"""{_apply_docking_box_rotation_js()}
const initViewer = async () => {{
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
      applyDockingBoxRotation(viewer, {rotation_json});
    }};"""

    return _render_viewer_html(script_body=script_body)


def render_interactive_docking_box_html(
    *,
    pdb_path: str,
    box_center: list[float],
    box_size: list[float],
    bridge_id: str,
    rotation_deg: list[float] | None = None,
    rotation_used_by_run: bool = True,
    radius: float = _DEFAULT_DOCKING_BOX_RADIUS,
    color: int = _DEFAULT_DOCKING_BOX_COLOR,
) -> str:
    """Build iframe HTML for an interactive protein + docking box viewer.

    Loads molstarLib with ``DockingBoxControls`` (via Settings). Gesture-end
    events from ``onDockingBoxChange`` commit ``rotation_deg`` back to Python
    through the iframe postMessage ↔ AnyWidget bridge.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        box_center: Docking box center ``[x, y, z]`` in angstroms.
        box_size: Docking box extents ``[sx, sy, sz]`` in angstroms.
        bridge_id: UUID matching the parent Comm bridge.
        rotation_deg: Optional session rotation to restore on the box mesh.
        rotation_used_by_run: When ``False``, overlay warns that ``run()``
            ignores rotation (ConstrainedDocking v1).
        radius: Wireframe mesh radius.
        color: Hex color integer for the box.

    Returns:
        A complete HTML document for iframe embedding.

    Raises:
        ValueError: If center/size are invalid (see :func:`_validate_docking_box_geometry`).
    """
    from deeporigin.utils.iframe_comm_bridge import (
        DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE,
        DOCKING_BOX_COMMIT_ERROR_MESSAGE_TYPE,
        DOCKING_BOX_COMMIT_MESSAGE_TYPE,
    )

    min_corner, max_corner = _validate_docking_box_geometry(
        box_center=box_center,
        box_size=box_size,
        radius=radius,
    )
    color = _validate_docking_box_color(color)

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    min_json = _json_value_for_script_tag(min_corner)
    max_json = _json_value_for_script_tag(max_corner)
    rotation_json = _rotation_deg_script_literal(rotation_deg)
    bridge_id_json = _json_value_for_script_tag(bridge_id)
    message_type_json = _json_value_for_script_tag(DOCKING_BOX_COMMIT_MESSAGE_TYPE)
    ack_message_type_json = _json_value_for_script_tag(
        DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE
    )
    error_message_type_json = _json_value_for_script_tag(
        DOCKING_BOX_COMMIT_ERROR_MESSAGE_TYPE
    )
    warning_html = ""
    if not rotation_used_by_run:
        warning_html = (
            '<div id="do-box-warning">'
            "Visualization only — ConstrainedDocking.run() ignores rotation in v1."
            "</div>"
        )

    apply_rotation_js = _apply_docking_box_rotation_js()
    script_body = f"""{apply_rotation_js}
const seedRotation = {rotation_json};
let lastPostedRotation = Array.isArray(seedRotation)
  ? [Number(seedRotation[0]), Number(seedRotation[1]), Number(seedRotation[2])]
  : [0, 0, 0];

const rotationsEqual = (left, right) => {{
  if (!left || !right || left.length !== 3 || right.length !== 3) {{
    return false;
  }}
  return left.every((value, index) => Math.abs(Number(value) - Number(right[index])) < 1e-6);
}};

const setStatus = (text, color) => {{
  const status = document.getElementById("do-box-status");
  status.textContent = text;
  status.style.color = color;
}};

const payloadFromState = (state) => {{
  const rot = state.rotationDeg;
  return {{
    center: state.center,
    box_size: state.size,
    rotation_deg: [rot[0], rot[1], rot[2]],
  }};
}};

const postCommit = (payload) => {{
  try {{
    lastPostedRotation = payload.rotation_deg.slice();
    window.parent.postMessage(
      {{
        type: {message_type_json},
        bridge_id: {bridge_id_json},
        payload,
      }},
      "*",
    );
    setStatus(
      "Syncing rotation_deg=" + JSON.stringify(payload.rotation_deg) + "...",
      "#334155",
    );
  }} catch (error) {{
    setStatus(error?.message || String(error), "#b91c1c");
  }}
}};

const onDockingBoxChange = (state) => {{
  if (!state) {{
    return;
  }}
  const payload = payloadFromState(state);
  if (rotationsEqual(payload.rotation_deg, lastPostedRotation)) {{
    return;
  }}
  postCommit(payload);
}};

const receiveCommitResult = (event) => {{
  const data = event.data;
  if (
    event.source !== window.parent
    || !data
    || data.bridge_id !== {bridge_id_json}
  ) {{
    return;
  }}

  if (data.type === {ack_message_type_json}) {{
    setStatus(
      "Synced rotation_deg=" + JSON.stringify(data.payload.rotation_deg),
      "#334155",
    );
  }} else if (data.type === {error_message_type_json}) {{
    setStatus("Commit failed: " + data.message, "#b91c1c");
  }}
}};

const initViewer = async () => {{
  if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
    throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
  }}
  const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
  if (typeof viewer.api.getDockingBox !== "function") {{
    throw new Error(
      "molstarLib getDockingBox API is unavailable. "
      + "Update the hosted molstar bundle before using interactive box adjustment."
    );
  }}
  if (typeof viewer.api.onDockingBoxChange !== "function") {{
    throw new Error(
      "molstarLib onDockingBoxChange API is unavailable. "
      + "Update the hosted molstar bundle before using interactive box adjustment."
    );
  }}
  const proteinData = atob("{pdb_b64}");
  const structureRef = await viewer.api.loadFromRawContent(
    proteinData,
    "pdb",
    "protein",
    "cartoon",
  );
  const box = {{ min: {min_json}, max: {max_json} }};
  await viewer.api.renderBoundingBox(structureRef, box, {{
    radius: {radius},
    color: {color},
  }});
  applyDockingBoxRotation(viewer, seedRotation);
  if (Array.isArray(seedRotation)) {{
    setStatus(
      "Synced rotation_deg=" + JSON.stringify(lastPostedRotation),
      "#334155",
    );
  }}
  viewer.api.onDockingBoxChange(onDockingBoxChange);
  if (viewer.api.openDockingBoxPanel) {{
    viewer.api.openDockingBoxPanel();
  }}
}};"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, user-scalable=no, minimum-scale=1.0, maximum-scale=1.0">
  <base href="{MOLSTAR_HOST_ASSET_BASE_URL}" />
  <title>Interactive docking box</title>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      font-family: system-ui, sans-serif;
    }}
    #{_VIEWER_CONTAINER_ID} {{
      width: 100%;
      height: 100%;
    }}
    #do-box-overlay {{
      position: fixed;
      left: 8px;
      right: 8px;
      bottom: 8px;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 4px;
      pointer-events: none;
      z-index: 1000;
      font-size: 12px;
    }}
    #do-box-warning {{
      color: #92400e;
      background: #fff;
      padding: 4px 8px;
      border-radius: 4px;
    }}
    #do-box-status:empty {{
      display: none;
    }}
    #do-box-status {{
      color: #334155;
      background: #fff;
      padding: 4px 8px;
      border-radius: 4px;
    }}
    #molstar-error {{
      display: none;
      color: #b00020;
      padding: 12px;
    }}
  </style>
</head>
<body>
  <div id="{_VIEWER_CONTAINER_ID}"></div>
  <div id="do-box-overlay">
    {warning_html}
    <div id="do-box-status"></div>
  </div>
  <div id="molstar-error"></div>
  <script src="{MOLSTAR_JS_URL}"></script>
  <script>
    const showError = (error) => {{
      const el = document.getElementById("molstar-error");
      el.style.display = "block";
      el.textContent = "Mol* viewer failed to load: " + (error?.message || error);
      console.error(error);
    }};

    {script_body}

    window.addEventListener("message", receiveCommitResult);

    const run = () => {{
      initViewer().catch(showError);
    }};

    if (document.readyState === "loading") {{
      document.addEventListener("DOMContentLoaded", run);
    }} else {{
      run();
    }}
  </script>
</body>
</html>"""


def render_protein_with_box_and_poses_html(
    *,
    pdb_path: str,
    box_center: list[float],
    box_size: list[float],
    ligand_payloads: list[dict[str, object]],
    rotation_deg: list[float] | None = None,
    protein_style: str = "cartoon",
    ligand_style: str = "ball-and-stick",
    radius: float = _DEFAULT_DOCKING_BOX_RADIUS,
    color: int = _DEFAULT_DOCKING_BOX_COLOR,
) -> str:
    """Build iframe-ready HTML for protein + docking box + docked poses.

    Composes ``visualizeDockedLigands`` (returns a structure ref) with
    ``renderBoundingBox`` on that ref. There is no dedicated molstarLib method for
    this combo; the CLI composes existing APIs.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        box_center: Docking box center ``[x, y, z]`` in angstroms.
        box_size: Docking box extents ``[sx, sy, sz]`` in angstroms.
        ligand_payloads: Per-ligand dicts from :func:`ligand_data_for_js`.
        rotation_deg: Optional ``[rx, ry, rz]`` Euler angles (degrees) applied to
            the box mesh after ``renderBoundingBox``.
        protein_style: Mol* representation type for the protein polymer.
        ligand_style: Mol* representation type for docked ligands.
        radius: Wireframe mesh radius (default ``0.2``).
        color: Hex color integer for the box (default ``0xFFFF00``).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.

    Raises:
        ValueError: If box geometry is invalid, ``ligand_payloads`` is empty, or
            ``color`` is not an int in ``[0, 0xFFFFFF]``.
    """
    if not ligand_payloads:
        raise ValueError("ligand_payloads must be non-empty")

    min_corner, max_corner = _validate_docking_box_geometry(
        box_center=box_center,
        box_size=box_size,
        radius=radius,
    )
    color = _validate_docking_box_color(color)

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    ligands_json = _json_value_for_script_tag(ligand_payloads)
    protein_style_json = _json_for_script_tag(protein_style)
    ligand_style_json = _json_for_script_tag(ligand_style)
    min_json = _json_value_for_script_tag(min_corner)
    max_json = _json_value_for_script_tag(max_corner)
    rotation_json = _rotation_deg_script_literal(rotation_deg)
    decode_ligands = _decode_ligand_payloads_js()

    script_body = f"""{_apply_docking_box_rotation_js()}
const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = atob("{pdb_b64}");
      const ligandPayloads = {ligands_json};
      {decode_ligands}
      const structureRef = await viewer.api.visualizeDockedLigands(
        proteinData,
        "pdb",
        ligands,
        "sdf",
        {protein_style_json},
        {ligand_style_json},
      );
      // Duck-typed Box3D: molstarLib IIFE does not export Box3D/Vec3 yet.
      const box = {{ min: {min_json}, max: {max_json} }};
      await viewer.api.renderBoundingBox(structureRef, box, {{
        radius: {radius},
        color: {color},
      }});
      applyDockingBoxRotation(viewer, {rotation_json});
    }};"""

    return _render_viewer_html(script_body=script_body)
