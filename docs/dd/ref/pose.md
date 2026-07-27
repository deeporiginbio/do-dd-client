# `deeporigin.drug_discovery.Pose` / `PoseSet`

::: src.drug_discovery.structures.pose.Pose
    options:
      docstring_style: google
      show_root_heading: false
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true

::: src.drug_discovery.structures.pose.PoseSet
    options:
      docstring_style: google
      show_root_heading: false
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true

## Overview

A **Pose** is a 3D ligand conformation stored in the platform pose result table
(`result_type=pose`). It has its own platform **pose id** (`Pose.id`) and a
parent **ligand id** (`Pose.ligand_id`) in the ligands table.

Use :class:`Pose` / :class:`PoseSet` when you need pose-scoped identity. Docking
outputs still return :class:`~deeporigin.drug_discovery.LigandSet` from
:meth:`~deeporigin.drug_discovery.Docking.get_poses` until a later release; prefer
:meth:`PoseSet.from_result` or :meth:`~deeporigin.drug_discovery.Ligand.get_poses`
for new code.

### Register an external SDF

```{.python notest}
from deeporigin.drug_discovery import Pose

pose = Pose.from_sdf("cocrystal.sdf", protein_id=protein.id)
print(pose.id, pose.ligand_id)
```

### List poses for a ligand

```{.python notest}
ligand.sync()
poses = ligand.get_poses()
for pose in poses:
    print(pose.id, pose.pose_score)
```

### Load poses from a docking run

```{.python notest}
from deeporigin.drug_discovery import PoseSet

pose_set = PoseSet.from_result(execution_id=docking.id)
```
