"""PROTOTYPE DDOS-6937 — iframe postMessage ↔ ipykernel Comm bridge.

Throwaway module validating the pattern from design-docs/research/DDOS-6931.
Candidate lift target: ``deeporigin.utils.notebook.render_html_with_comm``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from beartype import beartype
from comm import Comm
from IPython.display import HTML, Javascript, display

from deeporigin.utils.notebook import (
    _iframe_src_for_html_document,
    get_notebook_environment,
)

COMM_TARGET = "deeporigin.molstar.docking_box"
MESSAGE_TYPE = "deeporigin:docking-box-commit"


@dataclass
class CommBridgeHandle:
    """Handle for an interactive iframe ↔ Python Comm bridge."""

    bridge_id: str
    comm_target: str = COMM_TARGET
    committed: dict[str, Any] | None = field(default=None)


def _iframe_markup_with_bridge_id(*, html: str, bridge_id: str, height: int) -> str:
    """Build iframe markup tagged with ``data-bridge-id`` for postMessage pairing."""
    src = _iframe_src_for_html_document(html)
    return (
        f'<iframe data-bridge-id="{bridge_id}" '
        f'src="{src}" '
        f'sandbox="allow-scripts allow-same-origin" '
        f'style="width:100%;height:{height}px;border:0" '
        f'loading="lazy" referrerpolicy="no-referrer"></iframe>'
    )


def _parent_bridge_javascript(*, bridge_id: str, comm_id: str, comm_target: str) -> str:
    """Return parent-page JS that forwards validated iframe postMessages to Comm."""
    bridge_id_json = json.dumps(bridge_id)
    comm_id_json = json.dumps(comm_id)
    comm_target_json = json.dumps(comm_target)
    message_type_json = json.dumps(MESSAGE_TYPE)
    return f"""
(function() {{
  const bridgeId = {bridge_id_json};
  const commId = {comm_id_json};
  const commTarget = {comm_target_json};
  const messageType = {message_type_json};

  const kernel =
    (typeof Jupyter !== "undefined" && Jupyter.notebook && Jupyter.notebook.kernel) ||
    (typeof IPython !== "undefined" && IPython.notebook && IPython.notebook.kernel);

  if (!kernel) {{
    console.error("[DDOS-6937 prototype] No Jupyter kernel — Comm bridge inactive.");
    return;
  }}

  const comm = kernel.comm_manager.new_comm(commId, commTarget, {{ bridge_id: bridgeId }});

  window.addEventListener("message", function(event) {{
    const data = event.data;
    if (!data || data.type !== messageType || data.bridge_id !== bridgeId) {{
      return;
    }}

    const frames = document.querySelectorAll('iframe[data-bridge-id="' + bridgeId + '"]');
    let matched = false;
    frames.forEach(function(frame) {{
      if (event.source === frame.contentWindow) {{
        matched = true;
      }}
    }});
    if (!matched) {{
      return;
    }}

    comm.send({{ data: data.payload }});
  }});
}})();
"""


@beartype
def render_interactive_html_with_comm(
    html_builder: Callable[[str], str],
    *,
    on_commit: Callable[[dict[str, Any]], None],
    comm_target: str = COMM_TARGET,
    height: int = 620,
) -> CommBridgeHandle:
    """Display iframe HTML and wire postMessage commits to a Python callback.

    Args:
        html_builder: Callable receiving ``bridge_id`` and returning iframe HTML.
        on_commit: Called with the committed docking-box payload dict.
        comm_target: ipykernel Comm target name.
        height: Iframe height in pixels.

    Returns:
        Handle with ``bridge_id`` and last ``committed`` payload (if any).

    Raises:
        RuntimeError: If not running inside Jupyter.
    """
    if get_notebook_environment() != "jupyter":
        raise RuntimeError(
            "render_interactive_html_with_comm requires Jupyter "
            "(JupyterLab or VS Code notebook)."
        )

    bridge_id = str(uuid.uuid4())
    html = html_builder(bridge_id)
    handle = CommBridgeHandle(bridge_id=bridge_id, comm_target=comm_target)

    def _on_comm_msg(msg: dict[str, Any]) -> None:
        payload = msg.get("content", {}).get("data")
        if not isinstance(payload, dict):
            return
        handle.committed = payload
        on_commit(payload)

    comm = Comm(target_name=comm_target)
    comm.on_msg(_on_comm_msg)

    display(HTML(_iframe_markup_with_bridge_id(html=html, bridge_id=bridge_id, height=height)))
    display(
        Javascript(
            _parent_bridge_javascript(
                bridge_id=bridge_id,
                comm_id=comm.comm_id,
                comm_target=comm_target,
            )
        )
    )
    return handle
