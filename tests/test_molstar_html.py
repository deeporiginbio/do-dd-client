"""Tests for Mol* HTML builders."""

import base64
from pathlib import Path

import pytest

from deeporigin.viz.molstar_html import (
    MOLSTAR_HOST_ASSET_BASE_URL,
    MOLSTAR_JS_URL,
    render_protein_html,
)

_FIXTURE_PDB = (
    Path(__file__).parent
    / "fixtures"
    / "entities"
    / "proteins"
    / "51f3f8008c28559b18cb6eb1ae048b24604274a91659e8bc12d27151de594c80.pdb"
)


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
    pdb_b64 = base64.b64encode(pdb_path.read_bytes()).decode("ascii")
    assert f'atob("{pdb_b64}")' in html


def test_render_protein_html_missing_file_raises() -> None:
    """Missing PDB path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Structure file not found"):
        render_protein_html(pdb_path="/nonexistent/path/to/protein.pdb")
