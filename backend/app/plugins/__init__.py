"""Risk-analysis plugins. Every module in this package is imported, and classes decorated with
`@register` become available in the API, the Analyses page and the chat `run_analysis` tool."""

from __future__ import annotations

import importlib
import pkgutil

from ..dataset import Dataset
from .base import Param, PluginError, Result, RiskAnalysisPlugin

_REGISTRY: dict[str, RiskAnalysisPlugin] = {}
_loaded = False


def register(cls: type[RiskAnalysisPlugin]) -> type[RiskAnalysisPlugin]:
    if not getattr(cls, "id", None):
        raise TypeError(f"{cls.__name__} needs an id")
    if cls.id in _REGISTRY:
        raise TypeError(f"Duplicate plugin id {cls.id}")
    _REGISTRY[cls.id] = cls()
    return cls


def _discover() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for mod in pkgutil.iter_modules(__path__):
        if mod.name not in ("base",) and not mod.name.startswith("_"):
            importlib.import_module(f"{__name__}.{mod.name}")


def all_plugins() -> list[RiskAnalysisPlugin]:
    _discover()
    return list(_REGISTRY.values())


def get(plugin_id: str) -> RiskAnalysisPlugin:
    _discover()
    if plugin_id not in _REGISTRY:
        raise PluginError(f"Unknown analysis plugin {plugin_id!r}")
    return _REGISTRY[plugin_id]


def run(ds: Dataset, plugin_id: str, ids: list[str], params: dict | None = None) -> dict:
    plugin = get(plugin_id)
    ok, why = plugin.available(ds)
    if not ok:
        raise PluginError(f"{plugin.name} is not available for this dataset: {why}")
    clean = []
    for sid in ids:
        s = str(sid).strip().upper()
        if s not in ds.pos:
            raise PluginError(f"No supplier {s}")
        if s not in clean:
            clean.append(s)
    if not plugin.min_suppliers <= len(clean) <= plugin.max_suppliers:
        raise PluginError(f"{plugin.name} needs {plugin.min_suppliers}–{plugin.max_suppliers} suppliers")
    p = plugin.resolve_params(ds, params)
    result = plugin.run(ds, clean, p)
    return {
        "plugin": plugin.id,
        "plugin_name": plugin.name,
        "version": plugin.version,
        "ids": clean,
        "params": p,
        "title": result.title,
        "summary": result.summary,
        "assumptions": result.assumptions,
        "blocks": result.blocks,
        "data": result.data,
    }


__all__ = ["Param", "PluginError", "Result", "RiskAnalysisPlugin", "all_plugins", "get", "register", "run"]
