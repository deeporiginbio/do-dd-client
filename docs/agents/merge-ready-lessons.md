# merge-ready lessons

Notes from past merge-ready cycles. Read before starting; append after success.

## 2026-08-14 — PR #604 — ProteinPrep async wrapper

Copilot asked `ProteinPrep` to reject `start(quote=True)`; that was an explicit inherit-silent mixin decision — reply and resolve rather than special-casing `start()`. `gh pr checks --json` fields are `name,state,bucket` (`conclusion` is invalid and silently yields empty output).

## 2026-08-13 — PR #602 — DDOS-6737 docking PoseSet

Sonar new-code coverage needed explicit unit tests for `PoseSet.download`/`Protein.show(poses=...)` helpers beyond the complexity split — aim past 80% early. Branch protection only requires Ubuntu functionality + formatting; Windows `test_import_config_does_not_create_deeporigin_dir` and staging ADMET `FailedQuotation` are non-required flakes — do not block Copilot on them.
