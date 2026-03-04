"""
Backward-compatibility re-exports for drug_discovery utilities.

Functions have been moved to focused modules:
  - geometry:    calculate_box_min_max, calculate_box_dimensions
  - files:       move_file_with_extension, remove_file
  - collections: chunker
"""

from deeporigin.drug_discovery.utilities.collections import chunker
from deeporigin.drug_discovery.utilities.files import (
    move_file_with_extension,
    remove_file,
)
from deeporigin.drug_discovery.utilities.geometry import (
    calculate_box_dimensions,
    calculate_box_min_max,
)

DEFAULT_MAX_DEPTH = 2

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "move_file_with_extension",
    "remove_file",
    "chunker",
    "calculate_box_min_max",
    "calculate_box_dimensions",
]
