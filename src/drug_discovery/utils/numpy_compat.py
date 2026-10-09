"""NumPy compatibility helpers for the scientific stack."""

import sys


def ensure_numpy_char_submodule() -> None:
    """Ensure ``import numpy.char`` works before Biotite serializes structures.

    Biotite calls ``np.char.array(...)`` when writing PDB records. On NumPy 2.x
    that resolves the ``char`` attribute via a lazy import of the ``numpy.char``
    subpackage. A partial or mixed NumPy install — common after ``pip install``
    in a long-lived Jupyter kernel — can leave that subpackage missing while the
    rest of NumPy still imports, which surfaces as::

        ModuleNotFoundError: No module named 'numpy.char'

    Register ``numpy.core.defchararray`` as ``numpy.char`` when the subpackage
    is absent so Biotite can continue to write structures.
    """
    if "numpy.char" in sys.modules:
        return
    try:
        import numpy.char  # noqa: F401
    except ModuleNotFoundError:
        import numpy.core.defchararray as defchararray

        sys.modules["numpy.char"] = defchararray
