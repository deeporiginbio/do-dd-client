# merge-ready lessons

Notes from past merge-ready cycles. Read before starting; append after success.

## 2026-08-19 — PR #603 — FEP Pose kwargs (DDOS-6738)

Ubuntu notebook CI failed on `protein.show(poses=poses)` until the bulk-docking demo used `filter_top_poses()`; mock bulk-docking rows must point at per-ligand SDFs (not shared `128poses.sdf`) so pose rehydrate works headless. Sonar blocked on RBFE `from_dto` pose-pair coverage and a redundant `SystemPrep` RBFE guard (S2583/S2589) — add rehydrate tests early and drop guards already enforced by mode flags.

## 2026-08-19 — PR #607 — docking box rotation from pocket

Copilot caught three real geometry edge cases on pocket-finder nested `box`: interactive commits must sync nested OBB sizes, identity rotation `[0,0,0]` must not normalize to `None` (or inferred rotation wins), and constrained docking must use parent AABB sizes when omitting `rotation_deg`. Committed viewer sizes are OBB-local — derive parent lab-frame AABB via `abs(Rz·Ry·Rx) @ obb` only when `pocket.box` exists; legacy pockets keep OBB on parent for free docking with rotation.

## 2026-08-19 — PR #606 — interactive box geometry sync

Pre-commit `nb-clean` promotion can inject `protein.sync()` into notebook setup cells; verify clean notebooks after commit when claiming “no platform sync until run”. Copilot catches this reliably — resolve before re-review.

## 2026-08-14 — PR #604 — ProteinPrep async wrapper

Copilot asked `ProteinPrep` to reject `start(quote=True)`; that was an explicit inherit-silent mixin decision — reply and resolve rather than special-casing `start()`. `gh pr checks --json` fields are `name,state,bucket` (`conclusion` is invalid and silently yields empty output).

## 2026-08-13 — PR #602 — DDOS-6737 docking PoseSet

Sonar new-code coverage needed explicit unit tests for `PoseSet.download`/`Protein.show(poses=...)` helpers beyond the complexity split — aim past 80% early. Branch protection only requires Ubuntu functionality + formatting; Windows `test_import_config_does_not_create_deeporigin_dir` and staging ADMET `FailedQuotation` are non-required flakes — do not block Copilot on them.
