"""Risk-analysis plugin contract.

A plugin is a class with metadata and a `run()` method. It receives the loaded dataset and the selected
supplier IDs and returns a `Result` made of generic blocks the UI already knows how to render:

    metrics     {"type": "metrics", "items": [{"label", "value", "sub"?}]}
    text        {"type": "text", "markdown": "..."}
    table       {"type": "table", "title"?, "columns": [...], "rows": [[...]], "note"?}
    chart       {"type": "chart", "title"?, "option": <ECharts option>, "height"?}
    fault_tree  {"type": "fault_tree", "title"?, "tree": <node>}
    tabs        {"type": "tabs", "tabs": [{"label", "blocks": [...]}]}

So a new plugin needs no frontend code. Register it with the `@register` decorator in any module inside
`app/plugins/` (modules are discovered automatically).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..dataset import Dataset


@dataclass
class Param:
    """One user-adjustable parameter; rendered as a form field."""

    key: str
    label: str
    type: str  # "number" | "select" | "boolean" | "text"
    default: Any
    help: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[dict] | None = None  # for select: [{"value", "label"}]
    widget: str | None = None  # number: "slider"; text: "textarea"
    max_length: int | None = None  # for text
    placeholder: str | None = None
    zero_label: str | None = None  # slider: what 0 means, e.g. "suggested"

    def coerce(self, value: Any) -> Any:
        if value is None:
            return self.default
        if self.type == "number":
            v = float(value)
            if self.min is not None:
                v = max(self.min, v)
            if self.max is not None:
                v = min(self.max, v)
            return v
        if self.type == "boolean":
            return bool(value)
        if self.type == "text":
            return " ".join(str(value).split())[: self.max_length or 500]
        if self.type == "select":
            allowed = {o["value"] for o in self.options or []}
            return value if value in allowed else self.default
        return value

    def spec(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Result:
    title: str
    summary: str
    blocks: list[dict]
    assumptions: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)  # machine-readable results; data["chat"] (optional) is what the assistant sees


class PluginError(ValueError):
    pass


class RiskAnalysisPlugin(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]
    version: ClassVar[str] = "1.0"
    requires_columns: ClassVar[tuple[str, ...]] = ()
    min_suppliers: ClassVar[int] = 1
    max_suppliers: ClassVar[int] = 20

    def params(self, ds: Dataset) -> list[Param]:
        return []

    def presets(self, ds: Dataset) -> list[dict]:
        """Optional one-click parameter sets, shown as buttons: [{"label", "params": {...}, "help"?}]."""
        return []

    def available(self, ds: Dataset) -> tuple[bool, str]:
        missing = [c for c in self.requires_columns if c not in ds.score_cols and c not in ds.metrics]
        if missing:
            return False, "needs columns: " + ", ".join(ds.original(c) for c in missing)
        return True, ""

    def describe(self, ds: Dataset) -> dict:
        ok, why = self.available(ds)
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "available": ok,
            "unavailable_reason": why,
            "min_suppliers": self.min_suppliers,
            "max_suppliers": self.max_suppliers,
            "params": [p.spec() for p in self.params(ds)],
            "presets": self.presets(ds),
        }

    def resolve_params(self, ds: Dataset, raw: dict | None) -> dict:
        raw = raw or {}
        return {p.key: p.coerce(raw.get(p.key)) for p in self.params(ds)}

    @abstractmethod
    def run(self, ds: Dataset, ids: list[str], params: dict) -> Result: ...
