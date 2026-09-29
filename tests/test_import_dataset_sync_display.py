"""Tests for import-dataset sync step progress HTML."""

from deeporigin.drug_discovery.import_dataset_sync_display import (
    POSE_REGISTRATION_STEPS,
    NullImportDatasetSyncProgress,
    import_dataset_sync_progress_for_pose_registration,
    render_import_dataset_sync_progress_html,
)


def test_render_import_dataset_sync_progress_html_compact() -> None:
    html = render_import_dataset_sync_progress_html(
        completed=2,
        total=len(POSE_REGISTRATION_STEPS),
        status_label=POSE_REGISTRATION_STEPS[2],
        detail="import-dataset",
    )
    assert "progress-bar" in html
    assert "Run import-dataset" in html
    assert "import-dataset" in html
    assert "list-group" not in html
    assert "exec-123" not in html
    assert "spinner-border" in html


def test_render_import_dataset_sync_progress_html_done() -> None:
    html = render_import_dataset_sync_progress_html(
        completed=5,
        total=5,
        status_label="ignored",
    )
    assert "Done" in html
    assert "bg-success" in html


def test_null_progress_reporter_is_no_op() -> None:
    reporter = NullImportDatasetSyncProgress()
    reporter.start_step(0)
    reporter.finish_step(0)
    reporter.set_execution_id("x")
    reporter.fail_step(0, message="nope")
    reporter.close()


def test_progress_disabled_when_show_progress_false() -> None:
    reporter = import_dataset_sync_progress_for_pose_registration(show_progress=False)
    assert isinstance(reporter, NullImportDatasetSyncProgress)


def test_ligand_workflow_progress_uses_six_steps() -> None:
    from deeporigin.drug_discovery.import_dataset_sync_display import (
        LIGAND_WORKFLOW_SYNC_STEPS,
        import_dataset_sync_progress_for_ligand,
    )

    reporter = import_dataset_sync_progress_for_ligand(
        show_progress=False,
        workflow=True,
    )
    assert isinstance(reporter, NullImportDatasetSyncProgress)
    assert len(LIGAND_WORKFLOW_SYNC_STEPS) == 6
    assert "Wait for workflow" in LIGAND_WORKFLOW_SYNC_STEPS
