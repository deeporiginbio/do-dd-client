"""Build iframe-ready HTML for Mol* visualizations in Jupyter notebooks.

Uses the hosted molstarLib bundle from platform-ui/packages/molstar instead of
the legacy deeporigin-molstar Python package.
"""

from __future__ import annotations

from pathlib import Path

MOLSTAR_JS_URL = "https://os.dev.deeporigin.io/molstar/latest/index.js"
# Resolves relative asset paths in the molstar bundle (e.g. assets/icons/*.svg).
MOLSTAR_HOST_ASSET_BASE_URL = "https://os.deeporigin.io/host/"

_VIEWER_CONTAINER_ID = "DeepOriginMolstarViewer"


def _escape_js_template_literal(value: str) -> str:
    """Escape a string for safe embedding inside a JS template literal."""
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def _read_structure_file(path: str) -> str:
    """Read a structure file and return its text content."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Structure file not found: {path}")
    return file_path.read_text(encoding="utf-8")


def render_protein_html(*, pdb_path: str, style: str = "cartoon") -> str:
    """Build iframe-ready HTML for protein-only visualization.

    Loads a PDB file, embeds its content in generated HTML, and initializes the
    hosted molstarLib viewer with a cartoon (or custom) representation.

    Args:
        pdb_path: Path to a PDB file on disk.
        style: Mol* representation type for the polymer (default ``cartoon``).

    Returns:
        A complete HTML document suitable for ``render_html()`` iframe srcdoc.
    """
    pdb_data = _escape_js_template_literal(_read_structure_file(pdb_path))
    style_literal = _escape_js_template_literal(style)

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

    const initViewer = async () => {{
      if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
        throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
      }}
      const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
      const proteinData = `{pdb_data}`;
      await viewer.api.loadFromRawContent(
        proteinData,
        "pdb",
        "protein",
        "{style_literal}",
      );
    }};

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
