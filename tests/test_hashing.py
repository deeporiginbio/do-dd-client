"""Tests for hashing utilities beyond hash_dict."""

import base64
import hashlib
from pathlib import Path

from deeporigin.utils.hashing import (
    hash_file,
    hash_strings,
    normalize_tool_execution_body,
    sha256_checksum,
)


def test_hash_file_matches_sha256(tmp_path: Path) -> None:
    """hash_file returns the hex SHA-256 digest of file contents."""
    file_path = tmp_path / "payload.bin"
    content = b"hello deeporigin"
    file_path.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    assert hash_file(file_path) == expected


def test_sha256_checksum_base64(tmp_path: Path) -> None:
    """sha256_checksum returns a base64-encoded digest."""
    file_path = tmp_path / "payload.bin"
    content = b"checksum me"
    file_path.write_bytes(content)
    expected = base64.b64encode(hashlib.sha256(content).digest()).decode()

    assert sha256_checksum(file_path) == expected


def test_hash_strings_order_independent() -> None:
    """hash_strings is stable regardless of input order."""
    a = hash_strings(["beta", "alpha", "gamma"])
    b = hash_strings(["gamma", "beta", "alpha"])

    assert a == b
    assert len(a) == 64


def test_normalize_tool_execution_body_strips_volatile_keys() -> None:
    """normalize_tool_execution_body removes environment-specific fields."""
    body = {
        "inputs": {
            "protein": {"id": "prot-1", "file_path": "/tmp/a.pdb", "effort": 2},
            "ligand": {"id": "lig-1", "mol_file": "/tmp/b.sdf", "smiles": "CCO"},
        },
        "clusterId": "cluster-a",
        "tag": "billing-tag",
        "app": "notebook",
        "session": "sess-1",
        "approveAmount": 0,
    }

    normalized = normalize_tool_execution_body(body)

    assert normalized == {
        "inputs": {
            "protein": {"effort": 2},
            "ligand": {"smiles": "CCO"},
        },
        "approveAmount": 0,
    }


def test_normalize_tool_execution_body_accepts_params_alias() -> None:
    """normalize_tool_execution_body reads params when inputs is absent."""
    body = {"params": {"smiles": "CCO", "id": "drop-me"}}

    normalized = normalize_tool_execution_body(body)

    assert normalized == {"inputs": {"smiles": "CCO"}}
