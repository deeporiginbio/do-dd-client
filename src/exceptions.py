"""custom exceptions to surface better errors in notebooks"""

import sys

from deeporigin.utils.core import _supports_color

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

    def __str__(self) -> str:
        """Format exception for display. Returns minimal output in notebooks (where HTML rendering is handled separately) or formatted console output otherwise."""
        # Try to use IPython display if available (for notebooks)
        try:
            from IPython import get_ipython

            ip = get_ipython()
            if ip is not None and "pytest" not in sys.modules:
                # In notebook, let the custom handler display HTML
                # Return minimal string to avoid double display
                return self.title
        except ImportError:
            # IPython is not available; fall back to console output formatting below.
            pass

        # Format for console output
        lines = []

        # Add colored title if terminal supports it
        if _supports_color():
            level_colors = {
                "danger": "\033[91m",  # Red
                "warning": "\033[93m",  # Yellow
                "info": "\033[94m",  # Blue
                "success": "\033[92m",  # Green
                "secondary": "\033[90m",  # Gray
            }
            reset = "\033[0m"
            color = level_colors.get(self.level, reset)
            lines.append(f"{color}╔═ {self.title} ═╗{reset}")
        else:
            lines.append(f"╔═ {self.title} ═╗")

        # Add body
        if self.body:
            lines.append(self.body)

        # Add footer/fix if present
        if self.footer:
            if _supports_color():
                lines.append(f"\033[2m{self.footer}\033[0m")  # Dimmed text
            else:
                lines.append(self.footer)

        return "\n".join(lines)


def _silent_error_handler(shell, etype, evalue, tb, tb_offset=None):
    """Display a styled error card using Bootstrap 5.3.0."""
    try:
        from IPython.display import HTML, display
    except ImportError:
        # Fallback to console output if IPython not available
        print(str(evalue), file=sys.stderr)
        return []

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


def install_silent_error_handler() -> bool:
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
