"""
Parallel execution utilities for running functions in parallel batches with retries.

Provides :func:`run_func_in_parallel` (thread pool) for batching and retries.
"""

from collections.abc import Callable
import concurrent.futures
import time
from typing import Any, Optional

from beartype import beartype


@beartype
def run_func_in_parallel(
    *,
    func: Callable,
    batch_size: int = 10,
    max_retries: int = 3,
    sleep_between_batches: float = 0.1,
    args: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run a function in parallel batches with retries for failures.

    Args:
        func: Callable invoked as ``func(**kwargs)`` for each ``args`` entry.
        batch_size: Parallel batch size.
        max_retries: Retries per index on failure.
        sleep_between_batches: Delay between batches in seconds.
        args: List of keyword-argument dicts.

    Returns:
        Dict with ``results``, ``total_failures``, ``permanent_failures``,
        ``elapsed_time``, and ``durations``.
    """
    if not args:
        return {
            "results": [],
            "total_failures": 0,
            "permanent_failures": [],
            "elapsed_time": 0,
            "durations": [],
        }

    total = len(args)
    results: list[Any] = [None] * total
    retries_left = [max_retries] * total
    total_failures = 0
    durations: list[float | None] = [None] * total

    def call_func_timed(idx: int) -> Optional[tuple]:
        nonlocal total_failures
        try:
            start = time.time()
            result = func(**args[idx])
            end = time.time()
            return (idx, result, end - start)
        except Exception as e:
            print(f"[Error] Call {idx} failed: {e}")
            total_failures += 1
            return (idx, None, None)

    start_time = time.time()

    def process_batch(batch_indices: list[int]) -> None:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            batch_results = list(executor.map(call_func_timed, batch_indices))

        for idx, result, duration in batch_results:
            if result is not None:
                results[idx] = result
                durations[idx] = duration
            else:
                retries_left[idx] -= 1

    while any(
        (result is None and retries > 0)
        for result, retries in zip(results, retries_left, strict=True)
    ):
        to_process = [
            i
            for i, (result, retries) in enumerate(
                zip(results, retries_left, strict=True)
            )
            if result is None and retries > 0
        ]

        for i in range(0, len(to_process), batch_size):
            batch = to_process[i : i + batch_size]
            process_batch(batch)
            time.sleep(sleep_between_batches)

    elapsed_time = time.time() - start_time
    permanent_failures = [i for i, result in enumerate(results) if result is None]

    return {
        "results": results,
        "total_failures": total_failures,
        "permanent_failures": permanent_failures,
        "elapsed_time": elapsed_time,
        "durations": durations,
    }
