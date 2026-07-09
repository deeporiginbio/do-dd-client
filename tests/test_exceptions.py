"""Tests for DeepOrigin custom exceptions."""

from __future__ import annotations

import pytest

from deeporigin.exceptions import (
    DeepOriginException,
    MethodDeprecatedError,
    install_silent_error_handler,
)


def test_deep_origin_exception_str_console_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepOriginException formats title, body, and footer for plain consoles."""
    monkeypatch.setattr(
        "deeporigin.exceptions._supports_color",
        lambda: False,
    )
    exc = DeepOriginException(
        title="Bad input",
        message="Value was invalid",
        fix="Use a valid SMILES string",
        level="warning",
    )

    text = str(exc)

    assert "Bad input" in text
    assert "Value was invalid" in text
    assert "Use a valid SMILES string" in text


def test_deep_origin_exception_str_with_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepOriginException applies ANSI colors when supported."""
    monkeypatch.setattr(
        "deeporigin.exceptions._supports_color",
        lambda: True,
    )
    exc = DeepOriginException(title="Error", message="boom", level="danger")

    text = str(exc)

    assert "\033[91m" in text
    assert "Error" in text


def test_method_deprecated_error_is_value_error() -> None:
    """MethodDeprecatedError is a ValueError subclass."""
    with pytest.raises(ValueError):
        raise MethodDeprecatedError("use the new API instead")


def test_install_silent_error_handler_false_under_pytest() -> None:
    """install_silent_error_handler does not install during pytest runs."""
    assert install_silent_error_handler() is False
