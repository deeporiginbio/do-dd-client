"""Tests for job visualization functions."""

import json

from deeporigin.tools.job_viz_functions import _viz_func_abfe


class MockJob:
    """Mock job object for testing visualization functions."""

    def __init__(self, progress_report: str | None = None, status: str | None = None):
        """Initialize mock job with optional progress report and status."""
        self._progress_report = progress_report
        self._status = status


def test_viz_func_abfe_fep_results():
    """Test that FEP Results shows success message and delta G."""
    progress_data = {
        "cmd": "FEP Results",
        "Solvation": 77.787,
        "Binding": 99.238,
        "AnalyticalCorr": -11.465,
        "Std": 0.0,
        "Total": -9.986,
        "unit": "kcal/mol",
    }
    job = MockJob(progress_report=json.dumps(progress_data))
    result = _viz_func_abfe(job)

    assert "Job completed successfully" in result
    assert "delta G = -9.986 kcal/mol" in result
    assert "✓" in result


def test_viz_func_abfe_fep_results_no_unit():
    """Test that FEP Results works when unit is missing (uses default)."""
    progress_data = {
        "cmd": "FEP Results",
        "Total": 5.5,
    }
    job = MockJob(progress_report=json.dumps(progress_data))
    result = _viz_func_abfe(job)

    assert "Job completed successfully" in result
    assert "delta G = 5.5 kcal/mol" in result


def test_viz_func_abfe_fep_results_no_total():
    """Test that FEP Results works when Total is missing (shows N/A)."""
    progress_data = {
        "cmd": "FEP Results",
        "unit": "kcal/mol",
    }
    job = MockJob(progress_report=json.dumps(progress_data))
    result = _viz_func_abfe(job)

    assert "Job completed successfully" in result
    assert "delta G = N/A kcal/mol" in result


def test_viz_func_abfe_solvation_fep():
    """Test that Solvation FEP shows normal progress (not success)."""
    progress_data = {
        "cmd": "Solvation FEP",
        "sub_step": "Running simulation",
        "current_avg_step": 5.0,
        "target_step": 10.0,
    }
    job = MockJob(progress_report=json.dumps(progress_data))
    result = _viz_func_abfe(job)

    assert "Job completed successfully" not in result
    assert "Solvation FEP" in result
    assert "Initializing" in result


def test_viz_func_abfe_binding_fep():
    """Test that Binding FEP shows normal progress (not success)."""
    progress_data = {
        "cmd": "Binding FEP",
        "sub_step": "Running simulation",
        "current_avg_step": 3.0,
        "target_step": 8.0,
    }
    job = MockJob(progress_report=json.dumps(progress_data))
    result = _viz_func_abfe(job)

    assert "Job completed successfully" not in result
    assert "Binding FEP" in result
    assert "Initializing" in result


def test_viz_func_abfe_no_progress_report():
    """Test that function works when progress report is None."""
    job = MockJob(progress_report=None)
    result = _viz_func_abfe(job)

    assert "Initializing" in result
    assert "Job completed successfully" not in result


def test_viz_func_abfe_invalid_json():
    """Test that function handles invalid JSON gracefully."""
    job = MockJob(progress_report="invalid json")
    result = _viz_func_abfe(job)

    assert "Initializing" in result
    assert "Job completed successfully" not in result
