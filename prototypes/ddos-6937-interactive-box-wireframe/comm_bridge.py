"""PROTOTYPE DDOS-6937 — iframe postMessage ↔ AnyWidget bridge.

Throwaway module validating a supported Jupyter Widget Comm round trip.
Candidate lift target: ``deeporigin.utils.notebook.render_html_with_comm``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import uuid

import anywidget
from beartype import beartype
from IPython.display import display
import traitlets

from deeporigin.utils.notebook import (
    _iframe_src_for_html_document,
    get_notebook_environment,
)

MESSAGE_TYPE = "deeporigin:docking-box-commit"

_WIDGET_ESM = """
const render = ({ model, el, signal }) => {
  const bridgeId = model.get("bridge_id");
  const messageType = model.get("message_type");
  const iframe = document.createElement("iframe");
  iframe.dataset.bridgeId = bridgeId;
  iframe.src = model.get("iframe_src");
  iframe.sandbox = "allow-scripts allow-same-origin";
  iframe.style.cssText = [
    "width:100%",
    `height:${model.get("height")}px`,
    "border:0",
  ].join(";");
  iframe.loading = "lazy";
  iframe.referrerPolicy = "no-referrer";
  el.appendChild(iframe);

  const onMessage = (event) => {
    const data = event.data;
    if (
      event.source !== iframe.contentWindow ||
      !data ||
      data.type !== messageType ||
      data.bridge_id !== bridgeId
    ) {
      return;
    }
    model.send({ type: messageType, payload: data.payload });
  };

  window.addEventListener("message", onMessage, { signal });
};

export default { render };
"""


class _IframeCommWidget(anywidget.AnyWidget):
    """AnyWidget host that owns the iframe and its supported kernel Comm."""

    _esm = _WIDGET_ESM

    bridge_id = traitlets.Unicode().tag(sync=True)
    iframe_src = traitlets.Unicode().tag(sync=True)
    message_type = traitlets.Unicode(MESSAGE_TYPE).tag(sync=True)
    height = traitlets.Int(620).tag(sync=True)


@dataclass
class CommBridgeHandle:
    """Handle for an interactive iframe ↔ Python widget bridge."""

    bridge_id: str
    committed: dict[str, Any] | None = field(default=None)
    widget: Any = field(default=None, repr=False)


@beartype
def render_interactive_html_with_comm(
    html_builder: Callable[[str], str],
    *,
    on_commit: Callable[[dict[str, Any]], None],
    height: int = 620,
) -> CommBridgeHandle:
    """Display iframe HTML and wire postMessage commits through AnyWidget.

    Args:
        html_builder: Callable receiving ``bridge_id`` and returning iframe HTML.
        on_commit: Called with the committed docking-box payload dict.
        height: Iframe height in pixels.

    Returns:
        Handle with the bridge ID, widget, and last committed payload.

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
    widget = _IframeCommWidget(
        bridge_id=bridge_id,
        iframe_src=_iframe_src_for_html_document(html),
        height=height,
    )
    handle = CommBridgeHandle(bridge_id=bridge_id, widget=widget)

    def _on_widget_msg(
        _: _IframeCommWidget,
        content: dict[str, Any],
        __: list[Any],
    ) -> None:
        payload = content.get("payload")
        if content.get("type") != MESSAGE_TYPE:
            return
        if not isinstance(payload, dict):
            return
        handle.committed = payload
        on_commit(payload)

    widget.on_msg(_on_widget_msg)
    display(widget)
    return handle
