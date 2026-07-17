"""Generate standalone Mol* visualization HTML files for the docs.

This is the single source of truth for how each ``docs/images/*.html`` Mol*
visualization is produced. Each entry in ``VIZ_REGISTRY`` maps a docs-image name
to a builder that returns a complete, self-contained HTML document (from the
``deeporigin.viz.molstar_html`` builders). The document is wrapped in an iframe
(via ``render_html(..., return_iframe_string=True)``) and written to
``docs/images/<name>.html`` — exactly the markup a Jupyter cell would emit, but
without the nbconvert export / copy-paste round trip.

Usage (from the repo root):

    uv run python skills/make-viz/scripts/build_docs_viz.py --list
    uv run python skills/make-viz/scripts/build_docs_viz.py brd-protein
    uv run python skills/make-viz/scripts/build_docs_viz.py brd-protein brd-pocket

Add a new visualization by adding an entry to ``VIZ_REGISTRY`` (see the existing
entries for the pattern), then run the script with that name.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys


def _find_repo_root() -> Path:
    """Return the CLI repo root (dir with pyproject.toml and src/viz/molstar_html.py)."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "viz" / "molstar_html.py"
        ).is_file():
            return candidate
    raise FileNotFoundError(
        "Could not find the CLI repo root from "
        f"{here!s}. Run this script from inside the cli repo."
    )


REPO_ROOT = _find_repo_root()
IMAGES_DIR = REPO_ROOT / "docs" / "images"


@dataclass(frozen=True)
class VizSpec:
    """A single docs visualization recipe.

    Attributes:
        build: Callable returning a complete standalone HTML document.
        height: iframe height in pixels for the generated docs file.
    """

    build: Callable[[], str]
    height: int = 600


def _brd_pdb() -> str:
    """Return the path to the bundled BRD4 protein PDB as a string."""
    from deeporigin.drug_discovery import BRD_DATA_DIR

    return str(BRD_DATA_DIR / "brd.pdb")


def _brd_sdf(index: int) -> str:
    """Return the path to a bundled BRD4 ligand SDF as a string."""
    from deeporigin.drug_discovery import BRD_DATA_DIR

    return str(BRD_DATA_DIR / f"brd-{index}.sdf")


def _pocket_fixture() -> str:
    """Return the path to the shared pocket PDB test fixture as a string."""
    return str(
        REPO_ROOT / "tests" / "fixtures" / "files" / "pocketfinder" / "pocket_1.pdb"
    )


def _build_brd_protein() -> str:
    """Protein-only view of BRD4 (mirrors ``Protein.show()``)."""
    from deeporigin.viz.molstar_html import render_protein_html

    return render_protein_html(pdb_path=_brd_pdb())


def _build_brd_no_water() -> str:
    """BRD4 protein with waters removed (mirrors ``remove_water()`` + ``show()``)."""
    from deeporigin.drug_discovery import Protein
    from deeporigin.viz.molstar_html import render_protein_html

    protein = Protein.from_file(_brd_pdb())
    protein.remove_water()
    return render_protein_html(pdb_path=protein._dump_state())


def _build_brd_pocket() -> str:
    """BRD4 protein with a single binding pocket overlay."""
    from deeporigin.drug_discovery import Pocket
    from deeporigin.viz.molstar_html import render_protein_with_pockets_html

    pocket_path = _pocket_fixture()
    pocket = Pocket.from_pdb_file(pocket_path, name="pocket-1", color="red")
    return render_protein_with_pockets_html(
        pdb_path=_brd_pdb(),
        pocket_paths=[pocket_path],
        pocket_colors=[pocket.color],
        pocket_labels=[pocket.name or "pocket-1"],
    )


def _build_brd_docked_poses() -> str:
    """BRD4 protein with the bundled BRD4 ligands overlaid as docked poses."""
    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet
    from deeporigin.drug_discovery.docking_common import ligand_payloads_for_viewer
    from deeporigin.viz.molstar_html import render_protein_with_poses_html

    poses = LigandSet.from_dir(BRD_DATA_DIR)
    return render_protein_with_poses_html(
        pdb_path=_brd_pdb(),
        ligand_payloads=ligand_payloads_for_viewer(list(poses.ligands)),
    )


def _build_brd_docking_box() -> str:
    """BRD4 protein with a docking search box (mirrors ``Docking.show_box()``).

    Uses the shared pocket fixture with a 15 A cubic box, matching the docking
    tutorial. Box center/size are resolved the same way ``Docking`` submits them.
    """
    from deeporigin.drug_discovery import Pocket
    from deeporigin.drug_discovery.docking_common import resolve_docking_box_geometry
    from deeporigin.viz.molstar_html import render_docking_box_html

    pocket = Pocket.from_pdb_file(_pocket_fixture(), name="pocket-1")
    pocket.box_size_x = pocket.box_size_y = pocket.box_size_z = 15.0
    box_center, box_size = resolve_docking_box_geometry(pocket)
    return render_docking_box_html(
        pdb_path=_brd_pdb(),
        box_center=box_center,
        box_size=box_size,
    )


def _build_serotonin() -> str:
    """Single serotonin ligand (mirrors ``Ligand.from_identifier(...).show()``).

    Resolves the SMILES from PubChem (network) and generates a 3D conformer so the
    Mol* ball-and-stick view has real coordinates.
    """
    from deeporigin.drug_discovery import Ligand
    from deeporigin.viz.molstar_html import render_ligand_html

    ligand = Ligand.from_identifier("serotonin")
    if ligand.mol.GetNumConformers() == 0:
        ligand.embed()
    return render_ligand_html(sdf_path=ligand.to_sdf())


VIZ_REGISTRY: dict[str, VizSpec] = {
    "brd-protein": VizSpec(build=_build_brd_protein, height=600),
    "brd-no-water": VizSpec(build=_build_brd_no_water, height=600),
    "brd-pocket": VizSpec(build=_build_brd_pocket, height=600),
    "brd-docked-poses": VizSpec(build=_build_brd_docked_poses, height=600),
    "brd-docking-box": VizSpec(build=_build_brd_docking_box, height=600),
    "serotonin": VizSpec(build=_build_serotonin, height=600),
}


def generate(name: str) -> Path:
    """Build one docs visualization and write it to ``docs/images/<name>.html``.

    Args:
        name: Registry key identifying the visualization.

    Returns:
        The path to the written HTML file.

    Raises:
        KeyError: If ``name`` is not in ``VIZ_REGISTRY``.
    """
    from deeporigin.utils.notebook import render_html

    if name not in VIZ_REGISTRY:
        raise KeyError(
            f"Unknown visualization {name!r}. Known: {', '.join(sorted(VIZ_REGISTRY))}"
        )

    spec = VIZ_REGISTRY[name]
    document_html = spec.build()
    iframe = render_html(document_html, height=spec.height, return_iframe_string=True)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = IMAGES_DIR / f"{name}.html"
    out_path.write_text(iframe, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "names",
        nargs="*",
        help="Visualization name(s) to generate (see --list).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available visualization names and exit.",
    )
    args = parser.parse_args(argv)

    if args.list or not args.names:
        print("Available visualizations:")
        for key in sorted(VIZ_REGISTRY):
            print(f"  {key}")
        return 0

    for name in args.names:
        out_path = generate(name)
        print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
