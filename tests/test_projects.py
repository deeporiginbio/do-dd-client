"""Tests for the data platform Projects API wrapper."""

import uuid

from deeporigin.platform import DeepOriginClient


def test_projects_search_name_icontains(client: DeepOriginClient) -> None:
    """``search(name=...)`` sends icontains and filters by project name."""
    run_id = str(uuid.uuid4())
    unique_a = f"CLI test test_projects_search_name_icontains {run_id} Alpha Project"
    unique_b = f"CLI test test_projects_search_name_icontains {run_id} Beta Workspace"

    client.projects.create(name=unique_a)
    client.projects.create(name=unique_b)

    alpha_only = client.projects.search(name="alpha", limit=50)
    names_a = {r.get("name") for r in alpha_only.get("data") or []}
    assert unique_a in names_a
    assert unique_b not in names_a

    beta_only = client.projects.search(name="beta", limit=50)
    names_b = {r.get("name") for r in beta_only.get("data") or []}
    assert unique_b in names_b
    assert unique_a not in names_b


def test_projects_search_name_overrides_filter_dict_name(
    client: DeepOriginClient,
) -> None:
    """Explicit ``name`` wins over ``filter_dict['name']``."""
    run_id = str(uuid.uuid4())
    unique_a = (
        f"CLI test test_projects_search_name_overrides_filter {run_id} Gamma Proj"
    )
    unique_b = (
        f"CLI test test_projects_search_name_overrides_filter {run_id} Delta Proj"
    )
    client.projects.create(name=unique_a)
    client.projects.create(name=unique_b)

    r = client.projects.search(
        name="gamma",
        filter_dict={"name": {"icontains": "delta"}},
        limit=50,
    )
    names = {row.get("name") for row in r.get("data") or []}
    assert unique_a in names
    assert unique_b not in names


def test_projects_user_create_upserts_by_exact_name(client: DeepOriginClient) -> None:
    """``deeporigin.projects.create`` reuses an existing project with the same name."""
    from deeporigin.projects import create

    name = f"CLI test test_projects_user_create_upserts_by_exact_name {uuid.uuid4()}"
    first_id = create(name=name, load=False, client=client)
    second_id = create(name=name, load=False, client=client)
    assert isinstance(first_id, str)
    assert first_id == second_id

    r = client.projects.search(filter_dict={"name": {"eq": name}}, limit=10)
    rows = r.get("data") or []
    assert len(rows) == 1
