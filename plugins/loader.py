"""Plugin loader.

Discovers plugin modules inside the ``plugins`` package and calls each one's
``setup(registry)`` entry point. This is how future AI batches register
themselves without the core UI knowing about them.
"""

from __future__ import annotations

import importlib
import pkgutil

from core.plugin_registry import PluginRegistry


def load_all(registry: PluginRegistry, package_name: str = "plugins") -> list[str]:
    """Import every submodule of ``package_name`` and run its ``setup``.

    Returns the names of plugins successfully loaded.
    """
    loaded: list[str] = []
    try:
        package = importlib.import_module(package_name)
    except Exception:
        return loaded

    for module_info in pkgutil.iter_modules(package.__path__, package_name + "."):
        if module_info.name.split(".")[-1].startswith("_"):
            continue  # skip private modules (e.g. loader itself)
        try:
            module = importlib.import_module(module_info.name)
        except Exception:
            continue
        setup = getattr(module, "setup", None)
        if callable(setup):
            setup(registry)
            loaded.extend(registry.names())
    return loaded
