"""Tests for Mol* HTML builders."""

import base64
from pathlib import Path

import pytest

from deeporigin.viz.molstar_html import (
    MOLSTAR_HOST_ASSET_BASE_URL,
    MOLSTAR_JS_URL,
    css_color_to_hex,
    ligand_data_for_js,
    render_docking_box_html,
    render_ligand_html,
    render_protein_html,
    render_protein_with_box_and_poses_html,
    render_protein_with_pockets_and_poses_html,
    render_protein_with_pockets_html,
    render_protein_with_poses_html,
)

_FIXTURE_PDB = (
    Path(__file__).parent
    / "fixtures"
    / "entities"
    / "proteins"
    / "51f3f8008c28559b18cb6eb1ae048b24604274a91659e8bc12d27151de594c80.pdb"
)
_FIXTURE_POCKET = (
    Path(__file__).parent / "fixtures" / "files" / "pocketfinder" / "pocket_1.pdb"
)
_FIXTURE_SDF = Path(__file__).parent / "fixtures" / "files" / "testing" / "brd-2.sdf"


def test_render_protein_html_includes_molstar_bundle_and_api() -> None:
    """Generated HTML references the hosted bundle and loadFromRawContent."""
    html = render_protein_html(pdb_path=str(_FIXTURE_PDB))

    assert MOLSTAR_JS_URL in html
    assert "molstarLib.initViewer" in html
    assert "loadFromRawContent" in html
    assert '"pdb"' in html
    assert "molstar-error" in html
    assert f'<base href="{MOLSTAR_HOST_ASSET_BASE_URL}"' in html


def test_render_protein_html_embeds_pdb_content() -> None:
    """PDB file content is embedded in the generated HTML as base64."""
    pdb_text = _FIXTURE_PDB.read_text(encoding="utf-8")
    html = render_protein_html(pdb_path=str(_FIXTURE_PDB))
    pdb_b64 = base64.b64encode(pdb_text.encode("utf-8")).decode("ascii")

    assert f'atob("{pdb_b64}")' in html
    assert "HEADER    HYDROLASE/HYDROLASE INHIBITOR" not in html


def test_render_protein_html_custom_style() -> None:
    """Custom representation style is passed through to generated JS."""
    html = render_protein_html(pdb_path=str(_FIXTURE_PDB), style="ball-and-stick")

    assert "ball-and-stick" in html


def test_render_protein_html_escapes_script_tags_in_pdb(tmp_path: Path) -> None:
    """PDB text with </script> is base64-encoded so it cannot break out of script tags."""
    pdb_path = tmp_path / "escape-test.pdb"
    pdb_path.write_text("REMARK </script><script>alert(1)</script>\n", encoding="utf-8")

    html = render_protein_html(pdb_path=str(pdb_path))

    assert "</script><script>alert(1)</script>" not in html
    pdb_text = pdb_path.read_text(encoding="utf-8")
    pdb_b64 = base64.b64encode(pdb_text.encode("utf-8")).decode("ascii")
    assert f'atob("{pdb_b64}")' in html


def test_render_protein_html_escapes_script_tags_in_style(tmp_path: Path) -> None:
    """Style values with </script> are JSON-escaped so they cannot break script tags."""
    pdb_path = tmp_path / "minimal.pdb"
    pdb_path.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000\n", encoding="utf-8"
    )

    html = render_protein_html(
        pdb_path=str(pdb_path), style="</script><script>alert(1)</script>"
    )

    assert "</script><script>alert(1)</script>" not in html
    assert '"\\u003c/script>' in html


