"""
Drug Discovery Module

This module provides tools and utilities for drug discovery workflows, including
molecule manipulation, protein-ligand interactions, and computational chemistry
calculations.
"""

from importlib.resources import files

__all__ = [
    "Complex",
    "Protein",
    "Ligand",
    "Pocket",
    "LigandSet",
    "PocketFinder",
    "Docking",
    "ABFE",
]

DATA_DIR = files("deeporigin.data")
BRD_DATA_DIR = DATA_DIR / "brd"


def __getattr__(name):
    if name == "Complex":
        from .complex import Complex

        return Complex
    elif name == "Protein":
        from .structures.protein import Protein

        return Protein
    elif name == "Ligand":
        from .structures.ligand import Ligand

        return Ligand
    elif name == "LigandSet":
        from .structures.ligand import LigandSet

        return LigandSet
    elif name == "Pocket":
        from .structures.pocket import Pocket

        return Pocket
    elif name == "PocketFinder":
        from deeporigin.jobs.pocket_finder import PocketFinder

        return PocketFinder
    elif name == "Docking":
        from deeporigin.jobs.docking import Docking

        return Docking
    elif name == "ABFE":
        from deeporigin.jobs.abfe import ABFE

        return ABFE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return __all__ + ["BRD_DATA_DIR", "DATA_DIR"]
