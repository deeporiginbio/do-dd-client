"""this module contains some core utility functions that in turn do not depend on anything else in this library"""

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Union

from beartype import beartype


@beartype
def _supports_unicode_output() -> bool:
    """Return True if stdout likely supports Unicode glyphs.

    Uses the encoding reported by `sys.stdout.encoding` and falls back to
    `utf-8` heuristic. On Windows default code pages (e.g., cp1252), returns
    False to avoid `UnicodeEncodeError`.

    Returns:
        True if stdout supports Unicode, False otherwise.
    """
    encoding: str | None = getattr(sys.stdout, "encoding", None)
    if not encoding:
        return False
    encoding_lower = encoding.lower()
    return "utf" in encoding_lower


@beartype
def _supports_color() -> bool:
    """Check if terminal supports ANSI color codes."""
    # Check if we're in a terminal that supports colors
    if not sys.stdout.isatty():
        return False

    # Check NO_COLOR environment variable (standard)
    if "NO_COLOR" in os.environ:
        return False

    # Check for common environment variables that disable colors
    if sys.platform == "win32":
        # Windows terminal color support is more complex
        return False
    # Check TERM environment variable
    term = os.environ.get("TERM", "")
    if term in ("dumb", "unknown"):
        return False

    return True


def fix_embedded_newlines_in_csv(path: Union[str, Path]) -> bool:
    """
    Detects literal '\\n' sequences in the CSV at `path` and replaces them
    with real newlines, rewriting the file in-place.

    Returns:
        True if the file was modified (i.e. a '\\n' was found and fixed),
        False if no literal '\\n' was present.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    # If there are no literal "\n" sequences, nothing to do
    if r"\n" not in text:
        return False

    # Replace all literal "\n" with actual newlines
    fixed = text.replace(r"\n", "\n")
    p.write_text(fixed, encoding="utf-8")
    return True


def elapsed_minutes(
    start: Union[str, datetime],
    end: Union[str, datetime],
) -> int:
    """
    Compute the number of minutes elapsed between two timestamps,
    rounding to the nearest whole minute.

    Parameters:
        start: ISO-8601 UTC string (e.g. "2025-04-16T18:03:16.154Z")
               or a timezone-aware datetime.
        end:   Same format as start.

    Returns:
        Elapsed time in minutes (int), rounded to the nearest minute.
    """

    def to_dt(ts):
        if isinstance(ts, datetime):
            return ts
        # parse "YYYY-MM-DDTHH:MM:SS.sssZ"
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.replace(tzinfo=timezone.utc)

    dt_start = to_dt(start)
    dt_end = to_dt(end)
    seconds_elapsed = (dt_end - dt_start).total_seconds()
    minutes = seconds_elapsed / 60
    return int(round(minutes))


@beartype
def ensure_file_extension(
    *,
    file_paths: list[Union[str, Path]],
    extension: str,
) -> list[str]:
    """
    Rename each file in file_paths so that it ends with the specified extension,
    and return the list of resulting file paths. Files already
    ending with the specified extension (case-insensitive) are left untouched.

    Args:
        file_paths (List[Union[str, Path]]): List of file paths to process
        extension (str): The desired file extension (with or without leading dot)

    Returns:
        List[Path]: List of resulting file paths

    Idempotent: running it again makes no further changes.
    """
    # Ensure extension starts with a dot
    if not extension.startswith("."):
        extension = f".{extension}"

    resulting_paths = []

    for fp in file_paths:
        p = Path(fp)

        # Already has the desired extension? leave as is
        if p.suffix.lower() == extension.lower():
            resulting_paths.append(str(p))
            continue

        new_path = p.with_suffix(extension)

        # If the file with new extension already exists, skip renaming—but still return new_path
        if new_path.exists():
            resulting_paths.append(str(new_path))
            continue

        # Otherwise rename and return the new path
        os.rename(p, new_path)
        resulting_paths.append(str(new_path))

    return resulting_paths


def set_key_to_value(
    obj: dict,
    target_key: str,
    new_value,
):
    """utility function to set a key in a dict to a value

    Args:
        obj (dict): the dictionary
        target_key (str): the key to be set
        new_value: the value to be set

    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == target_key:
                obj[key] = new_value
            else:
                set_key_to_value(value, target_key, new_value)
    elif isinstance(obj, list):
        for item in obj:
            set_key_to_value(item, target_key, new_value)


@beartype
def hash_file(file_path: str | Path) -> str:
    """
    Hashes the contents of a file using sha256

    Args:
        file_path (Union[str, Path]): Path to the file to be hashed.

    Returns:
        str: The hexadecimal hash digest of the file's contents.
    """
    file_path = Path(file_path)
    hasher = hashlib.new("sha256")

    # Read and update hash in chunks to handle large files efficiently
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


