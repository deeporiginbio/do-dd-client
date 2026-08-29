# merge-ready lessons

Notes from past merge-ready cycles. Read before starting; append after success.

## 2026-08-28 — PR #616 — metabolism async execution

CI failed on a real bug from this PR's own protein-stamping commit: `Protein.sync(lazy=True)` had grown a `self.remote_path is not None` short-circuit alongside the `id is not None` one, so `SystemPrep.sync_inputs()` got a protein with `id=None` after a lazy sync and raised — `lazy` must only skip when `id` is already known; skip-upload-when-remote_path-set is a separate, already-handled concern. Also caught: a new doc snippet with a placeholder path (`path/to/ligands.csv`) used a plain ` ```python ` fence instead of the repo's ` ```{.python notest} ` convention for non-runnable examples, so `pytest-markdown-docs` executed and failed it — grep sibling docs for the convention before adding a new placeholder-path snippet. And: a SonarCloud `# NOSONAR` suppression silently didn't take because ruff reformatted the flagged call across multiple lines, moving the comment off the line Sonar's annotation targets — keep NOSONAR'd calls on one line, or verify the annotation's exact line after formatting. Copilot caught a real safety bug: `Metabolism._start_impl` discarded `approve_amount` instead of forwarding it, so `start(quote=True)` would silently run the real execution instead of quoting — align `_make_payload`/`_start_impl` signatures with the `Execution` base contract (`*, approve_amount, sync`) even for tools with no billing path, and fail fast rather than silently ignore. `level-1-tests (3.13, prod)` fails on a known, non-required, pre-existing Pocket Finder platform-registration issue unrelated to any of these changes — do not chase it.

## 2026-08-27 — PR #615 — metabolism tool (DDOS-7477)

Copilot caught a real invariant break, a docs bug, and scope creep: `_ensure_enzymes_for_run` unconditionally rebuilt `self._enzymes` as a `list`, so a re-run on an already-executed instance (enzymes frozen to a `tuple`) would silently unfreeze it if `_create_execution` raised before `update_from_dto` re-froze it — preserve the input's tuple/list-ness through validation, same class of bug as `admet.py`'s `_ensure_properties_for_run`, which has the identical unguarded pattern and should get the same fix if touched again. Also: `constants.py` diffs in these PRs are easy to eyeball-check for drive-by edits — this PR accidentally bumped `pocket_finder`'s pinned `tool_version` from `"1"` to `"latest"` while only meaning to add the `metabolism` entry.

## 2026-08-24 — PR #611 — notebook cleanup / Pocket.show

Copilot found two real gaps in the new `Pocket.show()` delegation: a `from_dto`-rehydrated parent (`Protein.from_id(..., download=False)`) has `structure=None` so `Protein.show()` → `_dump_state()` raises, and `from_residue_number()` pockets have neither `local_path` nor `remote_path` so the delegated `pocket.download()` raises — hydrate the parent and materialize coordinates with `to_file()` before delegating, threading the pocket's `_client` through both. Level-1 CI failed on dev/staging/prod because `_resolve_parent_protein` re-raised the platform `DeepOriginException` verbatim ("Invalid id format"), which never mentions the protein: wrap platform errors with parent-protein context while keeping the original detail, and note that Copilot reads *this* file and will cite stale entries as an authoritative contract, so mark superseded lines explicitly.

## 2026-08-19 — PR #603 — FEP Pose kwargs (DDOS-6738)

Ubuntu notebook CI failed on `protein.show(poses=poses)` until the bulk-docking demo used `filter_top_poses()`; mock bulk-docking rows must point at per-ligand SDFs (not shared `128poses.sdf`) so pose rehydrate works headless. Sonar blocked on RBFE `from_dto` pose-pair coverage and a redundant `SystemPrep` RBFE guard (S2583/S2589) — add rehydrate tests early and drop guards already enforced by mode flags.

## 2026-08-19 — PR #607 — docking box rotation from pocket

Copilot caught three real geometry edge cases on pocket-finder nested `box`: interactive commits must sync nested OBB sizes, identity rotation `[0,0,0]` must not normalize to `None` (or inferred rotation wins), and constrained docking must use parent AABB sizes when omitting `rotation_deg`. Committed viewer sizes are OBB-local — derive parent lab-frame AABB from the OBB only when `pocket.box` exists; legacy pockets keep OBB on parent for free docking with rotation. (Superseded by PR #611 / DDOS-7441: `rotation_deg` is now lab→working, so the extents formula is `abs(Rᵀ) @ obb`; the composed result for viewer-committed boxes is unchanged.)

## 2026-08-19 — PR #606 — interactive box geometry sync

Pre-commit `nb-clean` promotion can inject `protein.sync()` into notebook setup cells; verify clean notebooks after commit when claiming “no platform sync until run”. Copilot catches this reliably — resolve before re-review.

## 2026-08-14 — PR #604 — ProteinPrep async wrapper

Copilot asked `ProteinPrep` to reject `start(quote=True)`; that was an explicit inherit-silent mixin decision — reply and resolve rather than special-casing `start()`. `gh pr checks --json` fields are `name,state,bucket` (`conclusion` is invalid and silently yields empty output).

## 2026-08-13 — PR #602 — DDOS-6737 docking PoseSet

Sonar new-code coverage needed explicit unit tests for `PoseSet.download`/`Protein.show(poses=...)` helpers beyond the complexity split — aim past 80% early. Branch protection only requires Ubuntu functionality + formatting; Windows `test_import_config_does_not_create_deeporigin_dir` and staging ADMET `FailedQuotation` are non-required flakes — do not block Copilot on them.
