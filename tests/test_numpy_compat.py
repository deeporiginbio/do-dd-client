"""Tests for NumPy compatibility shims."""

import sys

from deeporigin.drug_discovery.utils.numpy_compat import ensure_numpy_char_submodule


def test_ensure_numpy_char_submodule_idempotent() -> None:
    ensure_numpy_char_submodule()
    import numpy.char

    assert hasattr(numpy.char, "array")


def test_ensure_numpy_char_submodule_registers_defchararray_shim() -> None:
    saved = sys.modules.pop("numpy.char", None)
    try:
        ensure_numpy_char_submodule()
        import numpy.char

        assert hasattr(numpy.char, "array")
        numpy.char.array(["ATOM"])
    finally:
        if saved is not None:
            sys.modules["numpy.char"] = saved
