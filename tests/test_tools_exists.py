"""Tests for :meth:`deeporigin.platform.tools.Tools.exists`."""

from __future__ import annotations

from unittest.mock import MagicMock

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.tools import Tools


def test_tools_exists_exact_pin_enabled() -> None:
    """An exact semver pin that resolves to an enabled definition returns True."""
    tools = Tools(MagicMock())
    tools.get = MagicMock(return_value={"enabled": True, "version": "3.2.3"})
    assert tools.exists(tool_key="deeporigin.docking", tool_version="3.2.3") is True


def test_tools_exists_major_pin_resolves() -> None:
    """A major-only pin resolved by the platform returns True."""
    tools = Tools(MagicMock())
    tools.get = MagicMock(return_value={"enabled": True, "version": "1.2.3"})
    assert tools.exists(tool_key="deeporigin.system-prep", tool_version="1") is True


def test_tools_exists_not_found() -> None:
    """A missing tool definition returns False."""
    tools = Tools(MagicMock())
    tools.get = MagicMock(side_effect=DeepOriginException(title="Not found"))
    assert tools.exists(tool_key="missing", tool_version="1") is False


def test_tools_exists_disabled() -> None:
    """A disabled definition counts as not existing."""
    tools = Tools(MagicMock())
    tools.get = MagicMock(return_value={"enabled": False, "version": "1.0.0"})
    assert tools.exists(tool_key="deeporigin.system-prep", tool_version="1") is False