def test_render_protein_html_missing_file_raises() -> None:
    """Missing PDB path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Structure file not found"):
        render_protein_html(pdb_path="/nonexistent/path/to/protein.pdb")


def test_css_color_to_hex_red() -> None:
    """Named CSS colors convert to hex integers for molstarLib."""
    assert css_color_to_hex("red") == 0xFF0000
    assert css_color_to_hex("#ff5733") == 0xFF5733
    assert css_color_to_hex("rgb(0, 128, 255)") == 0x0080FF
    assert css_color_to_hex("rgba(0, 128, 255, 0.5)") == 0x0080FF


def test_css_color_to_hex_rejects_invalid_rgb() -> None:
    """Four-channel rgb() syntax is rejected."""
    with pytest.raises(ValueError, match="Unsupported CSS color"):
        css_color_to_hex("rgb(0, 128, 255, 0.5)")


def test_css_color_to_hex_rejects_invalid_rgba_alpha() -> None:
    """Malformed rgba alpha strings raise the standard color error."""
    with pytest.raises(ValueError, match="Unsupported CSS color"):
        css_color_to_hex("rgba(0, 128, 255, not-a-number)")


def test_render_protein_with_pockets_html_rejects_invalid_alpha() -> None:
    """Surface alpha values outside [0, 1] raise ValueError."""
    with pytest.raises(ValueError, match="protein_surface_alpha"):
        render_protein_with_pockets_html(
            pdb_path=str(_FIXTURE_PDB),
            pocket_paths=[str(_FIXTURE_POCKET)],
            pocket_colors=["red"],
            pocket_labels=["pocket-1"],
            protein_surface_alpha=1.5,
        )


def test_render_protein_with_pockets_html_api() -> None:
    """Generated HTML references renderStructureAndPockets with legacy alpha defaults."""
    html = render_protein_with_pockets_html(
        pdb_path=str(_FIXTURE_PDB),
        pocket_paths=[str(_FIXTURE_POCKET)],
        pocket_colors=["red"],
        pocket_labels=["pocket-1"],
    )

    assert "renderStructureAndPockets" in html
    assert '"gaussian-surface"' in html
    assert "0.1" in html
    assert "0.25" in html
    assert '"uniform"' in html
    assert str(0xFF0000) in html


def test_render_protein_with_pockets_embeds_pockets() -> None:
    """Pocket PDB content is embedded in the generated HTML as base64."""
    pocket_text = _FIXTURE_POCKET.read_text(encoding="utf-8")
    pocket_b64 = base64.b64encode(pocket_text.encode("utf-8")).decode("ascii")
    html = render_protein_with_pockets_html(
        pdb_path=str(_FIXTURE_PDB),
        pocket_paths=[str(_FIXTURE_POCKET)],
        pocket_colors=["red"],
        pocket_labels=["pocket-1"],
    )

    assert pocket_b64 in html
    assert "COMPND    pocket" not in html


def test_pocket_json_script_escape(tmp_path: Path) -> None:
    """Malicious pocket labels cannot break out of script tags."""
    pdb_path = tmp_path / "minimal.pdb"
    pdb_path.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000\n", encoding="utf-8"
    )
    pocket_path = tmp_path / "pocket.pdb"
    pocket_path.write_text("COMPND    pocket\n", encoding="utf-8")

    html = render_protein_with_pockets_html(
        pdb_path=str(pdb_path),
        pocket_paths=[str(pocket_path)],
        pocket_colors=["red"],
        pocket_labels=["</script><script>alert(1)</script>"],
    )

    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script>" in html


def test_render_protein_with_pockets_mismatched_lengths_raises() -> None:
    """Mismatched pocket list lengths raise ValueError."""
    with pytest.raises(ValueError, match="same length"):
        render_protein_with_pockets_html(
            pdb_path=str(_FIXTURE_PDB),
            pocket_paths=[str(_FIXTURE_POCKET)],
            pocket_colors=["red", "blue"],
            pocket_labels=["pocket-1"],
        )


def test_render_ligand_html_includes_api() -> None:
    """Ligand HTML references loadFromRawContent with sdf format."""
    html = render_ligand_html(sdf_path=str(_FIXTURE_SDF))

    assert MOLSTAR_JS_URL in html
    assert "loadFromRawContent" in html
    assert '"sdf"' in html
    # Use read_text (not read_bytes) so CRLF checkouts on Windows match
    # Path.read_text newline translation used by render_ligand_html.
    sdf_text = _FIXTURE_SDF.read_text(encoding="utf-8")
    sdf_b64 = base64.b64encode(sdf_text.encode("utf-8")).decode("ascii")
    assert f'atob("{sdf_b64}")' in html


def test_render_protein_with_poses_html_api() -> None:
    """Pose HTML references visualizeDockedLigands with per-ligand payloads."""
    payloads = [
        ligand_data_for_js(path=str(_FIXTURE_SDF), label="brd-2"),
    ]
    html = render_protein_with_poses_html(
        pdb_path=str(_FIXTURE_PDB),
        ligand_payloads=payloads,
    )

    assert "visualizeDockedLigands" in html
    assert "brd-2" in html
    assert payloads[0]["dataB64"] in html


def test_render_protein_with_poses_empty_raises() -> None:
    """Empty ligand_payloads raises ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        render_protein_with_poses_html(
            pdb_path=str(_FIXTURE_PDB),
            ligand_payloads=[],
        )


def test_render_protein_with_pockets_and_poses_html_api() -> None:
    """Combined HTML references renderStructureWithPocketsAndLigands."""
    payloads = [ligand_data_for_js(path=str(_FIXTURE_SDF), label="pose-1")]
    html = render_protein_with_pockets_and_poses_html(
        pdb_path=str(_FIXTURE_PDB),
        pocket_paths=[str(_FIXTURE_POCKET)],
        pocket_colors=["red"],
        pocket_labels=["pocket-1"],
        ligand_payloads=payloads,
    )

    assert "renderStructureWithPocketsAndLigands" in html
    assert '"gaussian-surface"' in html
    assert "pose-1" in html
    assert "0.25" in html


def test_ligand_label_script_escape(tmp_path: Path) -> None:
    """Malicious ligand labels cannot break out of script tags."""
    pdb_path = tmp_path / "minimal.pdb"
    pdb_path.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000\n", encoding="utf-8"
    )
    sdf_path = tmp_path / "lig.sdf"
    sdf_path.write_text(_FIXTURE_SDF.read_text(encoding="utf-8"), encoding="utf-8")

    html = render_protein_with_poses_html(
        pdb_path=str(pdb_path),
        ligand_payloads=[
            ligand_data_for_js(
                path=str(sdf_path),
                label="</script><script>alert(1)</script>",
            )
        ],
    )

    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script>" in html


