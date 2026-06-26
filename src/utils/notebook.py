"""utility functions for working in Jupyter notebooks"""

from typing import Optional

from beartype import beartype
from IPython import get_ipython
from IPython.display import HTML, display


@beartype
def show_progress_bar(
    *,
    completed: int,
    total: int,
    failed: int = 0,
    title: str = "Progress Report",
) -> None:
    """
    Displays a Bootstrap progress bar in a Jupyter Notebook with a title and external text.
    """

    progress_html = render_progress_bar(
        completed=completed,
        total=total,
        failed=failed,
        title=title,
    )

    display(HTML(progress_html))


@beartype
def render_progress_bar(
    *,
    completed: int,
    total: int,
    failed: int = 0,
    title: Optional[str] = None,
    body_text: str = "",
) -> str:
    """
    Displays a Bootstrap progress bar in a Jupyter Notebook with a title and external text.

    Parameters:
      completed (int): Total tasks attempted.
      total (int): Total tasks planned.
      failed (int): Number of failed tasks.
      title (str): Title to display above the progress bar.
    """
    if total <= 0:
        raise ValueError("Total must be a positive integer.")

    # Calculate passed (successful) and pending tasks.
    passed = max(completed - failed, 0)
    pending = max(total - completed, 0)

    # HTML for the title and text labels
    text_html = f"""
    <div style="margin-bottom: 5px;">
      <span>Completed: {passed}</span>
      <span style="margin-left: 15px;">Failed: {failed}</span>
      <span style="margin-left: 15px;">Remaining: {pending}</span>
    </div>
    """

    if title:
        title_html = f"<h3>{title}</h3>"
    else:
        title_html = ""

    # Use animated striped bar when just started (completed=0 and failed=0)
    if completed == 0 and failed == 0:
        progress_html = f"""
        {title_html}
        <p style="color: #666; margin: 10px 0;">{body_text}</p>
        {text_html}
        
        <div class="progress" role="progressbar" aria-label="Starting" aria-valuenow="0" aria-valuemin="0" aria-valuemax="{total}" style="height: 20px;">
          <div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 100%"></div>
        </div>
        """
    else:
        # Calculate percentage for each segment relative to total.
        passed_pct = (passed / total) * 100
        failed_pct = (failed / total) * 100
        pending_pct = (pending / total) * 100

        progress_html = f"""
        {title_html}
        <p style="color: #666; margin: 10px 0;">{body_text}</p>
        {text_html}
        
        <div class="progress" style="height: 20px;">
          <div class="progress-bar bg-success" role="progressbar" style="width: {passed_pct:.1f}%"
               aria-valuenow="{passed}" aria-valuemin="0" aria-valuemax="{total}"></div>
          <div class="progress-bar bg-danger" role="progressbar" style="width: {failed_pct:.1f}%"
               aria-valuenow="{failed}" aria-valuemin="0" aria-valuemax="{total}"></div>
          <div class="progress-bar bg-secondary" role="progressbar" style="width: {pending_pct:.1f}%"
               aria-valuenow="{pending}" aria-valuemin="0" aria-valuemax="{total}"></div>
        </div>
        """

    return progress_html


def mermaid_to_html(diagram_code: str) -> str:
    """
    Converts a Mermaid diagram code to HTML.
    """

    html_code = f'<div class="mermaid">{diagram_code}</div>'

    html_code += """
    <script>
      if (typeof mermaid === 'undefined') {
        var script = document.createElement('script');
        script.src = "https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js";
        script.onload = function() {
          mermaid.initialize({startOnLoad:true});
          mermaid.init(undefined, document.getElementsByClassName("mermaid"));
        };
        document.head.appendChild(script);
      } else {
          mermaid.init(undefined, document.getElementsByClassName("mermaid"));
      }
    </script>
    """

    return html_code


@beartype
def render_mermaid(diagram_code: str) -> None:
    """
    Renders a Mermaid diagram in a Jupyter Notebook cell.

    Parameters:
      diagram_code (str): The Mermaid diagram definition, e.g.,
        'graph TD; A-->B;'
    """

    # Check if mermaid is defined; if not, load it.
    # This snippet checks if window.mermaid exists, and if not, loads the script.
    display(HTML(mermaid_to_html(diagram_code)))


@beartype
def get_notebook_environment() -> str:
    """
    Determine the notebook environment type.

    Returns:
        str: One of 'marimo', 'jupyter', or 'other' indicating the current environment.
    """
    # First check for Marimo
    try:
        import marimo as mo

        if mo.running_in_notebook():
            return "marimo"
    except ImportError:
        pass

    # Then check for Jupyter
    try:
        shell = get_ipython().__class__.__name__
        if shell == "ZMQInteractiveShell":
            return "jupyter"
    except NameError:
        pass

    return "other"


def _iframe_src_for_html_document(html: str) -> str:
    """Return a data-URI ``src`` for embedding a full HTML document in an iframe.

    Uses base64 rather than ``srcdoc`` so scripts are not blocked by the implicit
    srcdoc sandbox (which omits ``allow-scripts`` per the HTML spec).
    """
    import base64

    encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
    return f"data:text/html;base64,{encoded}"


def _iframe_markup_for_html_document(html: str, *, height: int) -> str:
    """Build iframe markup for a self-contained HTML document."""
    src = _iframe_src_for_html_document(html)
    return (
        f'<iframe src="{src}" '
        f'sandbox="allow-scripts allow-same-origin" '
        f'style="width:100%;height:{height}px;border:0" '
        f'loading="lazy" referrerpolicy="no-referrer"></iframe>'
    )


def render_html(
    html: str,
    *,
    height: int = 600,
    return_iframe_string: bool = False,
):
    """Render HTML in a Jupyter or marimo Notebook cell with configurable height.

    Args:
        html (str): Raw HTML content to display.
        height (int): Height of the iframe in pixels.
        return_iframe_string: If True (Jupyter only), return the iframe markup without
            calling ``display``. Used by ``_repr_html_`` so notebook execution (e.g.
            nbconvert) receives a string instead of ``None`` from ``display()``.

    Returns:
        In marimo: a ``mo.Html`` wrapper. In Jupyter, ``None`` after ``display`` unless
        ``return_iframe_string`` is True, in which case the iframe HTML string.
    """

    if get_notebook_environment() == "marimo":
        if return_iframe_string:
            raise ValueError(
                "return_iframe_string is not supported in marimo; use default rendering."
            )
        import marimo as mo

        return mo.Html(_iframe_markup_for_html_document(html, height=height))
    else:
        iframe_code = _iframe_markup_for_html_document(html, height=height)
        if return_iframe_string:
            return iframe_code
        return display(HTML(iframe_code))
