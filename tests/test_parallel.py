"""
Tests for the parallel execution utilities.
"""

import time

from deeporigin.drug_discovery.parallel import run_func_in_parallel


def test_simple_function_parallelization():
    """Test basic parallel execution with a simple function."""

    def add_numbers(x, y):
        return x + y

    args_list = [
        {"x": 1, "y": 10},
        {"x": 2, "y": 20},
        {"x": 3, "y": 30},
        {"x": 4, "y": 40},
        {"x": 5, "y": 50},
    ]

    results = run_func_in_parallel(
        func=add_numbers,
        batch_size=3,
        max_retries=1,
        args=args_list,
    )

    assert results["results"] == [11, 22, 33, 44, 55]
    assert results["total_failures"] == 0
    assert results["permanent_failures"] == []
    assert results["elapsed_time"] > 0
    assert all(duration is not None for duration in results["durations"])


def test_function_with_scalar_and_list_arguments():
    """Test parallel execution with mixed scalar and list arguments."""

    def multiply_with_offset(x, y, offset=1):
        return x * y + offset

    args_list = [
        {"x": 2, "y": 5, "offset": 10},
        {"x": 3, "y": 6, "offset": 10},
        {"x": 4, "y": 7, "offset": 10},
    ]

    results = run_func_in_parallel(
        func=multiply_with_offset,
        batch_size=2,
        max_retries=1,
        args=args_list,
    )

    assert results["results"] == [20, 28, 38]  # (2*5+10), (3*6+10), (4*7+10)
    assert results["total_failures"] == 0
    assert results["permanent_failures"] == []


def test_function_with_retries():
    """Test parallel execution with retries for failed calls."""

    call_count = {}

    def sometimes_failing_func(x, attempt=0):
        call_count[x] = call_count.get(x, 0) + 1

        # Fail on first attempt for x=2, succeed on second
        if x == 2 and call_count[x] == 1:
            raise ValueError("Temporary failure")
        return x * 10

    args_list = [
        {"x": 1, "attempt": 0},
        {"x": 2, "attempt": 0},
        {"x": 3, "attempt": 0},
    ]

    results = run_func_in_parallel(
        func=sometimes_failing_func, batch_size=2, max_retries=2, args=args_list
    )

    assert results["results"] == [10, 20, 30]
    assert results["total_failures"] == 1  # One failure that was retried
    assert results["permanent_failures"] == []
    assert call_count[2] == 2  # x=2 was called twice (failed once, succeeded once)


def test_function_with_permanent_failures():
    """Test parallel execution where some calls permanently fail."""

    def always_failing_func(x):
        if x == 2:
            raise ValueError("Permanent failure")
        return x * 10

    args_list = [
        {"x": 1},
        {"x": 2},
        {"x": 3},
    ]

    results = run_func_in_parallel(
        func=always_failing_func, batch_size=2, max_retries=1, args=args_list
    )

    assert results["results"] == [10, None, 30]
    assert results["total_failures"] == 1  # One failure (one retry attempt)
    assert results["permanent_failures"] == [1]  # Index 1 (x=2) permanently failed
    assert results["durations"][1] is None  # Duration is None for failed call


def test_empty_input():
    """Test parallel execution with empty input."""

    def dummy_func(x):
        return x

    results = run_func_in_parallel(
        func=dummy_func, batch_size=5, max_retries=1, args=[]
    )

    assert results["results"] == []
    assert results["total_failures"] == 0
    assert results["permanent_failures"] == []
    assert results["elapsed_time"] >= 0


def test_single_item_input():
    """Test parallel execution with single item input."""

    def square_func(x):
        return x * x

    results = run_func_in_parallel(
        func=square_func, batch_size=5, max_retries=1, args=[{"x": 5}]
    )

    assert results["results"] == [25]
    assert results["total_failures"] == 0
    assert results["permanent_failures"] == []


def test_batch_size_effect():
    """Test that batch size affects execution timing."""

    def slow_func(x):
        time.sleep(0.01)  # Small delay
        return x * 2

    args_list = [{"x": i} for i in range(10)]

    # Test with small batch size
    results_small = run_func_in_parallel(
        func=slow_func, batch_size=2, max_retries=1, args=args_list
    )

    # Test with larger batch size
    results_large = run_func_in_parallel(
        func=slow_func, batch_size=10, max_retries=1, args=args_list
    )

    # Both should produce same results
    assert results_small["results"] == results_large["results"]
    assert results_small["results"] == [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]


def test_sleep_between_batches():
    """Test that sleep between batches is respected."""

    def fast_func(x):
        return x

    args_list = [{"x": i} for i in range(6)]  # 3 batches of 2

    start_time = time.monotonic()
    results = run_func_in_parallel(
        func=fast_func,
        batch_size=2,
        max_retries=1,
        sleep_between_batches=0.1,
        args=args_list,
    )
    elapsed_time = time.monotonic() - start_time

    # Should take at least 0.2 seconds (2 sleeps between 3 batches)
    assert elapsed_time >= 0.19
    assert results["results"] == [0, 1, 2, 3, 4, 5]


def test_function_with_complex_return_types():
    """Test parallel execution with functions returning complex types."""

    def create_dict(x, prefix="item"):
        return {"id": x, "name": f"{prefix}_{x}", "value": x * 10}

    args_list = [
        {"x": 1, "prefix": "test"},
        {"x": 2, "prefix": "test"},
        {"x": 3, "prefix": "test"},
    ]

    results = run_func_in_parallel(
        func=create_dict, batch_size=3, max_retries=1, args=args_list
    )

    expected = [
        {"id": 1, "name": "test_1", "value": 10},
        {"id": 2, "name": "test_2", "value": 20},
        {"id": 3, "name": "test_3", "value": 30},
    ]

    assert results["results"] == expected
    assert results["total_failures"] == 0


def test_function_with_different_argument_sets():
    """Test parallel execution where different calls have different arguments."""

    def flexible_func(**kwargs):
        if "x" in kwargs and "y" in kwargs:
            return kwargs["x"] + kwargs["y"]
        elif "x" in kwargs:
            return kwargs["x"] * 2
        else:
            return 42

    args_list = [
        {"x": 1, "y": 2},  # x + y = 3
        {"x": 5},  # x * 2 = 10
        {},  # default = 42
        {"x": 3, "y": 7},  # x + y = 10
    ]

    results = run_func_in_parallel(
        func=flexible_func,
        batch_size=2,
        max_retries=1,
        args=args_list,
    )

    assert results["results"] == [3, 10, 42, 10]
    assert results["total_failures"] == 0