def test_render_docking_box_html_api() -> None:
    """Docking-box HTML loads protein then calls renderBoundingBox with min/max."""
    html = render_docking_box_html(
        pdb_path=str(_FIXTURE_PDB),
        box_center=[10.0, 20.0, 30.0],
        box_size=[4.0, 6.0, 8.0],
    )

    assert "loadFromRawContent" in html
    assert "renderBoundingBox" in html
    assert "[8.0, 17.0, 26.0]" in html
    assert "[12.0, 23.0, 34.0]" in html
    assert "0.2" in html
    assert str(0xFFFF00) in html
    assert "showDockingBoxControls: false" in html


def test_render_docking_box_html_applies_rotation_deg() -> None:
    """Static box HTML applies rotation via DockingBoxManager after render."""
    html = render_docking_box_html(
        pdb_path=str(_FIXTURE_PDB),
        box_center=[10.0, 20.0, 30.0],
        box_size=[4.0, 6.0, 8.0],
        rotation_deg=[0.0, 45.0, 0.0],
    )

    assert "applyDockingBoxRotation" in html
    assert "dockingBoxManager" in html
    assert "setRotation" in html
    assert "[0.0, 45.0, 0.0]" in html


def test_render_docking_box_rejects_non_positive_size() -> None:
    """Non-positive box extents raise ValueError."""
    with pytest.raises(ValueError, match="positive"):
        render_docking_box_html(
            pdb_path=str(_FIXTURE_PDB),
            box_center=[0.0, 0.0, 0.0],
            box_size=[10.0, 0.0, 10.0],
        )


def test_render_docking_box_rejects_non_numeric_geometry() -> None:
    """Non-numeric center/size/radius raise ValueError, not TypeError."""
    with pytest.raises(ValueError, match="finite"):
        render_docking_box_html(
            pdb_path=str(_FIXTURE_PDB),
            box_center=["x", 0.0, 0.0],  # type: ignore[list-item]
            box_size=[10.0, 10.0, 10.0],
        )
    with pytest.raises(ValueError, match="radius"):
        render_docking_box_html(
            pdb_path=str(_FIXTURE_PDB),
            box_center=[0.0, 0.0, 0.0],
            box_size=[10.0, 10.0, 10.0],
            radius="wide",  # type: ignore[arg-type]
        )


def test_render_docking_box_rejects_invalid_color() -> None:
    """Non-int or out-of-range color raises ValueError."""
    with pytest.raises(ValueError, match="color"):
        render_docking_box_html(
            pdb_path=str(_FIXTURE_PDB),
            box_center=[0.0, 0.0, 0.0],
            box_size=[10.0, 10.0, 10.0],
            color="yellow",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="color"):
        render_docking_box_html(
            pdb_path=str(_FIXTURE_PDB),
            box_center=[0.0, 0.0, 0.0],
            box_size=[10.0, 10.0, 10.0],
            color=0x1000000,
        )


def test_render_protein_with_box_and_poses_html_api() -> None:
    """Box+poses HTML composes visualizeDockedLigands then renderBoundingBox."""
    payloads = [
        ligand_data_for_js(path=str(_FIXTURE_SDF), label="brd-2"),
    ]
    html = render_protein_with_box_and_poses_html(
        pdb_path=str(_FIXTURE_PDB),
        box_center=[10.0, 20.0, 30.0],
        box_size=[4.0, 6.0, 8.0],
        ligand_payloads=payloads,
    )

    assert "visualizeDockedLigands" in html
    assert "renderBoundingBox" in html
    assert "brd-2" in html
    assert payloads[0]["dataB64"] in html
    assert "[8.0, 17.0, 26.0]" in html
    assert "[12.0, 23.0, 34.0]" in html
    assert str(0xFFFF00) in html
    assert "showDockingBoxControls: false" in html


def test_render_protein_with_box_and_poses_html_applies_rotation_deg() -> None:
    """Box+poses HTML applies rotation via DockingBoxManager after render."""
    payloads = [
        ligand_data_for_js(path=str(_FIXTURE_SDF), label="brd-2"),
    ]
    html = render_protein_with_box_and_poses_html(
        pdb_path=str(_FIXTURE_PDB),
        box_center=[10.0, 20.0, 30.0],
        box_size=[4.0, 6.0, 8.0],
        ligand_payloads=payloads,
        rotation_deg=[0.0, 45.0, 0.0],
    )

    assert "applyDockingBoxRotation" in html
    assert "[0.0, 45.0, 0.0]" in html


def test_render_protein_with_box_and_poses_empty_raises() -> None:
    """Empty ligand_payloads raise ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        render_protein_with_box_and_poses_html(
            pdb_path=str(_FIXTURE_PDB),
            box_center=[0.0, 0.0, 0.0],
            box_size=[10.0, 10.0, 10.0],
            ligand_payloads=[],
        )
