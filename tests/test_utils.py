"""Tests for utility functions in the core module"""

import hashlib
import json

from src.utils.core import get_bool_env, hash_dict


def test_basic_dict_hashing():
    """Test that hash_dict produces a valid SHA-256 hash for a simple dictionary"""
    test_dict = {"a": 1, "b": 2, "c": 3}
    result = hash_dict(test_dict)

    # Check that result is a string
    assert isinstance(result, str)

    # Check that result is a valid hex string (SHA-256 produces 64 hex characters)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)

    # Verify the hash is deterministic
    result2 = hash_dict(test_dict)
    assert result == result2


def test_dict_key_ordering():
    """Test that hash_dict produces the same hash regardless of key order"""
    dict1 = {"a": 1, "b": 2, "c": 3}
    dict2 = {"c": 3, "a": 1, "b": 2}

    hash1 = hash_dict(dict1)
    hash2 = hash_dict(dict2)

    assert hash1 == hash2


def test_nested_dict_hashing():
    """Test that hash_dict works with nested dictionaries"""
    test_dict = {
        "outer": {"inner": {"deep": "value"}, "list": [1, 2, 3]},
        "simple": "string",
    }

    result = hash_dict(test_dict)
    assert isinstance(result, str)
    assert len(result) == 64


def test_empty_dict():
    """Test that hash_dict works with an empty dictionary"""
    result = hash_dict({})
    assert isinstance(result, str)
    assert len(result) == 64

    # Empty dict should always produce the same hash
    result2 = hash_dict({})
    assert result == result2


def test_dict_with_different_value_types():
    """Test that hash_dict works with various value types"""
    test_dict = {
        "string": "hello",
        "integer": 42,
        "float": 3.14,
        "boolean": True,
        "none": None,
        "list": [1, 2, 3],
        "dict": {"nested": "value"},
    }

    result = hash_dict(test_dict)
    assert isinstance(result, str)
    assert len(result) == 64


def test_manual_hash_verification():
    """Test that the hash matches what we would expect from manual calculation"""
    test_dict = {"a": 1, "b": 2}

    # Manual calculation of expected hash
    sorted_keys = sorted(test_dict.keys())
    sorted_dict = {key: test_dict[key] for key in sorted_keys}
    expected_hash = hashlib.sha256(json.dumps(sorted_dict).encode()).hexdigest()

    actual_hash = hash_dict(test_dict)
    assert actual_hash == expected_hash


def test_unicode_strings():
    """Test that hash_dict works with unicode strings"""
    test_dict = {"english": "hello", "unicode": "こんにちは", "emoji": "🚀"}

    result = hash_dict(test_dict)
    assert isinstance(result, str)
    assert len(result) == 64


def test_large_dict():
    """Test that hash_dict works with larger dictionaries"""
    test_dict = {f"key_{i}": f"value_{i}" for i in range(100)}

    result = hash_dict(test_dict)
    assert isinstance(result, str)
    assert len(result) == 64


def test_dict_with_special_characters():
    """Test that hash_dict works with special characters in keys and values"""
    test_dict = {
        "key with spaces": "value with spaces",
        "key-with-dashes": "value-with-dashes",
        "key_with_underscores": "value_with_underscores",
        "key.with.dots": "value.with.dots",
        "key:with:colons": "value:with:colons",
        "key/with/slashes": "value/with/slashes",
    }

    result = hash_dict(test_dict)
    assert isinstance(result, str)
    assert len(result) == 64


def test_consistency_across_runs():
    """Test that the same dictionary always produces the same hash across multiple runs"""
    test_dict = {"test": "data", "numbers": [1, 2, 3, 4, 5]}

    hashes = []
    for _ in range(10):
        hashes.append(hash_dict(test_dict))

    # All hashes should be identical
    assert len(set(hashes)) == 1
    assert hashes[0] == hash_dict(test_dict)


def test_different_dicts_produce_different_hashes():
    """Test that different dictionaries produce different hashes"""
    dict1 = {"a": 1, "b": 2}
    dict2 = {"a": 1, "b": 3}
    dict3 = {"a": 1, "c": 2}

    hash1 = hash_dict(dict1)
    hash2 = hash_dict(dict2)
    hash3 = hash_dict(dict3)

    # All hashes should be different
    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3


def test_get_bool_env_not_set(monkeypatch):
    """Test that get_bool_env returns default when env var is not set"""
    # Ensure the env var is not set
    monkeypatch.delenv("TEST_BOOL_ENV", raising=False)
    assert get_bool_env("TEST_BOOL_ENV", default=False) is False
    assert get_bool_env("TEST_BOOL_ENV", default=True) is True


def test_get_bool_env_truthy_values(monkeypatch):
    """Test that get_bool_env returns True for truthy values"""
    truthy_values = ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"]
    for value in truthy_values:
        monkeypatch.setenv("TEST_BOOL_ENV", value)
        assert get_bool_env("TEST_BOOL_ENV", default=False) is True


def test_get_bool_env_falsy_values(monkeypatch):
    """Test that get_bool_env returns False for falsy values"""
    falsy_values = [
        "0",
        "false",
        "False",
        "FALSE",
        "no",
        "No",
        "NO",
        "off",
        "Off",
        "OFF",
        "",
    ]
    for value in falsy_values:
        monkeypatch.setenv("TEST_BOOL_ENV", value)
        assert get_bool_env("TEST_BOOL_ENV", default=True) is False


def test_get_bool_env_with_whitespace(monkeypatch):
    """Test that get_bool_env handles whitespace correctly"""
    monkeypatch.setenv("TEST_BOOL_ENV", " true ")
    assert get_bool_env("TEST_BOOL_ENV", default=False) is True

    monkeypatch.setenv("TEST_BOOL_ENV", " 1 ")
    assert get_bool_env("TEST_BOOL_ENV", default=False) is True

    monkeypatch.setenv("TEST_BOOL_ENV", " false ")
    assert get_bool_env("TEST_BOOL_ENV", default=True) is False

    monkeypatch.setenv("TEST_BOOL_ENV", " 0 ")
    assert get_bool_env("TEST_BOOL_ENV", default=True) is False


def test_get_bool_env_case_insensitive(monkeypatch):
    """Test that get_bool_env is case-insensitive"""
    monkeypatch.setenv("TEST_BOOL_ENV", "TRUE")
    assert get_bool_env("TEST_BOOL_ENV", default=False) is True

    monkeypatch.setenv("TEST_BOOL_ENV", "FALSE")
    assert get_bool_env("TEST_BOOL_ENV", default=True) is False

    monkeypatch.setenv("TEST_BOOL_ENV", "YES")
    assert get_bool_env("TEST_BOOL_ENV", default=False) is True

    monkeypatch.setenv("TEST_BOOL_ENV", "NO")
    assert get_bool_env("TEST_BOOL_ENV", default=True) is False


def test_get_bool_env_unexpected_values(monkeypatch):
    """Test that get_bool_env returns False for unexpected values"""
    unexpected_values = ["maybe", "2", "enabled", "disabled", "foo", "bar"]
    for value in unexpected_values:
        monkeypatch.setenv("TEST_BOOL_ENV", value)
        assert get_bool_env("TEST_BOOL_ENV", default=True) is False
