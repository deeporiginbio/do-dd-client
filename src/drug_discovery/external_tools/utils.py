"""
Utility functions for drug discovery and protein structure analysis.

This module provides a collection of utility functions for working with protein structures,
sequence analysis, and drug discovery tasks. It includes functionality for:
- Protein sequence conversion (3-letter to 1-letter code)
- Structure file handling (PDB, CIF formats)
- Protein information retrieval from RCSB PDB
- Structure and sequence alignment analysis
- HTML report generation for protein information

Key functions:
- three2one(): Convert protein sequences between 3-letter and 1-letter codes
- download_struct(): Download protein structures from RCSB PDB
- read_structure(): Read and parse structure files
- get_structure_sequence(): Extract sequence information from structures
- get_protein_info_dict(): Retrieve comprehensive protein information from PDB
- generate_html_output(): Generate interactive HTML reports for protein data

The module integrates with various bioinformatics tools and databases to provide
a comprehensive set of utilities for protein structure analysis and drug discovery.
"""

import os
import pathlib

from beartype import beartype
import requests


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

    newprot = ""
    for a in prot:
        newprot += code.get(a, "?")

    return newprot


def read_structure(file_name, model=1, use_author_fields_flag=True):
    """
    Read a structure file and return the file object and structure object.

    Args:
        file_name (str): The name of the structure file.
        model (int, optional): The model number to read from the file. Defaults to 1.
        use_author_fields_flag (bool, optional): Flag indicating whether to use author fields. Defaults to True.

    Returns:
        tuple: A tuple containing the file object and structure object.

    Raises:
        None
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
        # elif s1=='-':
        #   print (i)

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
                # if a2!=-1 and b2==-1 and a2<len(res_list_2)-1 and res_list_2[a2]==res_list_2[a2+1]-1:
                # if a2==-1 and b2!=-1 and b2>0 and res_list_2[b2]==res_list_2[b2-1]+1:
        if b_valid:
            new_alignments.append(alignment)

    return new_alignments


def cif_to_pdb(input_file_path, output_file_path):
    """
    Convert a .cif file to a .pdb file.

    Args:
        input_file_path (str): The path to the input .cif file.
        output_file_path (str): The path to save the output .pdb file.

    Returns:
        None
    """
    from Bio.PDB.MMCIFParser import MMCIFParser
    from Bio.PDB.PDBIO import PDBIO

    _, file_name = os.path.split(input_file_path)
    base_name = os.path.splitext(file_name)[0]

    parser = MMCIFParser(QUIET=True)  # Use QUIET=True to suppress warnings
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


def extract_dict_field(json, json_keys, default_return="N/A"):
    """
    Extract a field from a nested dictionary using a list of keys.

    Args:
        json (dict): The dictionary to extract from.
        json_keys (list): List of keys to traverse in the dictionary.
        default_return (str, optional): Default value to return if the field is not found. Defaults to "N/A".

    Returns:
        The value at the specified path in the dictionary, or the default value if not found.
    """
    result = json.copy()
    for key in json_keys:
        try:
            result = result[key]
        except Exception:
            return default_return
    return default_return if result is None else result


def get_protein_info_dict(pdb_id: str):
    """
    Retrieve protein information from RCSB PDB using GraphQL API.

    Args:
        pdb_id (str): The PDB ID of the protein.

    Returns:
        dict: A dictionary containing comprehensive protein information including:
            - Title, method, resolution
            - R-factors
            - Classification
            - Source organism
            - Sequence information
            - Citations
            - Macromolecules
            - Small molecules
            - Assemblies
    """
    current_dir = pathlib.Path(__file__).parent
    assets = current_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    with open(f"{assets}/protein_info.gql", "r") as e:
        query_protein = e.read()

    url = "https://data.rcsb.org/graphql"
    payload = {"query": query_protein, "variables": {"id": pdb_id}}

    info = {}

    response = requests.post(url, json=payload)
    if response.status_code == 200:
        data = response.json()

        info = {}
        info["title"] = extract_dict_field(data, ["data", "entry", "struct", "title"])
        info["method"] = extract_dict_field(
            data, ["data", "entry", "exptl", 0, "method"]
        )
        info["resolution"] = extract_dict_field(
            data, ["data", "entry", "refine", 0, "ls_d_res_high"]
        )
        info["r_factor_work"] = extract_dict_field(
            data, ["data", "entry", "refine", 0, "ls_R_factor_R_work"]
        )
        info["r_factor_free"] = extract_dict_field(
            data, ["data", "entry", "refine", 0, "ls_R_factor_R_free"]
        )
        info["classification"] = extract_dict_field(
            data, ["data", "entry", "struct_keywords", "pdbx_keywords"]
        )
        info["source_organism"] = extract_dict_field(
            data,
            [
                "data",
                "entry",
                "polymer_entities",
                0,
                "rcsb_entity_source_organism",
                0,
                "scientific_name",
            ],
        )
        info["n_mutations"] = extract_dict_field(
            data,
            [
                "data",
                "entry",
                "polymer_entities",
                0,
                "entity_poly",
                "rcsb_mutation_count",
            ],
        )
        info["sequence_length"] = extract_dict_field(
            data,
            [
                "data",
                "entry",
                "polymer_entities",
                0,
                "entity_poly",
                "rcsb_sample_sequence_length",
            ],
        )
        info["canonical_sequence"] = extract_dict_field(
            data,
            [
                "data",
                "entry",
                "polymer_entities",
                0,
                "entity_poly",
                "pdbx_seq_one_letter_code_can",
            ],
        )

        info["pubmed_abstract"] = extract_dict_field(
            data, ["data", "entry", "pubmed", "rcsb_pubmed_abstract_text"]
        )

        info["citations"] = []
        citations = extract_dict_field(data, ["data", "entry", "citation"], [])
        for citation in citations:
            citation_info = {
                "title": extract_dict_field(citation, ["title"]),
                "doi": extract_dict_field(citation, ["pdbx_database_id_DOI"]),
                "authors": extract_dict_field(citation, ["rcsb_authors"]),
                "journal": extract_dict_field(citation, ["rcsb_journal_abbrev"]),
                "volume": extract_dict_field(citation, ["journal_volume"]),
                "pages": f"{extract_dict_field(citation, ['page_first'])}-{extract_dict_field(citation, ['page_last'])}",
                "year": extract_dict_field(citation, ["year"]),
            }
            info["citations"].append(citation_info)

        info["macromols"] = []
        polymer_entities = extract_dict_field(
            data, ["data", "entry", "polymer_entities"], []
        )

        for entity in polymer_entities:
            macromol_info = {
                "molecule": extract_dict_field(
                    entity, ["rcsb_polymer_entity", "pdbx_description"]
                ),
                "sequence_length": extract_dict_field(
                    entity, ["entity_poly", "rcsb_sample_sequence_length"]
                ),
                "organism": extract_dict_field(
                    entity,
                    ["rcsb_entity_source_organism", 0, "scientific_name"],
                ),
                "chains": extract_dict_field(
                    entity,
                    [
                        "rcsb_polymer_entity_container_identifiers",
                        "asym_ids",
                    ],
                ),
            }
            info["macromols"].append(macromol_info)

        info["uniprot_id"] = extract_dict_field(
            data,
            [
                "data",
                "entry",
                "polymer_entities",
                0,
                "uniprots",
                0,
                "rcsb_id",
            ],
        )
        info["source_organism_sci_name"] = extract_dict_field(
            data,
            [
                "data",
                "entry",
                "polymer_entities",
                0,
                "uniprots",
                0,
                "rcsb_uniprot_protein",
                "source_organism",
                "scientific_name",
            ],
        )
        info["uniprot_link"] = (
            f"https://www.uniprot.org/uniprotkb/{info['uniprot_id']}/entry"
        )

        info["small_mols"] = []
        nonpolymer_entities = extract_dict_field(
            data, ["data", "entry", "nonpolymer_entities"], []
        )
        for entity in nonpolymer_entities:
            small_mol_info = {
                "mol_id": extract_dict_field(
                    entity, ["nonpolymer_comp", "chem_comp", "id"]
                ),
                "mol_name": extract_dict_field(
                    entity, ["nonpolymer_comp", "chem_comp", "name"]
                ),
                "mol_formula": extract_dict_field(
                    entity, ["nonpolymer_comp", "chem_comp", "formula"]
                ),
                "mol_inchi_key": extract_dict_field(
                    entity,
                    [
                        "nonpolymer_comp",
                        "rcsb_chem_comp_descriptor",
                        "InChIKey",
                    ],
                ),
                "chains": extract_dict_field(
                    entity,
                    [
                        "nonpolymer_entity_instances",
                        0,
                        "rcsb_nonpolymer_entity_instance_container_identifiers",
                        "asym_id",
                    ],
                ),
                "author_identified_chains": extract_dict_field(
                    entity,
                    [
                        "nonpolymer_entity_instances",
                        0,
                        "rcsb_nonpolymer_entity_instance_container_identifiers",
                        "auth_asym_id",
                    ],
                ),
                "binding_affinities": [],
            }
            binding_affinities = extract_dict_field(
                data, ["data", "entry", "rcsb_binding_affinity"], []
            )
            for affinity in binding_affinities:
                affinity_info = {
                    "comp_id": extract_dict_field(affinity, ["comp_id"]),
                    "type": extract_dict_field(affinity, ["type"]),
                    "value": extract_dict_field(affinity, ["value"]),
                    "unit": extract_dict_field(affinity, ["unit"]),
                    "link": extract_dict_field(affinity, ["link"]),
                }
                small_mol_info["binding_affinities"].append(affinity_info)

            info["small_mols"].append(small_mol_info)

        info["assemblies"] = []
        assemblies = extract_dict_field(data, ["data", "entry", "assemblies"], [])
        for assembly in assemblies:
            assembly_info = {
                "symmetry_kind": extract_dict_field(
                    assembly, ["rcsb_struct_symmetry", 0, "kind"]
                ),
                "symmetry_type": extract_dict_field(
                    assembly, ["rcsb_struct_symmetry", 0, "type"]
                ),
                "symmetry_symbol": extract_dict_field(
                    assembly, ["rcsb_struct_symmetry", 0, "symbol"]
                ),
                "oligomeric_state": extract_dict_field(
                    assembly,
                    ["rcsb_struct_symmetry", 0, "oligomeric_state"],
                ),
                "modeled_polymer_monomer_count": extract_dict_field(
                    assembly,
                    ["rcsb_assembly_info", "modeled_polymer_monomer_count"],
                ),
            }
            info["assemblies"].append(assembly_info)

        mol_ids = [mol["mol_id"] for mol in info["small_mols"]]
        with open(f"{assets}/molecule_smiles.gql", "r") as e:
            query_molecule = e.read()

        smiles_payload = {
            "query": query_molecule,
            "variables": {"comp_ids": mol_ids},
        }

        response = requests.post(url, json=smiles_payload)
        if response.status_code == 200:
            smiles_data = response.json()
            for i, small_mol in enumerate(smiles_data["data"]["chem_comps"]):
                info["small_mols"][i]["mol_smiles"] = extract_dict_field(
                    small_mol,
                    [
                        "rcsb_chem_comp_descriptor",
                        "SMILES_stereo",
                    ],
                )

    return info


def generate_html_output(info) -> str:
    """
    Generate an interactive HTML report for protein information.

    Args:
        info (dict): A dictionary containing protein information including:
            - Title, method, resolution
            - R-factors
            - Classification
            - Source organism
            - Sequence information
            - Citations
            - Macromolecules
            - Small molecules
            - Assemblies

    Returns:
        str: HTML iframe code that can be embedded in a webpage to display the protein information report.
    """
    # Including DataTables CSS and JS via CDN
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Protein Information: {info.get("title", "N/A")}</title>
        <style>
            /* Reset some default styles */
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            body {{
                font-family: 'Helvetica Neue', Arial, sans-serif;
                background-color: var(--bg-color, #f4f6f9);
                color: var(--text-color, #000); /* Set default text color to black */
                padding: 20px;
                transition: background-color 0.3s, color 0.3s;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                font-size: 2.5em;
                color: var(--primary-color, #1E90FF);
                margin-bottom: 20px;
                text-align: center;
                word-wrap: break-word;
            }}
            .card {{
                background-color: var(--card-bg, #fff);
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                margin-bottom: 20px;
                padding: 20px;
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            .card:hover {{
                transform: translateY(-5px);
                box-shadow: 0 6px 12px rgba(0,0,0,0.15);
            }}
            .card-header {{
                margin-bottom: 15px;
            }}
            .card-header h2 {{
                font-size: 1.5em;
                color: var(--primary-color, #1E90FF);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 15px;
                table-layout: fixed;
                word-wrap: break-word;
            }}
            th, td {{
                padding: 12px 15px;
                text-align: left;
                border-bottom: 1px solid var(--primary-color, #1E90FF);
                color: var(--text-color, #000); /* Ensure table text is black */
                vertical-align: top;
            }}
            th {{
                background-color: var(--primary-color, #1E90FF);
                color: #fff;
                position: sticky;
                top: 0;
            }}
            tr:hover {{
                background-color: var(--hover-bg, #f1f1f1);
            }}
            .chains-cell {{
                background-color: var(--highlight-bg, #e6f7ff);
                font-weight: bold;
                color: var(--highlight-text, #004080);
                transition: background-color 0.3s;
            }}
            .chains-cell:hover {{
                background-color: var(--highlight-hover, #cceeff);
            }}
            code {{
                white-space: pre-wrap; /* Allow code to wrap */
                word-break: break-all;
            }}
            details {{
                margin-bottom: 20px;
                border: 1px solid var(--primary-color, #1E90FF);
                border-radius: 5px;
                overflow: hidden;
                background-color: var(--collapsible-bg, #f9f9f9);
                transition: background-color 0.3s, border-color 0.3s;
            }}
            summary {{
                padding: 15px;
                font-size: 1.2em;
                font-weight: bold;
                cursor: pointer;
                color: var(--primary-color, #1E90FF);
                list-style: none;
                outline: none;
            }}
            details[open] summary {{
                border-bottom: 1px solid var(--primary-color, #1E90FF);
            }}
            details ul {{
                padding: 15px;
                list-style-type: disc;
                padding-left: 40px;
                color: var(--text-color, #000); /* Ensure list text is black */
            }}
            details li {{
                margin-bottom: 10px;
            }}
            details a {{
                color: var(--primary-color, #1E90FF);
                text-decoration: none;
            }}
            details a:hover {{
                text-decoration: underline;
            }}
            /* Responsive Design */
            @media (max-width: 768px) {{
                table {{
                    font-size: 0.9em;
                }}
                h1 {{
                    font-size: 2em;
                }}
            }}
            /* Dark Theme Variables */
            body.dark {{
                --bg-color: #2E2E2E;
                --text-color: #f1f1f1; /* Light text in dark mode */
                --card-bg: #3E3E3E;
                --primary-color: #1E90FF;
                --hover-bg: #444444;
                --highlight-bg: #555555;
                --highlight-text: #ffffff;
                --highlight-hover: #666666;
                --collapsible-bg: #3E3E3E;
            }}
            /* Ensure DataTables buttons are visible */
            .dt-buttons {{
                margin-bottom: 10px;
            }}
        </style>
        
        <!-- DataTables CSS -->
        <link rel="stylesheet" href="https://cdn.datatables.net/1.13.4/css/jquery.dataTables.min.css">
        <link rel="stylesheet" href="https://cdn.datatables.net/buttons/2.3.6/css/buttons.dataTables.min.css">
        
        <!-- jQuery -->
        <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
        <!-- DataTables JS -->
        <script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>
        <script src="https://cdn.datatables.net/buttons/2.3.6/js/dataTables.buttons.min.js"></script>
        <script src="https://cdn.datatables.net/buttons/2.3.6/js/buttons.html5.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
        
        <script>
            $(document).ready(function() {{
                // Function to initialize DataTables for a given table ID
                function initializeDataTable(tableId) {{
                    if (!$(tableId).hasClass('dt-initialized')) {{
                        $(tableId).DataTable({{
                            dom: 'Bfrtip',
                            buttons: [
                                'copy', 'csv'
                            ]
                        }});
                        $(tableId).addClass('dt-initialized');
                    }}
                }}
                
                // Initialize DataTables when a <details> section is opened
                $('details').on('toggle', function() {{
                    if (this.open) {{
                        var summaryText = $(this).children('summary').text().trim();
                        switch(summaryText) {{
                            case 'Key Attributes':
                                initializeDataTable('#attributes-table');
                                break;
                            case 'Citations':
                                // No table to initialize
                                break;
                            case 'Macromolecules':
                                initializeDataTable('#macromols-table');
                                break;
                            case 'Small Molecules':
                                initializeDataTable('#small_mols-table');
                                break;
                            case 'Assemblies':
                                initializeDataTable('#assemblies-table');
                                break;
                            default:
                                break;
                        }}
                    }}
                }});
            }});
        
        </script>
    </head>
    <body>
        <div class="container">
            <h1>Protein Information: {info.get("title", "N/A")}</h1>
    
            <!-- Collapsible Key Attributes Section -->
            <details>
                <summary>Key Attributes</summary>
                <div class="card">
                    <div class="card-header">
                        <h2>Key Attributes</h2>
                    </div>
                    <table id="attributes-table" class="display">
                      <thead>
                          <tr>
                            <th>Attribute</th>
                            <th>Value</th>
                          </tr>
                      </thead>
                      <tbody>
                          <tr>
                            <td>UniProt ID</td>
                            <td>{info.get("uniprot_id", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Method</td>
                            <td>{info.get("method", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Resolution</td>
                            <td>{info.get("resolution", "N/A")} Å</td>
                          </tr>
                          <tr>
                            <td>R-factor Work</td>
                            <td>{info.get("r_factor_work", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>R-factor Free</td>
                            <td>{info.get("r_factor_free", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Classification</td>
                            <td>{info.get("classification", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Source Organism</td>
                            <td>{info.get("source_organism", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Number of Mutations</td>
                            <td>{info.get("n_mutations", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Sequence Length</td>
                            <td>{info.get("sequence_length", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Canonical Sequence</td>
                            <td><code>{info.get("canonical_sequence", "N/A")}</code></td>
                          </tr>
                          <tr>
                            <td>PubMed Abstract</td>
                            <td>{info.get("pubmed_abstract", "N/A")}</td>
                          </tr>
                          <tr>
                            <td>Uniprot Link</td>
                            <td><a href="{info.get("uniprot_link", "#")}" target="_blank">{info.get("uniprot_link", "N/A")}</a></td>
                          </tr>
                      </tbody>
                    </table>
                </div>
            </details>
    
            <!-- Collapsible Citations Section -->
            <details>
                <summary>Citations</summary>
                <div class="card">
                    <div class="card-header">
                        <h2>Citations</h2>
                    </div>
        """
    # Add citations to HTML
    citations = info.get("citations", [])
    if citations:
        html_content += """
                    <ul>
        """
        for citation in citations:
            doi = citation.get("doi", "N/A")
            doi_link = f"https://doi.org/{doi}" if doi != "N/A" else "#"
            authors = ", ".join(citation.get("authors", []))
            html_content += f"""
                        <li>
                            <strong>{citation.get("title", "N/A")}</strong><br/>
                            DOI: <a href="{doi_link}" target="_blank">{doi}</a><br/>
                            Authors: {authors}<br/>
                            Journal: {citation.get("journal", "N/A")} {citation.get("volume", "N/A")} Pages: {citation.get("pages", "N/A")}<br/>
                            Year: {citation.get("year", "N/A")}
                        </li>
            """
        html_content += """
                    </ul>
        """
    else:
        html_content += """
                    <p>No citations available.</p>
        """
    html_content += """
                </div>
            </details>
    
            <!-- Collapsible Macromolecules Section -->
            <details>
                <summary>Macromolecules</summary>
                <div class="card">
                    <div class="card-header">
                        <h2>Macromolecules</h2>
                    </div>
        """
    macromols = info.get("macromols", [])
    if macromols:
        html_content += """
                        <table id="macromols-table" class="display">
                          <thead>
                              <tr>
                                <th>Molecule</th>
                                <th>Sequence Length</th>
                                <th>Organism</th>
                                <th>Chains</th>
                              </tr>
                          </thead>
                          <tbody>
        """
        for macromol in macromols:
            chains = macromol.get("chains", "N/A")
            if isinstance(chains, list):
                chains = ", ".join(chains)
            html_content += f"""
                              <tr>
                                  <td>{macromol.get("molecule", "N/A")}</td>
                                  <td>{macromol.get("sequence_length", "N/A")}</td>
                                  <td>{macromol.get("organism", "N/A")}</td>
                                  <td class="chains-cell">{chains}</td>
                              </tr>
            """
        html_content += """
                          </tbody>
                        </table>
        """
    else:
        html_content += """
                        <p>No macromolecules data available.</p>
        """
    html_content += """
                </div>
            </details>
        """

    # Collapsible Small Molecules Section
    small_mols = info.get("small_mols", [])
    html_content += """
            <details>
                <summary>Small Molecules</summary>
                <div class="card">
                    <div class="card-header">
                        <h2>Small Molecules</h2>
                    </div>
    """
    if small_mols:
        html_content += """
                        <table id="small_mols-table" class="display">
                          <thead>
                              <tr>
                                <th>Molecule ID</th>
                                <th>Name</th>
                                <th>Formula</th>
                                <th>InChI Key</th>
                                <th>Chains</th>
                                <th>Author Identified Chains</th>
                                <th>Binding Affinities</th>
                                <th>SMILES</th>
                              </tr>
                          </thead>
                          <tbody>
        """
        for small_mol in small_mols:
            binding_affinities = small_mol.get("binding_affinities", [])
            if binding_affinities:
                affinities = "<ul>"
                for affinity in binding_affinities:
                    aff_type = affinity.get("type", "N/A")
                    value = affinity.get("value", "N/A")
                    unit = affinity.get("unit", "")
                    link = affinity.get("link", "#")
                    affinities += f"<li>{aff_type}: {value} {unit} (<a href='{link}' target='_blank'>Link</a>)</li>"
                affinities += "</ul>"
            else:
                affinities = "N/A"
            html_content += f"""
                          <tr>
                              <td>{small_mol.get("mol_id", "N/A")}</td>
                              <td>{small_mol.get("mol_name", "N/A")}</td>
                              <td>{small_mol.get("mol_formula", "N/A")}</td>
                              <td><code>{small_mol.get("mol_inchi_key", "N/A")}</code></td>
                              <td>{small_mol.get("chains", "N/A")}</td>
                              <td>{small_mol.get("author_identified_chains", "N/A")}</td>
                              <td>{affinities}</td>
                              <td><code>{small_mol.get("mol_smiles", "N/A")}</code></td>
                          </tr>
            """
        html_content += """
                          </tbody>
                        </table>
        """
    else:
        html_content += """
                        <p>No small molecules data available.</p>
        """
    html_content += """
                </div>
            </details>
    """

    # Collapsible Assemblies Section
    assemblies = info.get("assemblies", [])
    html_content += """
            <details>
                <summary>Assemblies</summary>
                <div class="card">
                    <div class="card-header">
                        <h2>Assemblies</h2>
                    </div>
    """
    if assemblies:
        html_content += """
                        <table id="assemblies-table" class="display">
                          <thead>
                              <tr>
                                <th>Symmetry Kind</th>
                                <th>Symmetry Type</th>
                                <th>Symmetry Symbol</th>
                                <th>Oligomeric State</th>
                                <th>Modeled Polymer Monomer Count</th>
                              </tr>
                          </thead>
                          <tbody>
        """
        for assembly in assemblies:
            html_content += f"""
                          <tr>
                              <td>{assembly.get("symmetry_kind", "N/A")}</td>
                              <td>{assembly.get("symmetry_type", "N/A")}</td>
                              <td>{assembly.get("symmetry_symbol", "N/A")}</td>
                              <td>{assembly.get("oligomeric_state", "N/A")}</td>
                              <td>{assembly.get("modeled_polymer_monomer_count", "N/A")}</td>
                          </tr>
            """
        html_content += """
                          </tbody>
                        </table>
        """
    else:
        html_content += """
                        <p>No assemblies data available.</p>
        """
    html_content += """
                </div>
            </details>
        </div>
    </body>
    </html>
    """

    return html_content
