import os
import pathlib
from pathlib import Path
import subprocess

from deeporigin.exceptions import DeepOriginException

__all__ = ["__version__", "DeepOriginException"]

SRC_DIR = pathlib.Path(__file__).parent

version_filename = os.path.join(SRC_DIR, "VERSION")


def _get_pep440_version():
    """get a pep440-compliant local version number"""
    result = subprocess.run(
        ["git", "describe", "--tags", "--dirty", "--long"],
        capture_output=True,
        universal_newlines=True,
        cwd=Path(__file__).parent.parent,
    )
    describe_str = result.stdout.strip()

    # Parse the git describe output
    tag, commits, commit_hash_dirty = describe_str.rsplit("-", 2)
    commit_hash, dirty = (commit_hash_dirty.split("-") + [""])[:2]

    # Format to PEP 440
    if dirty:
        local_version = f"+{commits}.g{commit_hash}.dirty"
    else:
        local_version = f"+{commits}.g{commit_hash}"

    pep440_version = f"{tag}{local_version}"

    return pep440_version


with open(version_filename, "r") as file:
    __version__ = file.read().strip()

    if __version__ == "0.0.0.dev0":
        # in dev mode. we use git to get a "version number"
        # that will change with tags and commits, if possible
        try:
            __version__ = _get_pep440_version()
        except Exception:
            pass
