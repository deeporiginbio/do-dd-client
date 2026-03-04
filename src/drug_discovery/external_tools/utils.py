"""
Backward-compatibility re-exports for external_tools utilities.

Functions have been moved to focused modules:
  - protein_structure: three2one, read_structure, get_structure_sequence,
                       get_gap_and_mut_residues, filter_for_valid_alignments,
                       cif_to_pdb, write_file
  - protein_info:      extract_dict_field, get_protein_info_dict,
                       generate_html_output
"""

from deeporigin.drug_discovery.external_tools.protein_info import (
    extract_dict_field,
    generate_html_output,
    get_protein_info_dict,
)
from deeporigin.drug_discovery.external_tools.protein_structure import (
    cif_to_pdb,
    filter_for_valid_alignments,
    get_gap_and_mut_residues,
    get_structure_sequence,
    read_structure,
    three2one,
    write_file,
)

__all__ = [
    "three2one",
    "read_structure",
    "get_structure_sequence",
    "get_gap_and_mut_residues",
    "filter_for_valid_alignments",
    "cif_to_pdb",
    "write_file",
    "extract_dict_field",
    "get_protein_info_dict",
    "generate_html_output",
]
