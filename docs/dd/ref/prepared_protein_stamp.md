# Prepared Protein stamp

Helpers that detect and preserve the file-borne Prepared Protein stamp
(`REMARK  99 DO_PREPARED`) on PDB files.

Protein Prep writes this stamp onto the prepared PDB before upload. Downstream
tools (Pocket Finder, Docking, System Prep) skip automatic protein cleanup when
the stamp is present. The CLI must not drop it when rewriting or syncing a
protein that already points at a stamped remote file.

::: src.drug_discovery.structures.prepared_protein_stamp
    options:
      docstring_style: google
      show_root_heading: false
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      members_order: alphabetical
      filters:
        - "!^_"
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true
