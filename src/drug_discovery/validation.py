"""This module contains functions for validating Ligands and Proteins."""

import re
from typing import Any

from beartype import beartype
from rdkit import Chem

from deeporigin.drug_discovery.constants import ELEMENT_SYMBOLS

# https://github.dev/mcs07/ChemDataExtractor
SMILES_RE = re.compile(
    r"^([BCNOPSFIbcnosp*]|Cl|Br|\[\d*(%(e)s|se|as|\*)(@+([THALSPBO]\d+)?)?(H\d?)?([\-+]+\d*)?(:\d+)?\])"
    r"([BCNOPSFIbcnosp*]|Cl|Br|\[\d*(%(e)s|se|as|\*)(@+([THALSPBO]\d+)?)?(H\d?)?([\-+]+\d*)?(:\d+)?\]|"
    r"[\-=#$:\\/\(\)%%\.+\d])*$" % {"e": "|".join(ELEMENT_SYMBOLS)}
)


def check_brackets(text: str) -> tuple[int, list[tuple[int, str]]]:
    """Check bracket balance in the input text and return unmatched bracket info.

    Args:
        text: Input string to check for bracket balance.

    Returns:
        A tuple containing:
            - nesting_level: Final depth of unmatched opening brackets
              (-1 if an unmatched closing bracket was found).
            - unmatched_stack: List of (index, char) tuples for unmatched brackets.
    """
    opening_to_closing = {"(": ")", "[": "]", "{": "}"}
    closing_to_opening = {v: k for k, v in opening_to_closing.items()}

    unmatched_stack: list[tuple[int, str]] = []
    for index, char in enumerate(text):
        if char in opening_to_closing:
            unmatched_stack.append((index, char))
        elif char in closing_to_opening:
            if unmatched_stack and unmatched_stack[-1][1] == closing_to_opening[char]:
                unmatched_stack.pop()
            else:
                # Found unmatched closing bracket
                return -1, [(index, char)]

    return len(unmatched_stack), unmatched_stack


@beartype
def is_valid_smiles(smiles: Any) -> bool:
    """Check if a string is a valid SMILES representation.

    Uses RDKit to parse the SMILES string and verify it can be converted to a
    molecule object. Handles empty strings, None values, and strings wrapped in
    quotes.

    Args:
        smiles: Input to validate. Can be any type, but only strings are checked.

    Returns:
        True if the input is a valid SMILES string, False otherwise.
    """
    if isinstance(smiles, str) and smiles:
        smiles = smiles.strip().strip("'").strip('"')
        try:
            mol = Chem.MolFromSmiles(smiles)
            return mol is not None
        except Exception:
            return False
    return False


@beartype
def is_smiles_like(string: str) -> bool:
    """Check if a string looks like a SMILES string using pattern matching.

    Validates that the string has balanced brackets and matches a SMILES-like
    pattern. This is a faster but less accurate check than is_valid_smiles.

    Args:
        string: Input string to check.

    Returns:
        True if the string appears to be SMILES-like, False otherwise.
    """
    if not isinstance(string, str) or not string.strip():
        return False
    string = string.strip()

    level, _ = check_brackets(string)
    if level != 0:
        return False

    return bool(SMILES_RE.match(string))


@beartype
def matches_mol_rules(smiles_like_str: str) -> bool:
    """Check if a SMILES-like string matches basic molecular rules.

    Validates that the string represents a reasonable molecule by checking:
    - Has at least 4 atoms
    - Has at least 2 carbon atoms
    - Common organic elements (C, N, O, S, F) make up at least 40% of atoms

    Args:
        smiles_like_str: Input SMILES-like string to validate.

    Returns:
        True if the string matches molecular rules, False otherwise.
    """
    smiles_like_str = smiles_like_str.lower()

    def count_atoms(inp: str) -> dict[str, int]:
        """Count occurrences of each atom type character in the input string.

        Args:
            inp: Input string to count atoms in.

        Returns:
            Dictionary mapping atom type characters to their counts.
        """
        atom_types = "abcdefghiklmnopqrstuvwxyz"  # except j
        counts: dict[str, int] = dict.fromkeys(atom_types, 0)
        pattern = re.compile(r"([a-ik-z])")
        matches = pattern.findall(inp)
        for match in matches:
            if match in counts:
                counts[match] += 1
        return counts

    counts = count_atoms(smiles_like_str)

    n_atoms = sum(counts.values())

    score = n_atoms < 4
    score += counts["c"] < 2
    score += (
        counts["c"] + counts["n"] + counts["o"] + counts["s"] + counts["f"]
    ) > 0.4 * n_atoms

    return score < 2
