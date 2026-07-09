"""Tests for :meth:`deeporigin.platform.tools.Tools.exists`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def test_tools_exists_exact_pin_enabled(client: DeepOriginClient) -> None:
    """An exact semver pin that resolves to an enabled definition returns True."""
    assert (
        client.tools.exists(tool_key="deeporigin.docking", tool_version="3.2.3") is True
    )


def test_tools_exists_major_pin_resolves(client: DeepOriginClient) -> None:
    """A major-only pin resolved by the platform returns True."""
    assert (
        client.tools.exists(tool_key="deeporigin.system-prep", tool_version="1") is True
    )


def test_tools_exists_not_found(client: DeepOriginClient) -> None:
    """A missing tool definition returns False."""
    assert client.tools.exists(tool_key="nonexistent-tool", tool_version="1") is False


def test_tools_exists_disabled(client: DeepOriginClient) -> None:
    """A disabled definition counts as not existing."""
    assert client.tools.exists(tool_key="disabled-tool", tool_version="1") is False
