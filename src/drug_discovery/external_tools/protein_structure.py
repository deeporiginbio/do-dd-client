"""
Utility functions for protein structure analysis.

Provides functions for working with protein structure files (PDB, CIF),
sequence extraction, sequence alignment analysis, and format conversion.
"""

import os

from beartype import beartype


@beartype
def three2one(prot) -> str:
    """Translate a protein sequence from 3 to 1 letter code.

    Args:
        prot (str): The protein sequence in 3 letter code.

    Returns:
        str: The protein sequence in 1 letter code.
    """
    code = {
        "GLY": "G",
        "ALA": "A",
        "LEU": "L",
        "ILE": "I",
        "ARG": "R",
        "LYS": "K",
        "MET": "M",
        "CYS": "C",
        "TYR": "Y",
        "THR": "T",
        "PRO": "P",
        "SER": "S",
        "TRP": "W",
        "ASP": "D",
        "GLU": "E",
        "ASN": "N",
        "GLN": "Q",
        "PHE": "F",
        "HIS": "H",
        "VAL": "V",
        "M3L": "K",
        "MSE": "M",
        "CAS": "C",
        "CSO": "C",
        "SEP": "S",
    }

    new_protein = ""
    for a in prot:
        new_protein += code.get(a, "?")

    return new_protein


def read_structure(file_name, model=1, use_author_fields_flag=True):
    """
    Read a structure file and return the file object and structure object.

    Args:
        file_name (str): The name of the structure file.
        model (int, optional): The model number to read from the file. Defaults to 1.
        use_author_fields_flag (bool, optional): Flag indicating whether to use author fields. Defaults to True.

    Returns:
        tuple: A tuple containing the file object and structure object.
    """
    import biotite.structure as struc
    import biotite.structure.io.pdb as pdb

    if file_name.endswith(".cif"):
        file = pdb.PDBFile.read(file_name)
        structure = pdb.get_structure(
            file, model=model, use_author_fields=use_author_fields_flag
        )
    elif file_name.endswith(".pdb"):
        file = pdb.PDBFile.read(file_name)
        structure = pdb.get_structure(file, model=1)
    else:
        print(f"Error: unsupported file type {file_name}")
        return None

    structure = structure[struc.filter_amino_acids(structure)]

    return file, structure


def get_structure_sequence(structure):
    """
    Get the sequence of a given structure.

    Args:
        structure: The structure object.

    Returns:
        The sequence of the structure.
    """
    import biotite.structure as struc

    return three2one(struc.get_residues(structure)[1])


def get_gap_and_mut_residues(alignment, res_ids):
    """
    Get the gap and mutation residues from an alignment.

    Args:
        alignment (Alignment): The alignment object.
        res_ids (list): The list of residue IDs.

    Returns:
        tuple: A tuple containing two lists - gap_id_list and mut_id_list.
            - gap_id_list (list): The list of residue IDs corresponding to gaps.
            - mut_id_list (list): The list of residue IDs corresponding to mutations.
    """
    ali_len = len(alignment.trace)
    ali_sequnces = alignment.get_gapped_sequences()
    gap_id_list = []
    mut_id_list = []
    for i in range(ali_len):
        s1 = ali_sequnces[0][i]
        s2 = ali_sequnces[1][i]
        if s1 != "-" and s1 != s2:
            j = alignment.trace[i][0]
            if s2 == "-":
                gap_id_list.append(res_ids[j])
            else:
                mut_id_list.append(res_ids[j])

    return gap_id_list, mut_id_list


def filter_for_valid_alignments(
    alignments, res_list_1=None, res_list_2=None, n_breaks_tol=0
):
    """
    Filters a list of alignments based on certain criteria.

    Args:
        alignments (list): A list of alignments to be filtered.
        res_list_1 (list, optional): A list of residues for the first sequence. Defaults to None.
        res_list_2 (list, optional): A list of residues for the second sequence. Defaults to None.
        n_breaks_tol (int, optional): The maximum number of breaks allowed in the alignment. Defaults to 0.

    Returns:
        list: A new list of alignments that meet the filtering criteria.
    """
    new_alignments = []
    for alignment in alignments:
        b_valid = True
        trace = alignment.trace
        n_breaks = 0
        for i in range(len(trace) - 1):
            if res_list_1 is not None:
                a1 = trace[i][0]
                b1 = trace[i + 1][0]
                if a1 != -1 and b1 != -1 and res_list_1[a1] != res_list_1[b1] - 1:
                    n_breaks += 1
                    if n_breaks > n_breaks_tol:
                        b_valid = False
                        break
            if res_list_2 is not None:
                a2 = trace[i][1]
                b2 = trace[i + 1][1]
                if a2 != -1 and b2 != -1 and res_list_2[a2] != res_list_2[b2] - 1:
                    n_breaks += 1
                    if n_breaks > n_breaks_tol:
                        b_valid = False
                        break
        if b_valid:
            new_alignments.append(alignment)

    return new_alignments


def cif_to_pdb(input_file_path, output_file_path):
    """
    Convert a .cif file to a .pdb file.

    Args:
        input_file_path (str): The path to the input .cif file.
        output_file_path (str): The path to save the output .pdb file.
    """
    from Bio.PDB.MMCIFParser import MMCIFParser
    from Bio.PDB.PDBIO import PDBIO

    _, file_name = os.path.split(input_file_path)
    base_name = os.path.splitext(file_name)[0]

    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure(base_name, input_file_path)

    io = PDBIO()
    io.set_structure(structure)
    io.save(output_file_path)
    print(f"converted {input_file_path} .cif file to {output_file_path} .pdb file")


def write_file(path, content):
    """
    Write content to a file at the specified path.

    Args:
        path (str): The path to the file.
        content (str): The content to write to the file.
    """
    if dir_name := os.path.dirname(path):
        os.makedirs(dir_name, exist_ok=True)
    with open(path, "w") as file:
        file.write(content)
