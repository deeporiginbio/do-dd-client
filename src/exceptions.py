"""custom exceptions to surface better errors in notebooks"""

import sys

from IPython.display import HTML, Javascript, display

__all__ = ["DeepOriginException", "install_silent_error_handler"]


class DeepOriginException(Exception):
    """Stops execution without showing a traceback, displays a styled error card."""

    def __init__(self, title="Error", message=None, fix=None, level="danger"):
        super().__init__(message or title)
        self.title = title
        self.body = message or ""
        self.footer = fix
        # accepted: danger | warning | info | success | secondary
        self.level = level


# --- Best-effort: ensure Bootstrap 5 CSS is available (no-op if already loaded) ---
def _ensure_bootstrap_loaded():
    try:
        js = r"""
        (function() {
          try {
            // If any bootstrap-like CSS already present, do nothing
            if (document.querySelector('link[href*="bootstrap"]')) return;
            if (document.getElementById('do-bootstrap-5')) return;

            var link = document.createElement('link');
            link.id = 'do-bootstrap-5';
            link.rel = 'stylesheet';
            link.href = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css';
            link.integrity = 'sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH';
            link.crossOrigin = 'anonymous';
            document.head.appendChild(link);
          } catch (e) {
            // ignore; we'll fall back to inline styles
          }
        })();
        """
        display(Javascript(js))
    except Exception:
        pass


def _silent_error_handler(shell, etype, evalue, tb, tb_offset=None):
    # Inline fallback styles so it looks good even without Bootstrap
    palette = {
        "danger": {
            "bg": "#dc3545",
            "text": "#ffffff",
            "tint": "#fff5f5",
            "body": "#5c0000",
            "border": "#dc3545",
        },
        "warning": {
            "bg": "#ffc107",
            "text": "#000000",
            "tint": "#fff8e1",
            "body": "#5c3b00",
            "border": "#ffc107",
        },
        "info": {
            "bg": "#0dcaf0",
            "text": "#000000",
            "tint": "#e8f9ff",
            "body": "#003846",
            "border": "#0dcaf0",
        },
        "success": {
            "bg": "#198754",
            "text": "#ffffff",
            "tint": "#eefaf3",
            "body": "#0c3b27",
            "border": "#198754",
        },
        "secondary": {
            "bg": "#6c757d",
            "text": "#ffffff",
            "tint": "#f6f7f8",
            "body": "#2d3236",
            "border": "#6c757d",
        },
    }
    colors = palette.get(getattr(evalue, "level", "danger"), palette["danger"])

    html = f"""
    <div class="card border-{evalue.level} mb-3 shadow-sm"
         style="max-width: 42rem; border:1px solid {colors["border"]}; border-radius:0.5rem; box-shadow:0 .125rem .25rem rgba(0,0,0,.075); overflow:hidden;">
      <div class="card-header bg-{evalue.level} text-white fw-bold"
           style="background:{colors["bg"]}; color:{colors["text"]}; padding:.6rem .9rem; font-weight:600;">
        {evalue.title}
      </div>
      <div class="card-body"
           style="background:{colors["tint"]}; padding:1.25rem 1.5rem;">
        <div class="card-text" style="font-size:1rem; color:{colors["body"]}; line-height:1.45;">
          {evalue.body}
        </div>
      </div>
      {f'<div class="card-footer text-muted" style="font-size:.9rem; color:#6c757d; background:#fafafa; padding:.5rem .9rem;">{evalue.footer}</div>' if evalue.footer else ""}
    </div>
    """
    display(HTML(html))
    return []  # suppress traceback completely


def install_silent_error_handler():
    """Install a custom error handler for IPython notebooks that displays a styled error card."""
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    ip = get_ipython()
    if ip is None or "pytest" in sys.modules:
        return False
    _ensure_bootstrap_loaded()  # best-effort
    ip.set_custom_exc((DeepOriginException,), _silent_error_handler)
    return True


install_silent_error_handler()
