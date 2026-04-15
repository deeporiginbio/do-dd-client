"""Command-line interface for Deep Origin."""

from __future__ import annotations

import json
from typing import Annotated

from beartype import beartype
import typer

from deeporigin.platform.client import DeepOriginClient

app = typer.Typer(help="Deep Origin CLI.")
results_app = typer.Typer(help="Result explorer commands.")
entities_app = typer.Typer(help="Ligand and protein entity commands.")
app.add_typer(results_app, name="results")
app.add_typer(entities_app, name="entities")


@beartype
def _normalize_ligand_id(ligand_id: list[str]) -> str | list[str] | None:
    """Map repeatable CLI values to :meth:`~deeporigin.platform.results.Results.get_poses` input.

    Args:
        ligand_id: Values from zero or more ``--ligand-id`` options.

    Returns:
        ``None``, a single ID string, or a list of IDs.
    """
    if not ligand_id:
        return None
    if len(ligand_id) == 1:
        return ligand_id[0]
    return ligand_id


@results_app.command("get-poses")
def get_poses(
    *,
    protein_id: str | None = typer.Option(None, help="Optional protein ID filter."),
    ligand_id: Annotated[
        list[str],
        typer.Option(
            "--ligand-id",
            "-l",
            help="Ligand ID (repeat for multiple).",
        ),
    ] = [],
    compute_job_id: str | None = typer.Option(None, help="Optional compute job ID."),
    tool_version: str | None = typer.Option(None, help="Optional tool version."),
    effort: int | None = typer.Option(
        None, help="Optional docking effort level (1–5)."
    ),
    best_pose: bool | None = typer.Option(
        None,
        "--best-pose/--no-best-pose",
        help="Filter by best pose; omit for no filter.",
    ),
    limit: int | None = typer.Option(100, help="Maximum number of results."),
    select: Annotated[
        list[str],
        typer.Option("--select", help="Field to select (repeat for multiple)."),
    ] = [],
) -> None:
    """Fetch docking poses via ``DeepOriginClient().results.get_poses`` and print JSON."""
    client = DeepOriginClient()
    raw = client.results.get_poses(
        protein_id=protein_id,
        ligand_id=_normalize_ligand_id(ligand_id),
        compute_job_id=compute_job_id,
        tool_version=tool_version,
        effort=effort,
        best_pose=best_pose,
        limit=limit,
        select=select if select else None,
    )
    typer.echo(json.dumps(raw, indent=2))


@results_app.command("get-pockets")
def get_pockets(
    *,
    record_id: str | None = typer.Option(
        None,
        "--record-id",
        help="Optional result-explorer record ID for one pocket row.",
    ),
    protein_id: str | None = typer.Option(
        None,
        "--protein",
        "-p",
        help="Optional protein ID filter.",
    ),
    compute_job_id: str | None = typer.Option(None, help="Optional compute job ID."),
    pocket_count: int | None = typer.Option(None, help="Optional pocket count filter."),
    pocket_min_size: int | None = typer.Option(
        None, help="Optional minimum pocket size filter."
    ),
    tool_version: str | None = typer.Option(None, help="Optional tool version."),
    limit: int | None = typer.Option(1000, help="Maximum number of results."),
    select: Annotated[
        list[str],
        typer.Option("--select", help="Field to select (repeat for multiple)."),
    ] = [],
) -> None:
    """Fetch binding pockets via ``DeepOriginClient().results.get_pockets`` and print JSON."""
    client = DeepOriginClient()
    raw = client.results.get_pockets(
        id=record_id,
        protein_id=protein_id,
        compute_job_id=compute_job_id,
        pocket_count=pocket_count,
        pocket_min_size=pocket_min_size,
        tool_version=tool_version,
        limit=limit,
        select=select if select else None,
    )
    typer.echo(json.dumps(raw, indent=2))


@entities_app.command("get-protein")
def get_protein(
    *,
    protein_id: str = typer.Option(
        ...,
        "--id",
        "-i",
        help="Protein entity ID.",
    ),
) -> None:
    """Fetch one protein by ID via ``DeepOriginClient().entities.get_protein`` and print JSON."""
    client = DeepOriginClient()
    if client.entities is None:
        typer.secho("Entities API is not available in this client build.", err=True)
        raise typer.Exit(code=1)
    raw = client.entities.get_protein(id=protein_id)
    typer.echo(json.dumps(raw, indent=2))


@entities_app.command("get-ligand")
def get_ligand(
    *,
    ligand_id: str = typer.Option(
        ...,
        "--id",
        "-i",
        help="Ligand entity ID.",
    ),
) -> None:
    """Fetch one ligand by ID via ``DeepOriginClient().entities.get_ligand`` and print JSON."""
    client = DeepOriginClient()
    if client.entities is None:
        typer.secho("Entities API is not available in this client build.", err=True)
        raise typer.Exit(code=1)
    raw = client.entities.get_ligand(id=ligand_id)
    typer.echo(json.dumps(raw, indent=2))
