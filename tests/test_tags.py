"""Tests for entity tag provenance helpers."""

import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.tags import merge_entity_tags, stamp_batch_row_tags


def test_merge_entity_tags_always_stamps_provenance() -> None:
    """Create paths always include app and session from the client."""
    DeepOriginClient.close_all()
    client = DeepOriginClient.from_local()

    merged = merge_entity_tags(client, None, always=True)

    assert merged == {"app": client._app, "session": client._session}


def test_merge_entity_tags_caller_keys_win() -> None:
    """User tag keys override default provenance when both are set."""
    DeepOriginClient.close_all()
    client = DeepOriginClient.from_local()

    merged = merge_entity_tags(
        client,
        {"app": "custom-app", "campaign": "foo"},
        always=True,
    )

    assert merged["app"] == "custom-app"
    assert merged["campaign"] == "foo"
    assert merged["session"] == client._session


def test_merge_entity_tags_update_omits_when_none() -> None:
    """Update paths skip tags when the caller does not pass tags."""
    DeepOriginClient.close_all()
    client = DeepOriginClient.from_local()

    assert merge_entity_tags(client, None, always=False) is None


def test_merge_entity_tags_rejects_non_dict() -> None:
    """List shorthand is no longer accepted."""
    DeepOriginClient.close_all()
    client = DeepOriginClient.from_local()

    with pytest.raises(TypeError, match="tags must be a dict"):
        merge_entity_tags(client, ["a", "b"], always=True)  # type: ignore[arg-type]


def test_stamp_batch_row_tags_stamps_each_row() -> None:
    """Batch create rows always receive provenance tags."""
    DeepOriginClient.close_all()
    client = DeepOriginClient.from_local()

    stamped = stamp_batch_row_tags(
        client,
        [{"smiles": "CCO"}, {"smiles": "CCC", "tags": {"batch": "x"}}],
    )

    assert stamped[0]["tags"]["app"] == client._app
    assert stamped[1]["tags"]["batch"] == "x"
