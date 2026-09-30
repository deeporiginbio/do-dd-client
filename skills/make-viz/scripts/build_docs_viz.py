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


def _fixture_1eby() -> str:
    """Return the path to the bundled 1EBY holo structure PDB."""
    return str(REPO_ROOT / "tests" / "fixtures" / "1eby.pdb")


def _prepared_system_pdb() -> str:
    """Return a representative solvated system PDB from test fixtures."""
    return str(
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "files"
        / "tool-runs"
        / "d037ce61-c52e-49bc-9507-1f300993d9fe"
        / "system.pdb"
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


def _build_1eby() -> str:
    """1EBY holo protein (mirrors ``Protein.from_pdb_id('1EBY').show()``)."""
    from deeporigin.viz.molstar_html import render_protein_html

    return render_protein_html(pdb_path=_fixture_1eby())


def _build_5qsp() -> str:
    """5QSP with gaps visible (mirrors docs loop-modelling section, pre-``model_loops``)."""
    from deeporigin.drug_discovery import Protein
    from deeporigin.viz.molstar_html import render_protein_html

    protein = Protein.from_pdb_id("5QSP")
    return render_protein_html(pdb_path=protein._dump_state())


def _build_5qsp_lm() -> str:
    """5QSP after loop modelling (docs ``5QSP-lm.html``).

    Uses the same PDB fetch as ``_build_5qsp`` until a checked-in loop-modelled
    structure snapshot is added to fixtures. Re-run ``model_loops()`` locally when
    updating this visual.
    """
    return _build_5qsp()


def _build_1eby_docked_poses() -> str:
    """1EBY with co-crystal ligand overlaid (docked-pose style docs embed)."""
    from deeporigin.drug_discovery import Protein
    from deeporigin.drug_discovery.docking_common import ligand_payloads_for_viewer
    from deeporigin.viz.molstar_html import render_protein_with_poses_html

    protein = Protein.from_file(_fixture_1eby())
    ligand = protein.extract_ligand()
    return render_protein_with_poses_html(
        pdb_path=protein._dump_state(),
        ligand_payloads=ligand_payloads_for_viewer([ligand]),
    )


def _build_brd_ligands() -> str:
    """BRD ligand set carousel (mirrors ``LigandSet.from_sdf(...).show()``)."""
    from deeporigin.drug_discovery import DATA_DIR, LigandSet
    from deeporigin.drug_discovery.docking_common import ligand_payloads_for_viewer
    from deeporigin.viz.molstar_html import render_ligand_set_html

    ligands = LigandSet.from_sdf(DATA_DIR / "ligands" / "ligands-brd-all.sdf")
    return render_ligand_set_html(
        ligand_payloads=ligand_payloads_for_viewer(list(ligands.ligands)),
    )


def _build_ligand() -> str:
    """Single ligand extracted from 1EBY (legacy ``ligand.html`` embed)."""
    from deeporigin.drug_discovery import Protein
    from deeporigin.viz.molstar_html import render_ligand_html

    protein = Protein.from_file(_fixture_1eby())
    ligand = protein.extract_ligand()
    return render_ligand_html(sdf_path=ligand.to_sdf())


def _build_crystal_ligand() -> str:
    """1EBY holo structure with embedded co-crystal ligand."""
    return _build_1eby()


def _build_prepared_system() -> str:
    """Solvated ABFE system PDB (mirrors ``PreparedSystem.show()``)."""
    from deeporigin.viz.molstar_html import render_protein_html

    return render_protein_html(pdb_path=_prepared_system_pdb())


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
    "1eby": VizSpec(build=_build_1eby, height=600),
    "1eby-docked-poses": VizSpec(build=_build_1eby_docked_poses, height=650),
    "5QSP": VizSpec(build=_build_5qsp, height=600),
    "5QSP-lm": VizSpec(build=_build_5qsp_lm, height=600),
    "brd-protein": VizSpec(build=_build_brd_protein, height=600),
    "brd-no-water": VizSpec(build=_build_brd_no_water, height=600),
    "brd-pocket": VizSpec(build=_build_brd_pocket, height=600),
    "brd-docked-poses": VizSpec(build=_build_brd_docked_poses, height=600),
    "brd-docking-box": VizSpec(build=_build_brd_docking_box, height=600),
    "brd-ligands": VizSpec(build=_build_brd_ligands, height=600),
    "crystal-ligand": VizSpec(build=_build_crystal_ligand, height=600),
    "ligand": VizSpec(build=_build_ligand, height=600),
    "prepared-system": VizSpec(build=_build_prepared_system, height=630),
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
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate every registered visualization.",
    )
    args = parser.parse_args(argv)

    if args.list:
        print("Available visualizations:")
        for key in sorted(VIZ_REGISTRY):
            print(f"  {key}")
        return 0

    if args.all:
        args.names = sorted(VIZ_REGISTRY)

    if not args.names:
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
