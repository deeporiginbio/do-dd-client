"""
Collection utility functions for drug discovery workflows.

Provides helpers for working with iterables and sequences.
"""

from itertools import islice


def chunker(iterable, size):
    """
    Split an iterable into chunks of specified size.

    Args:
        iterable: Any iterable object
        size (int): Size of each chunk

    Yields:
        list: Chunks of the input iterable, each containing up to 'size' elements
    """
    iterator = iter(iterable)
    for first in iterator:
        yield [first] + list(islice(iterator, size - 1))
