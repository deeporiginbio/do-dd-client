"""Iframe postMessage ↔ AnyWidget bridge for Jupyter notebook interactivity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
import uuid

import anywidget
from beartype import beartype
from IPython.display import display
import traitlets

from deeporigin.utils.notebook import (
    _iframe_src_for_html_document,
    get_notebook_environment,
)

DOCKING_BOX_COMMIT_MESSAGE_TYPE = "deeporigin:docking-box-commit"
DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE = "deeporigin:docking-box-commit-ack"
DOCKING_BOX_COMMIT_ERROR_MESSAGE_TYPE = "deeporigin:docking-box-commit-error"

_WIDGET_ESM = """
const render = ({ model, el, signal }) => {
  const bridgeId = model.get("bridge_id");
  const messageType = model.get("message_type");
  const iframe = document.createElement("iframe");
  iframe.id = `do-bridge-${bridgeId}`;
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

  const onWindowMessage = (event) => {
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

  const onKernelMessage = (data) => {
    if (!data || data.bridge_id !== bridgeId) {
      return;
    }
    iframe.contentWindow?.postMessage(data, "*");
  };

  window.addEventListener("message", onWindowMessage, { signal });
  model.on("msg:custom", onKernelMessage);
  signal.addEventListener(
    "abort",
    () => model.off("msg:custom", onKernelMessage),
    { once: true },
  );
};

export default { render };
"""


class _IframeCommWidget(anywidget.AnyWidget):
    """Widget that owns the iframe and its supported Jupyter Comm."""

    _esm = _WIDGET_ESM

    bridge_id = traitlets.Unicode().tag(sync=True)
    iframe_src = traitlets.Unicode().tag(sync=True)
    message_type = traitlets.Unicode(DOCKING_BOX_COMMIT_MESSAGE_TYPE).tag(sync=True)
    height = traitlets.Int(620).tag(sync=True)


@dataclass
class IframeCommHandle:
    """Handle for an interactive iframe ↔ Python comm bridge."""

    bridge_id: str
    committed: dict[str, Any] | None = field(default=None)
    widget: Any = field(default=None, repr=False)


@beartype
def render_interactive_html_with_comm(
    html_builder: Callable[[str], str],
    *,
    on_commit: Callable[[dict[str, Any]], None],
    height: int = 620,
) -> IframeCommHandle:
    """Display iframe HTML and wire postMessage commits through AnyWidget.

    Args:
        html_builder: Callable receiving ``bridge_id`` and returning iframe HTML.
        on_commit: Called with the committed payload dict from the iframe.
        height: Iframe height in pixels.

    Returns:
        Handle with bridge metadata and the last committed payload.

    Raises:
        RuntimeError: If not running inside Jupyter.
    """
    if get_notebook_environment() != "jupyter":
        raise RuntimeError(
            "Interactive notebook comm bridge requires JupyterLab or Notebook."
        )

    bridge_id = str(uuid.uuid4())
    html = html_builder(bridge_id)
    widget = _IframeCommWidget(
        bridge_id=bridge_id,
        iframe_src=_iframe_src_for_html_document(html),
        height=height,
    )
    handle = IframeCommHandle(bridge_id=bridge_id, widget=widget)

    def _on_widget_msg(
        _: _IframeCommWidget,
        content: dict[str, Any],
        __: list[Any],
    ) -> None:
        if content.get("type") != DOCKING_BOX_COMMIT_MESSAGE_TYPE:
            return
        payload = content.get("payload")
        if not isinstance(payload, dict):
            return
        handle.committed = payload
        try:
            on_commit(payload)
        except Exception as error:
            widget.send(
                {
                    "type": DOCKING_BOX_COMMIT_ERROR_MESSAGE_TYPE,
                    "bridge_id": bridge_id,
                    "message": str(error),
                }
            )
            raise
        widget.send(
            {
                "type": DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE,
                "bridge_id": bridge_id,
                "payload": payload,
            }
        )

    widget.on_msg(_on_widget_msg)
    display(widget)
    return handle
