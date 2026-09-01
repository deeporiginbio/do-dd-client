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
    "PocketFinderMode",
    "PocketSelection",
    "PocketSelectionAuthor",
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
    "Admet",
    "Metabolism",
    "Protonation",
    "Konnektor",
    "KonnektorResult",
    "Patent",
    "Enumerator",
    "LigandSearch",
    "ProteinPrep",
    "RecommendationView",
    "StructureReport",
    "StructureReportResult",
    "UniprotDiscovery",
    "UniprotDiscoveryCandidate",
]

DATA_DIR = files("deeporigin.data")
BRD_DATA_DIR = DATA_DIR / "brd"

_POCKET_FINDER_MODULE = "deeporigin.drug_discovery.pocket_finder"

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
    "PocketFinder": (_POCKET_FINDER_MODULE, "PocketFinder"),
    "PocketFinderMode": (_POCKET_FINDER_MODULE, "PocketFinderMode"),
    "PocketSelection": (_POCKET_FINDER_MODULE, "PocketSelection"),
    "PocketSelectionAuthor": (_POCKET_FINDER_MODULE, "PocketSelectionAuthor"),
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
    "Admet": ("deeporigin.drug_discovery.admet", "Admet"),
    "Metabolism": ("deeporigin.drug_discovery.metabolism", "Metabolism"),
    "Protonation": ("deeporigin.drug_discovery.protonation", "Protonation"),
    "Konnektor": ("deeporigin.drug_discovery.konnektor", "Konnektor"),
    "KonnektorResult": ("deeporigin.drug_discovery.konnektor", "KonnektorResult"),
    "Patent": ("deeporigin.drug_discovery.patent", "Patent"),
    "Enumerator": ("deeporigin.drug_discovery.enumerator", "Enumerator"),
    "LigandSearch": ("deeporigin.drug_discovery.ligand_search", "LigandSearch"),
    "ProteinPrep": ("deeporigin.drug_discovery.protein_prep", "ProteinPrep"),
    "RecommendationView": (
        "deeporigin.drug_discovery.protein_prep",
        "RecommendationView",
    ),
    "StructureReport": (
        "deeporigin.drug_discovery.structure_report",
        "StructureReport",
    ),
    "StructureReportResult": (
        "deeporigin.drug_discovery.structure_report",
        "StructureReportResult",
    ),
    "UniprotDiscovery": (
        "deeporigin.drug_discovery.uniprot_discovery",
        "UniprotDiscovery",
    ),
    "UniprotDiscoveryCandidate": (
        "deeporigin.drug_discovery.uniprot_discovery",
        "UniprotDiscoveryCandidate",
    ),
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
