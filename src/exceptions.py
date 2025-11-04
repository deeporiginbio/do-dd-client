"""custom exceptions to surface better errors"""

import sys
import textwrap

from IPython.display import HTML, display

__all__ = ["DeepOriginException"]


def _wrap(text: str) -> str:
    wrapped_message = textwrap.wrap(text)
    wrapped_message = "\n".join(wrapped_message)

    return wrapped_message


# class DeepOriginException(Exception):
#     """Deep Origin exception"""

#     def __init__(
#         self,
#         message: str,
#         *,
#         title: str = "Deep Origin error",
#         fix: Optional[str] = None,
#     ):
#         """Utility function to print a nicely formatted error, used in the CLI"""

#         self.message = message

#         printout = [[title], [_wrap(message)]]
#         if fix:
#             printout.append([_wrap(fix)])

#         sys.stderr.write(
#             termcolor.colored(
#                 tabulate(
#                     printout,
#                     tablefmt="rounded_grid",
#                 ),
#                 "red",
#             )
#             + "\n"
#         )

#         super().__init__(self.message)


class DeepOriginException(Exception):
    """Stops execution without showing a traceback, displays Bootstrap-styled error card."""

    def __init__(self, title="Error", message=None, fix=None, level="danger"):
        """
        Args:
            title: Card title text (e.g. "Invalid Input")
            body: Card body HTML or plain text
            footer: Optional footer text
            level: Bootstrap color level (default 'danger')
        """
        super().__init__(message or title)
        self.title = title
        self.body = message or ""
        self.footer = fix
        self.level = level


def _silent_error_handler(shell, etype, evalue, tb, tb_offset=None):
    # more padding and stronger red tone
    html = f"""
    <div class="card border-{evalue.level} mb-3 shadow-sm" style="max-width: 40rem;">
      <div class="card-header bg-{evalue.level} text-white fw-bold">
        {evalue.title}
      </div>
      <div class="card-body" style="background-color:#fff5f5; padding:1.25rem 1.5rem;">
        <div class="card-text" style="font-size:1rem; color:#5c0000;">
          {evalue.body}
        </div>
      </div>
      {f'<div class="card-footer text-muted" style="font-size:0.9rem;">{evalue.footer}</div>' if evalue.footer else ""}
    </div>
    """
    display(HTML(html))
    return []  # suppress traceback completely


def install_silent_error_handler():
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    ip = get_ipython()
    if ip is None or "pytest" in sys.modules:
        # skip installing during pytest runs
        return False
    ip.set_custom_exc((DeepOriginException,), _silent_error_handler)
    print("Silent error handler installed")
    return True


install_silent_error_handler()
