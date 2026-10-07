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

**Pose origin** known values include `cocrystal`, `docked`, `registered`, and
`manual`. Older indexed rows may still store `crystal_extract`; the client
reads that as `cocrystal`. Unknown origin strings are preserved for forward
compatibility.

Use :class:`Pose` / :class:`PoseSet` when you need pose-scoped identity.
:meth:`~deeporigin.drug_discovery.Docking.get_results` and
:meth:`~deeporigin.drug_discovery.Docking.get_poses` return :class:`PoseSet`.
You can also load poses with :meth:`PoseSet.from_result` or
:meth:`~deeporigin.drug_discovery.Ligand.get_poses`.

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

### Computing pairwise pose RMSD

Use :meth:`PoseSet.compute_rmsd` for an ``n x n`` matrix of pose-to-pose RMSD
values (Å). The calculation is **symmetry-corrected** (equivalent symmetric
atom mappings are minimized) and **in place**: coordinates are not aligned or
centered, so RMSD reflects actual positional deviation in the stored poses.

Each pose must have a local 3D structure loaded. For remote-only poses, call
:meth:`PoseSet.download` before :meth:`PoseSet.compute_rmsd`.

```{.python notest}
from deeporigin.drug_discovery import PoseSet

pose_set = PoseSet.from_sdf("docking_results.sdf")
rmsd_matrix = pose_set.compute_rmsd()
```

!!! note "Returns New Data"
    ``compute_rmsd()`` returns a NumPy array and does not mutate the
    :class:`PoseSet` or its poses.
