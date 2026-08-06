"""PROTOTYPE DDOS-6937 — interactive docking box iframe HTML.

Extends the static ``render_docking_box_html`` pattern with an Apply overlay and
postMessage commit. Uses real molstarLib; rotation readback falls back to overlay
sliders until ``viewer.api.getDockingBox()`` ships (DDOS-6934).
"""

from __future__ import annotations

import json

from deeporigin.viz.molstar_html import (
    MOLSTAR_HOST_ASSET_BASE_URL,
    MOLSTAR_JS_URL,
    _encode_text_base64,
    _json_value_for_script_tag,
    _read_structure_file,
    _validate_docking_box_color,
    _validate_docking_box_geometry,
)

_VIEWER_CONTAINER_ID = "DeepOriginMolstarViewer"
_MESSAGE_TYPE = "deeporigin:docking-box-commit"


def render_interactive_docking_box_html(
    *,
    pdb_path: str,
    box_center: list[float],
    box_size: list[float],
    bridge_id: str,
    radius: float = 0.2,
    color: int = 0xFFFF00,
) -> str:
    """Build iframe HTML for protein + docking box + Apply overlay.

    Args:
        pdb_path: Path to the protein PDB file on disk.
        box_center: Docking box center ``[x, y, z]`` in angstroms.
        box_size: Docking box extents ``[sx, sy, sz]`` in angstroms.
        bridge_id: UUID matching the parent Comm bridge ``data-bridge-id``.
        radius: Wireframe mesh radius.
        color: Hex color integer for the box.

    Returns:
        A complete HTML document for iframe embedding.
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
    center_json = _json_value_for_script_tag(box_center)
    size_json = _json_value_for_script_tag(box_size)
    bridge_id_json = _json_value_for_script_tag(bridge_id)
    message_type_json = _json_value_for_script_tag(_MESSAGE_TYPE)

    script_body = f"""let viewerRef = null;

const readDockingBoxPayload = () => {{
  const fallbackRotation = [
    Number(document.getElementById("proto-rot-x").value) || 0,
    Number(document.getElementById("proto-rot-y").value) || 0,
    Number(document.getElementById("proto-rot-z").value) || 0,
  ];

  if (viewerRef?.api?.getDockingBox) {{
    const state = viewerRef.api.getDockingBox();
    if (state) {{
      const rot = state.rotationDeg;
      return {{
        center: state.center,
        box_size: state.size,
        rotation_deg: rot
          ? [rot.x ?? rot[0] ?? 0, rot.y ?? rot[1] ?? 0, rot.z ?? rot[2] ?? 0]
          : fallbackRotation,
      }};
    }}
  }}

  return {{
    center: {center_json},
    box_size: {size_json},
    rotation_deg: fallbackRotation,
  }};
}};

const postCommit = () => {{
  const payload = readDockingBoxPayload();
  window.parent.postMessage(
    {{
      type: {message_type_json},
      bridge_id: {bridge_id_json},
      payload,
    }},
    "*",
  );
  const status = document.getElementById("proto-status");
  status.textContent = "Committed: rotation_deg=" + JSON.stringify(payload.rotation_deg);
}};

const initViewer = async () => {{
  if (typeof molstarLib === "undefined" || typeof molstarLib.initViewer !== "function") {{
    throw new Error("molstarLib bundle did not load from {MOLSTAR_JS_URL}");
  }}
  const viewer = await molstarLib.initViewer("{_VIEWER_CONTAINER_ID}");
  viewerRef = viewer;
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
  <title>PROTOTYPE — Interactive docking box (DDOS-6937)</title>
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
      height: calc(100vh - 88px);
    }}
    #proto-overlay {{
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 12px;
      padding: 8px 12px;
      background: rgba(20, 24, 32, 0.92);
      color: #f5f5f5;
      font-size: 13px;
      z-index: 1000;
    }}
    #proto-overlay label {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}
    #proto-overlay input[type="range"] {{
      width: 72px;
    }}
    #proto-apply {{
      background: #2563eb;
      color: white;
      border: none;
      border-radius: 4px;
      padding: 6px 12px;
      cursor: pointer;
      font-weight: 600;
    }}
    #proto-status {{
      flex: 1 1 100%;
      color: #94a3b8;
      font-size: 12px;
      min-height: 1.2em;
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
  <div id="proto-overlay">
    <span>Open Settings (gear) for molstar rotation controls.</span>
    <label>X<input id="proto-rot-x" type="range" min="-180" max="180" value="0" /></label>
    <label>Y<input id="proto-rot-y" type="range" min="-180" max="180" value="0" /></label>
    <label>Z<input id="proto-rot-z" type="range" min="-180" max="180" value="0" /></label>
    <button id="proto-apply" type="button">Apply to notebook</button>
    <div id="proto-status"></div>
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

    document.getElementById("proto-apply").addEventListener("click", postCommit);

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
