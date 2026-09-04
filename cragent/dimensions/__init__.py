"""Dimension plugins.

Importing this package registers every dimension implementation. Drop a new
module here that subclasses ``Dimension`` and add it to ``config.yaml`` -- no
other file needs to change.
"""
from __future__ import annotations

import importlib
import pkgutil

from cragent.dimensions.base import REGISTRY, Dimension, build_dimensions  # noqa: F401


def _load_plugins() -> None:
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_") or module.name == "base":
            continue
        importlib.import_module(f"{__name__}.{module.name}")


_load_plugins()

__all__ = ["REGISTRY", "Dimension", "build_dimensions"]
