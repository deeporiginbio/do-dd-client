"""Every tool class pins its version the same way: class default + constructor."""

from __future__ import annotations

import inspect

import pytest

import deeporigin.drug_discovery as dd
from deeporigin.drug_discovery import Konnektor, Pose
from deeporigin.drug_discovery.execution import Execution
from deeporigin.platform.client import DeepOriginClient

_TOOL_CLASSES = [
    getattr(dd, name)
    for name in dd.__all__
    if inspect.isclass(getattr(dd, name))
    and issubclass(getattr(dd, name), Execution)
    and getattr(dd, name) is not Execution
]


@pytest.mark.parametrize("cls", _TOOL_CLASSES, ids=lambda c: c.__name__)
def test_tool_class_has_class_default_and_ctor_pin(cls: type[Execution]) -> None:
    """A class-wide default exists and the constructor accepts tool_version."""
    assert isinstance(cls.tool_version, str) and cls.tool_version
    param = inspect.signature(cls.__init__).parameters.get("tool_version")
    assert param is not None
    assert param.default is None


def _konnektor(client: DeepOriginClient, **kwargs) -> Konnektor:
    """Konnektor over two registered pose stubs."""
    poses = [
        Pose(ligand_id=f"lig-{n}", id=f"pose-{n}", remote_path=f"poses/p{n}.sdf")
        for n in (1, 2)
    ]
    return Konnektor(poses=poses, client=client, **kwargs)


def test_class_pin_and_ctor_pin_reach_execution_create(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cls.tool_version pins new instances; tool_version= overrides one instance."""
    default = Konnektor.tool_version
    assert _konnektor(client).tool_version == default

    monkeypatch.setattr(Konnektor, "tool_version", "2.0.0-1")
    assert _konnektor(client).tool_version == "2.0.0-1"
    assert _konnektor(client, tool_version="9.9.9").tool_version == "9.9.9"

    if client.env != "local":
        pytest.skip("execution create check requires the local mock server.")
    job = _konnektor(client)
    job.run(quote=True)
    assert job.tool_version == "2.0.0-1"
