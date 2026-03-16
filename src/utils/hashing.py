"""SHA-256 hashing helpers for files, dicts, and strings."""

import base64
import hashlib
import json
from pathlib import Path

from beartype import beartype


@beartype
def hash_file(file_path: str | Path) -> str:
    """Return the hex SHA-256 digest of a file's contents.

    Args:
        file_path: Path to the file to hash.
    """
    hasher = hashlib.new("sha256")
    with Path(file_path).open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_checksum(file_path) -> str:
    """Return a base64-encoded SHA-256 digest of a file's contents.

    Unlike :func:`hash_file` which returns a hex digest, this returns a
    base64-encoded digest suitable for integrity-checking HTTP headers
    (similar in format to Content-MD5, but using SHA-256).
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return base64.b64encode(sha256_hash.digest()).decode()


@beartype
def hash_dict(data: dict) -> str:
    """Return the hex SHA-256 digest of a dictionary.

    Key order is normalised before hashing so that dicts with the same
    contents always produce the same hash.
    """
    sorted_data = {key: data[key] for key in sorted(data.keys())}
    hasher = hashlib.sha256()
    hasher.update(json.dumps(sorted_data).encode())
    return hasher.hexdigest()


@beartype
def hash_strings(strings: list[str]) -> str:
    """Return the hex SHA-256 digest of a list of strings (order-insensitive).

    Strings are sorted before joining so the hash is stable regardless of
    input order.
    """
    combined = "--".join(sorted(strings))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


_VOLATILE_KEYS = {"id", "file_path", "mol_file"}


def _strip_ids(obj: object) -> object:
    """Recursively remove volatile keys from nested dicts/lists.

    Strips ``"id"``, ``"file_path"``, and ``"mol_file"`` so that the
    fixture-lookup hash is stable across environments where entity IDs
    and upload paths may differ.
    """
    if isinstance(obj, dict):
        return {k: _strip_ids(v) for k, v in obj.items() if k not in _VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_ids(item) for item in obj]
    return obj


def normalize_function_body(body: dict) -> dict:
    """Normalise a function-run request body for stable hashing.

    Strips environment-specific fields (``clusterId``, ``tag``, nested
    ``id`` values) so the hash is the same across dev/local/staging.

    Args:
        body: The raw request body sent to the functions API.
    """
    inputs = body.get("inputs", body.get("params", {}))
    normalized: dict = {"inputs": _strip_ids(inputs)}
    if "approveAmount" in body:
        normalized["approveAmount"] = body["approveAmount"]
    return normalized
