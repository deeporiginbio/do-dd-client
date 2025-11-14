"""custom exceptions to surface better errors in notebooks"""

import sys

from IPython.display import HTML, display

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


def _silent_error_handler(shell, etype, evalue, tb, tb_offset=None):
    """Display a styled error card using Bootstrap 5.3.0."""
    footer_html = (
        f'<div class="card-footer text-muted">{evalue.footer}</div>'
        if evalue.footer
        else ""
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container-fluid px-0">
            <div class="card border-{evalue.level} mb-3 shadow-sm" style="max-width: 42rem;">
                <div class="card-header bg-{evalue.level} text-white fw-bold">
                    {evalue.title}
                </div>
                <div class="card-body">
                    <div class="card-text">
                        {evalue.body}
                    </div>
                </div>
                {footer_html}
            </div>
        </div>
    </body>
    </html>
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
    ip.set_custom_exc((DeepOriginException,), _silent_error_handler)
    return True


install_silent_error_handler()
