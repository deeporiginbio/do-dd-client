"""Tests for DeepOrigin custom exceptions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deeporigin.exceptions import (
    DeepOriginException,
    MethodDeprecatedError,
    _silent_error_handler,
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


def test_silent_error_handler_escapes_html() -> None:
    """Notebook error cards escape title, body, and footer from server text."""
    exc = DeepOriginException(
        title='<script>alert("t")</script>',
        message="<img src=x onerror=alert(1)>",
        fix="<b>footer</b>",
        level="danger",
    )
    mock_display = MagicMock()
    with patch("IPython.display.display", mock_display):
        _silent_error_handler(None, DeepOriginException, exc, None)

    mock_display.assert_called_once()
    card = mock_display.call_args[0][0].data
    assert "<script>" not in card
    assert "&lt;script&gt;" in card
    assert "&lt;img src=x onerror=alert(1)&gt;" in card
    assert "&lt;b&gt;footer&lt;/b&gt;" in card
    assert "border-danger" in card
