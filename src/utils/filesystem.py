"""File and path utilities."""

import os
from pathlib import Path
from typing import Union

from beartype import beartype


def fix_embedded_newlines_in_csv(path: Union[str, Path]) -> bool:
    """Replace literal ``\\n`` sequences in a CSV file with real newlines, in-place.

    Returns:
        True if the file was modified, False if no literal ``\\n`` was found.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if r"\n" not in text:
        return False
    p.write_text(text.replace(r"\n", "\n"), encoding="utf-8")
    return True


@beartype
def ensure_file_extension(
    *,
    file_paths: list[Union[str, Path]],
    extension: str,
) -> list[str]:
    """Rename files to ensure they end with *extension*; return the resulting paths.

    Files already ending with the extension (case-insensitive) are untouched.
    If a file with the new extension already exists the original is left in
    place and the existing path is returned. Idempotent.

    Args:
        file_paths: Paths to process.
        extension:  Desired extension, with or without a leading dot.
    """
    if not extension.startswith("."):
        extension = f".{extension}"

    results = []
    for fp in file_paths:
        p = Path(fp)
        if p.suffix.lower() == extension.lower():
            results.append(str(p))
            continue
        new_path = p.with_suffix(extension)
        if not new_path.exists():
            os.rename(p, new_path)
        results.append(str(new_path))
    return results


@beartype
def expand_user(path, user_home_dirname: str = os.path.expanduser("~")) -> str:
    """Expand a ``~``-prefixed path to an absolute path.

    Args:
        path: Path string, possibly starting with ``~``.
        user_home_dirname: Home directory to expand into (defaults to the real home).
    """
    if path == "~":
        return user_home_dirname
    if path.startswith("~" + os.path.sep):
        return os.path.join(user_home_dirname, path[2:])
    return path
