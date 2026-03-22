"""Terminal output helpers: color/unicode detection, formatting, and pretty-printing."""

import json
import shutil
import sys

from beartype import beartype


@beartype
def _supports_unicode_output() -> bool:
    """Return True if stdout likely supports Unicode glyphs.

    Falls back to False when the encoding is unknown or non-UTF (e.g. cp1252
    on Windows) to avoid UnicodeEncodeError at runtime.
    """
    encoding: str | None = getattr(sys.stdout, "encoding", None)
    if not encoding:
        return False
    return "utf" in encoding.lower()


@beartype
def _supports_color() -> bool:
    """Return True if the terminal supports ANSI color codes."""
    if not sys.stdout.isatty():
        return False
    if "NO_COLOR" in __import__("os").environ:
        return False
    if sys.platform == "win32":
        return False
    term = __import__("os").environ.get("TERM", "")
    return term not in ("dumb", "unknown")


def humanize_file_size(file_size: int) -> str:
    """Convert a byte count to a human-readable string (e.g. "1.23 MB")."""
    for unit_prefix in ["", "K", "M", "G", "T", "P", "E", "Z", "Y"]:
        if file_size < 1024.0:
            return f"{file_size:.2f} {unit_prefix}B"
        file_size /= 1024.0


def _truncate(txt: str) -> str:
    """Truncate text to half the current terminal width, adding "..." if cut."""
    width = int(shutil.get_terminal_size().columns / 2)
    if txt is None:
        return txt
    txt = str(txt)
    if len(txt) > width:
        txt = txt[: width - 3] + "..."
    return txt


@beartype
def _show_json(data: list | dict) -> None:
    """Pretty-print a JSON-serialisable value to stdout."""
    print(json.dumps(data, indent=2))


@beartype
def _print_tree(tree: dict, offset: int = 0) -> None:
    """Recursively pretty-print a nested tree dict using its ``hid`` field."""
    print(" " * offset + tree["hid"])
    for child in tree.get("children", []):
        _print_tree(child, offset + 2)
