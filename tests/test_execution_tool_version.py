"""Every tool class pins its version the same way: a constructor argument."""

from __future__ import annotations

import inspect

import pytest

import deeporigin.drug_discovery as dd
from deeporigin.drug_discovery import Konnektor, Pose
from deeporigin.drug_discovery.execution import Execution
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

_TOOL_CLASSES = [
    getattr(dd, name)
    for name in dd.__all__
    if inspect.isclass(getattr(dd, name))
    and issubclass(getattr(dd, name), Execution)
    and getattr(dd, name) is not Execution
]
_PINS = {entry["tool_version"] for entry in TOOL_KEYS_AND_VERSIONS.values()}


@pytest.mark.parametrize("cls", _TOOL_CLASSES, ids=lambda c: c.__name__)
def test_tool_class_pins_only_through_constructor(cls: type[Execution]) -> None:
    """tool_version is a constructor argument defaulting to a pinned version."""
    param = inspect.signature(cls.__init__).parameters.get("tool_version")
    assert param is not None
    assert param.default in _PINS
    assert not any("tool_version" in vars(klass) for klass in cls.__mro__)


def test_constructor_pin_reaches_execution_create(client: DeepOriginClient) -> None:
    """tool_version= pins one instance; the default is the pinned major."""
    poses = [
        Pose(ligand_id=f"lig-{n}", id=f"pose-{n}", remote_path=f"poses/p{n}.sdf")
        for n in (1, 2)
    ]
    default = TOOL_KEYS_AND_VERSIONS["konnektor"]["tool_version"]
    assert Konnektor(poses=poses, client=client).tool_version == default

    job = Konnektor(poses=poses, client=client, tool_version="2.0.0-1")
    assert job.tool_version == "2.0.0-1"
    if client.env != "local":
        pytest.skip("execution create check requires the local mock server.")
    job.run(quote=True)
    assert job.tool_version == "2.0.0-1"
