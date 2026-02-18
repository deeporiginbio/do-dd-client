"""Generic result wrapper for API operations with billing information."""

from dataclasses import dataclass
from typing import Any, Optional

from deeporigin.utils.cost import Estimate


@dataclass
class Result:
    """Generic result of an API operation.

    Wraps function output to provide unified access to computed data and
    billing information. When a quote is requested, data will be None and
    estimate will be populated. When a real run is performed, data will
    contain the function output and cost will reflect the actual charge.

    Attributes:
        data: The function output (e.g. LigandSet for docking, list[Pocket]
            for pocket finding). None when quote=True.
        estimate: Predicted cost info when quote=True, otherwise None.
        cost: Actual cost info after a completed run, otherwise None.

    Examples:
        >>> result = protein.dock(ligand=ligand, pocket=pocket, quote=True)
        >>> result.data     # None
        >>> result.estimate # Estimate(total_price=...)

        >>> result = protein.dock(ligand=ligand, pocket=pocket)
        >>> result.data     # LigandSet(...)
        >>> result.cost     # Estimate(total_price=...)
    """

    data: Any = None
    estimate: Optional[Estimate] = None
    cost: Optional[Estimate] = None