@beartype
def hash_dict(data: dict) -> str:
    """
    Computes a SHA-256 hash for a dictionary.

    Parameters:
        data (dict): A dictionary.

    Returns:
        str: The hexadecimal SHA-256 hash of the dictionary.
    """
    sorted_keys = sorted(data.keys())
    data = {key: data[key] for key in sorted_keys}

    hasher = hashlib.sha256()
    hasher.update(json.dumps(data).encode())
    return hasher.hexdigest()


@beartype
def hash_strings(strings: list[str]) -> str:
    """
    Computes a SHA-256 hash for a list of strings in an order-insensitive manner.

    The function sorts the input list, joins the sorted strings using a null-character delimiter,
    and returns the hexadecimal digest of the SHA-256 hash.

    Parameters:
        strings (list[str]): A list of strings.

    Returns:
        str: The hexadecimal SHA-256 hash of the sorted list.
    """
    sorted_strings = sorted(strings)

    # Use a delimiter
    combined_string = "--".join(sorted_strings)
    hash_obj = hashlib.sha256(combined_string.encode("utf-8"))
    return hash_obj.hexdigest()


class PersistentDict:
    """
    A class that behaves like a dictionary but persists its data to a JSON file.
    """

    def __init__(self, file_path):
        """
        Initialize the PersistentDict.

        Args:
            file_path (str or Path): The path to the JSON file.
        """
        self.file_path = Path(file_path)
        self._data = self._load_or_initialize()

    def _load_or_initialize(self):
        """
        Load data from the JSON file if it exists, or initialize an empty dict.
        """
        if self.file_path.exists():
            with self.file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        else:
            self.file_path.parent.mkdir(
                parents=True, exist_ok=True
            )  # Ensure the directory exists
            self._save({})
            return {}

    def _save(self, data):
        """
        Save the current data to the JSON file.
        """
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        self._save(self._data)

    def __delitem__(self, key):
        del self._data[key]
        self._save(self._data)

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return repr(self._data)

    def keys(self):
        """method to return the keys of this dict"""
        return self._data.keys()

    def values(self):
        """method to return the values of the underlying dict"""
        return self._data.values()

    def items(self):
        """method to return the items of the underlying dict"""
        return self._data.items()

    def get(self, key, default=None):
        """method to get a value by key"""
        return self._data.get(key, default)

    def update(self, *args, **kwargs):
        """method to update a value in the underlying dict"""
        self._data.update(*args, **kwargs)
        self._save(self._data)

    def clear(self):
        """method to clear the underlying dict"""
        self._data.clear()
        self._save(self._data)


def _get_method(obj, method_path: str):
    # Split the method path into components
    methods = method_path.split(".")

    # Traverse the attributes to get to the final method
    for method in methods:
        obj = getattr(obj, method)

    return obj


def humanize_file_size(file_size: int):
    """humanizes a file size in bytes"""
    for unit_prefix in ["", "K", "M", "G", "T", "P", "E", "Z", "Y"]:
        if file_size < 1024.0:
            return f"{file_size:.2f} {unit_prefix}B"
        file_size /= 1024.0


def sha256_checksum(file_path):
    """compute sha256 hash of a file"""

    import hashlib

    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return base64.b64encode(sha256_hash.digest()).decode()


@beartype
def _print_tree(tree: dict, offset: int = 0) -> None:
    """Helper function to pretty print a tree"""
    print(" " * offset + tree["hid"])

    if "children" not in tree.keys():
        return
    for child in tree["children"]:
        _print_tree(child, offset + 2)


def _truncate(txt: str) -> str:
    """Utility function for truncating text"""

    TERMINAL_WIDTH = int(shutil.get_terminal_size().columns / 2)

    if txt is None:
        return txt
    txt = str(txt)
    if len(txt) > TERMINAL_WIDTH:
        txt = txt[: TERMINAL_WIDTH - 3] + "..."
    return txt


@beartype
def _show_json(data: Union[list, dict]) -> None:
    """Utility for pretty printing JSON, used in the CLI"""

    print(json.dumps(data, indent=2))


@beartype
def expand_user(path, user_home_dirname: str = os.path.expanduser("~")) -> str:
    """Expand paths that start with `~` by replacing it the user's home directory

    Args:
        path (:obj:`str`): path
        user_home_dirname (:obj:`str`, optional): user's home directory

    Returns:
        :obj:`str`: expanded path
    """
    if path == "~":
        return user_home_dirname
    elif path.startswith("~" + os.path.sep):
        return os.path.join(user_home_dirname, path[2:])
    else:
        return path


@beartype
def _ensure_do_folder() -> Path:
    """makes sure that the deeporigin scratch folder exists

    If it doesn't exist, the folder is created. The location of this folder is typically in the home directory"""

    deeporigin_path = Path.home() / ".deeporigin"
    deeporigin_path.mkdir(parents=True, exist_ok=True)

    return deeporigin_path
