"""Build iframe-ready HTML for Mol* visualizations in Jupyter notebooks.

Uses the hosted molstarLib bundle from platform-ui/packages/molstar instead of
the legacy deeporigin-molstar Python package.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re

MOLSTAR_JS_URL = "https://os.dev.deeporigin.io/molstar/latest/index.js"
# Resolves relative asset paths in the molstar bundle (e.g. assets/icons/*.svg).
MOLSTAR_HOST_ASSET_BASE_URL = "https://os.deeporigin.io/host/"

_VIEWER_CONTAINER_ID = "DeepOriginMolstarViewer"
_DEFAULT_POCKET_SURFACE_ALPHA = 0.7
_DEFAULT_PROTEIN_SURFACE_ALPHA = 0.1

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
    r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+\s*)?\)$",
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


def css_color_to_hex(color: str) -> int:
    """Convert a CSS color string to a hex integer for molstarLib ``PocketColor.value``.

    Supports named colors (e.g. ``red``), ``#rgb`` / ``#rrggbb``, and ``rgb(r,g,b)``.

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
        red, green, blue = (int(channel) for channel in rgb_match.groups())
        if any(channel > 255 for channel in (red, green, blue)):
            raise ValueError(f"Unsupported CSS color: {color!r}")
        return (red << 16) | (green << 8) | blue

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
        pocket_surface_alpha: Surface opacity for pockets (legacy default 0.7).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe embedding.

    Raises:
        ValueError: If pocket path, color, and label lists differ in length.
    """
    if not (len(pocket_paths) == len(pocket_colors) == len(pocket_labels)):
        raise ValueError(
            "pocket_paths, pocket_colors, and pocket_labels must have the same length"
        )

    pdb_b64 = _encode_text_base64(_read_structure_file(pdb_path))
    pocket_payloads = [
        pocket_data_for_js(path=path, color=color, label=label)
        for path, color, label in zip(pocket_paths, pocket_colors, pocket_labels)
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
