"""
Drug Discovery Module

This module provides tools and utilities for drug discovery workflows, including
molecule manipulation, protein-ligand interactions, and computational chemistry
calculations.
"""

from importlib import import_module
from importlib.resources import files

__all__ = [
    "Protein",
    "Ligand",
    "Pocket",
    "Pose",
    "LigandSet",
    "PoseSet",
    "PreparedSystem",
    "PocketFinder",
    "Docking",
    "ConstrainedDocking",
    "ABFE",
    "ABFEParams",
    "RBFE",
    "RBFEParams",
    "Execution",
    "PlatformStatus",
    "SystemPrep",
    "Molprops",
    "Protonation",
    "Konnektor",
    "KonnektorResult",
    "Patent",
    "Enumerator",
]

DATA_DIR = files("deeporigin.data")
BRD_DATA_DIR = DATA_DIR / "brd"

_LAZY_IMPORTS = {
    "Protein": ("deeporigin.drug_discovery.structures.protein", "Protein"),
    "Ligand": ("deeporigin.drug_discovery.structures.ligand", "Ligand"),
    "LigandSet": ("deeporigin.drug_discovery.structures.ligand", "LigandSet"),
    "Pocket": ("deeporigin.drug_discovery.structures.pocket", "Pocket"),
    "Pose": ("deeporigin.drug_discovery.structures.pose", "Pose"),
    "PoseSet": ("deeporigin.drug_discovery.structures.pose", "PoseSet"),
    "PreparedSystem": (
        "deeporigin.drug_discovery.structures.prepared_system",
        "PreparedSystem",
    ),
    "PocketFinder": ("deeporigin.drug_discovery.pocket_finder", "PocketFinder"),
    "Docking": ("deeporigin.drug_discovery.docking", "Docking"),
    "ConstrainedDocking": (
        "deeporigin.drug_discovery.constrained_docking",
        "ConstrainedDocking",
    ),
    "ABFE": ("deeporigin.drug_discovery.abfe", "ABFE"),
    "ABFEParams": ("deeporigin.drug_discovery.fep_common", "ABFEParams"),
    "RBFE": ("deeporigin.drug_discovery.rbfe", "RBFE"),
    "RBFEParams": ("deeporigin.drug_discovery.fep_common", "RBFEParams"),
    "SystemPrep": ("deeporigin.drug_discovery.system_prep", "SystemPrep"),
    "Molprops": ("deeporigin.drug_discovery.molprops", "Molprops"),
    "Protonation": ("deeporigin.drug_discovery.protonation", "Protonation"),
    "Konnektor": ("deeporigin.drug_discovery.konnektor", "Konnektor"),
    "KonnektorResult": ("deeporigin.drug_discovery.konnektor", "KonnektorResult"),
    "Patent": ("deeporigin.drug_discovery.patent", "Patent"),
    "Enumerator": ("deeporigin.drug_discovery.enumerator", "Enumerator"),
    "Execution": ("deeporigin.drug_discovery.execution", "Execution"),
    "PlatformStatus": ("deeporigin.platform.constants", "PlatformStatus"),
}


def __getattr__(name):
    """Lazily import public drug-discovery symbols."""
    try:
        module_name, attr_name = _LAZY_IMPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = import_module(module_name)
    return getattr(module, attr_name)


def __dir__():
    return __all__ + ["BRD_DATA_DIR", "DATA_DIR"]
