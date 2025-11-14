"""Constants and configuration values for drug discovery related functionality.

This module contains various constants used throughout the drug discovery pipeline,
including lists of metal atoms and file paths for state management.
"""

from pathlib import Path
from typing import Literal

METALS = ["MG", "CA", "ZN", "MN", "CU", "FE", "NA", "K", "HG", "CO", "U", "CD", "NI"]

# Comprehensive list of metal elements for protein structure analysis
METAL_ELEMENTS = {
    "AC",
    "AG",
    "AL",
    "AM",
    "AS",
    "AU",
    "B",
    "BA",
    "BE",
    "BH",
    "BI",
    "BK",
    "CA",
    "CD",
    "CE",
    "CF",
    "CM",
    "CN",
    "CS",
    "CU",
    "DB",
    "DS",
    "DY",
    "ER",
    "ES",
    "EU",
    "FE",
    "FM",
    "FR",
    "GA",
    "GD",
    "GE",
    "HF",
    "HG",
    "HO",
    "HS",
    "K",
    "LA",
    "LI",
    "LR",
    "LU",
    "MD",
    "MG",
    "MN",
    "MO",
    "MT",
    "NA",
    "NB",
    "ND",
    "NI",
    "NO",
    "NP",
    "OS",
    "PA",
    "TA",
    "PM",
    "PO",
    "PR",
    "PT",
    "PU",
    "RA",
    "RB",
    "RE",
    "RF",
    "RG",
    "RH",
    "RU",
    "SB",
    "SC",
    "SG",
    "SI",
    "SM",
    "SN",
    "SR",
    "TB",
    "TC",
    "TE",
    "TH",
    "TI",
    "TL",
    "TM",
    "U",
    "V",
    "W",
    "YB",
    "ZN",
    "ZR",
    "CO",
    "CR",
    "IN",
    "IR",
    "PB",
    "PD",
}

# File paths
DO_HOME_DIR = Path.home() / ".deeporigin"
STATE_DUMP_PATH = DO_HOME_DIR / "state_dump.pdb"
PROTEINS_DIR = DO_HOME_DIR / "proteins"
LIGANDS_DIR = DO_HOME_DIR / "ligands"

# make sure these directories exist
PROTEINS_DIR.mkdir(parents=True, exist_ok=True)
LIGANDS_DIR.mkdir(parents=True, exist_ok=True)

valid_tools = Literal["ABFE", "RBFE", "Docking"]


# this mapper used to map b/w tool short name and tool key
tool_mapper = {
    "ABFE": "deeporigin.abfe-end-to-end",
    "RBFE": "deeporigin.rbfe-end-to-end",
    "Docking": "deeporigin.bulk-docking",
}

# Base directory for storing pocket files
POCKETS_BASE_DIR = "~/.deeporigin/pockets"
"""Base directory for storing pocket files."""

# Supported atom symbols for small-molecule ligands in this toolkit.
# These intentionally exclude certain elements (e.g., metals, boron) that are
# not supported by downstream tools in typical docking workflows.
SUPPORTED_ATOM_SYMBOLS = {
    "H",
    "C",
    "N",
    "O",
    "F",
    "P",
    "S",
    "Cl",
    "Br",
    "I",
}
"""Set of supported atom symbols for ligands.

This set is used to validate ligands before docking and related operations.
Ligands containing atoms outside this set should be rejected by preparation
utilities.
"""
