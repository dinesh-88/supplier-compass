"""Chat tools. Each returns JSON-able data; the chat loop records every call for "How I got this"."""

from __future__ import annotations

import numpy as np

from . import compare as cmp
from . import descriptions, index_model
from .dataset import Dataset, category_label
from .sqlguard import QueryEngine, SQLRejected

CHART_TYPES = {"bar", "radar", "heatmap", "scatter"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
LEVEL_COLORS = {"Low": "#e8a177", "Medium": "#d26a3c", "High": "#a6401c", "Critical": "#661c0b"}

TOOL_SPECS = [
    {
        "name": "get_suppliers",
        "description": "Fetch rows for specific supplier IDs. Use for any question about named suppliers.",
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}, "description": "Supplier IDs like SUPP_00012 (max 20)"},
                "fields": {"type": "array", "items": {"type": "string"},
                           "description": "Column names (snake_case) or everyday terms; omit for all scores and metrics"},
            },
            "required": ["ids"],
        },
    },
    {
        "name": "query_suppliers",
        "description": "Run one read-only DuckDB SELECT against the `suppliers` table (only that table). "
        "LIMIT 200 is enforced. Use for counts, rankings, filters and aggregates.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    },
    {
        "name": "explain_index",
        "description": "Exact breakdown of one supplier's Total_Risk_Index: contribution (weight × score) and points "
        "above average (weight × (score − mean)) per category. Use for 'why is the index high/low'.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "compare",
        "description": "Compare suppliers on given fields or everyday terms (e.g. 'financial risk'). For terms that "
        "map to several columns it reports the best supplier per column, whether the columns disagree, and an "
        "index-weighted combination.",
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["ids"],
        },
    },
    {
        "name": "define",
        "description": "Definition of a column or everyday risk term from the column descriptions, and which "
        "columns it maps to.",
        "parameters": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]},
    },
    {
        "name": "make_chart",
        "description": "Render a chart inline in the chat from dataset values. type: bar | radar | heatmap | scatter. "
        "bar: one field across ids (or sql returning label, value). radar/heatmap: ids × fields. "
        "scatter: fields [x, y] for ids or for all suppliers, or sql returning x, y[, label].",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": sorted(CHART_TYPES)},
                "title": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "string"}},
                "fields": {"type": "array", "items": {"type": "string"}},
                "sql": {"type": "string"},
            },
            "required": ["type"],
        },
    },
    {
        "name": "add_to_compare",
        "description": "Offer the user a button that adds these suppliers to their compare set (max 20).",
        "parameters": {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["ids"],
        },
    },
]


def openai_tools() -> list[dict]:
    return [{"type": "function", "function": spec} for spec in TOOL_SPECS]


class ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, ds: Dataset, engine: QueryEngine):
        self.ds = ds
        self.engine = engine
        self.charts: list[dict] = []
        self.actions: list[dict] = []

    # ---------------------------------------------------------------- helpers

    def _ids(self, ids, limit: int = cmp.MAX_COMPARE) -> list[str]:
        if isinstance(ids, str):
            ids = [ids]
        out, missing = [], []
        for sid in ids or []:
            s = str(sid).strip().upper()
            if s in self.ds.pos:
                if s not in out:
                    out.append(s)
            else:
                missing.append(s)
        if missing and not out:
            raise ToolError(f"Unknown supplier IDs: {', '.join(missing)}")
        return out[:limit]

    def _columns(self, fields) -> list[str]:
        ds = self.ds
        available = ds.score_cols + list(ds.metrics) + list(ds.text) + ["total_risk_index"]
        cols: list[str] = []
        for f in fields or []:
            d = descriptions.define(str(f), ds.meta["descriptions"], available, ds.formula["weights"])
            for c in d["columns"]:
                if c not in cols:
                    cols.append(c)
        return cols

    def _value(self, i: int, col: str):
        return cmp._value(self.ds, i, col)

    # ---------------------------------------------------------------- tools

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            raise ToolError(f"Unknown tool {name}")
        try:
            return fn(**(args or {}))
        except TypeError as exc:
            raise ToolError(f"Bad arguments for {name}: {exc}") from exc
        except KeyError as exc:
            raise ToolError(f"Unknown supplier {exc.args[0]}") from exc
        except SQLRejected as exc:
            raise ToolError(str(exc)) from exc

    def t_get_suppliers(self, ids, fields=None) -> dict:
        ds = self.ds
        ids = self._ids(ids)
        cols = self._columns(fields) if fields else ["total_risk_index", *ds.score_cols, *ds.metrics]
        rows = []
        for sid in ids:
            i = ds.pos[sid]
            r = {"supplierID": sid, "name": ds.names[i]}
            for c in cols:
                r[c] = self._value(i, c)
                if c in ds.score_cols:
                    r[f"{c}_level"] = index_model.level_of(r[c], ds.bands)
            r["level"] = index_model.level_of(ds.index[i], ds.bands)
            r["official_rank"] = int(ds.official_rank[i])
            rows.append(r)
        return {"columns": cols, "rows": rows}

    def t_query_suppliers(self, sql: str) -> dict:
        return self.engine.run(sql)

    def t_explain_index(self, id: str) -> dict:
        e = self.ds.explain(id)
        keep = ("column", "label", "score", "weight_pct", "contribution", "mean_score", "points_above_average", "level", "percentile")
        return {
            "supplierID": e["supplierID"],
            "name": e["name"],
            "total_risk_index": e["total_risk_index"],
            "level": e["level"],
            "percentile": e["percentile"],
            "formula": e["formula_label"],
            "approximate": e["approximate"],
            "weighted_sum": e["weighted_sum"],
            "average_index": e["average_index"],
            "points_above_average_total": e["points_above_average_total"],
            "top_drivers": [{k: d[k] for k in keep} for d in e["drivers"][:6]],
            "biggest_offsets": [{k: d[k] for k in keep} for d in e["drivers"][-3:]],
            "note": e["note"],
        }

    def t_compare(self, ids, fields=None) -> dict:
        ids = self._ids(ids)
        out = cmp.field_comparison(self.ds, ids, fields or ["overall risk"])
        out["index"] = [
            {"supplierID": sid, "total_risk_index": float(self.ds.index[self.ds.pos[sid]]),
             "level": index_model.level_of(self.ds.index[self.ds.pos[sid]], self.ds.bands)}
            for sid in ids
        ]
        if len(ids) >= 2:
            c = cmp.compare(self.ds, ids)
            out["most_different_categories"] = c["most_different"]
        return out

    def t_define(self, term: str) -> dict:
        ds = self.ds
        available = ds.score_cols + list(ds.metrics) + list(ds.text) + ["total_risk_index"]
        return descriptions.define(term, ds.meta["descriptions"], available, ds.formula["weights"])

    def t_add_to_compare(self, ids) -> dict:
        ids = self._ids(ids)
        self.actions.append({"type": "add_to_compare", "ids": ids})
        return {"offered": ids, "note": "A button to add these to the compare set is shown to the user."}

    def t_make_chart(self, type: str, title: str | None = None, ids=None, fields=None, sql: str | None = None) -> dict:
        if type not in CHART_TYPES:
            raise ToolError(f"Chart type must be one of {sorted(CHART_TYPES)}")
        ds = self.ds
        cols = self._columns(fields) if fields else []
        source: dict = {"type": type}
        if type == "bar":
            option, source = self._bar(ids, cols, sql, title)
        elif type in ("radar", "heatmap"):
            sel = self._ids(ids, limit=5 if type == "radar" else 20)
            if not sel:
                raise ToolError(f"{type} needs supplier ids")
            cols = [c for c in (cols or ds.score_cols) if c in ds.score_cols] or ds.score_cols
            option = self._radar(sel, cols, title) if type == "radar" else self._heatmap(sel, cols, title)
            source = {"ids": sel, "fields": cols}
        else:
            option, source = self._scatter(ids, cols, sql, title)
        chart = {"type": type, "title": title or "", "option": option, "source": source}
        self.charts.append(chart)
        return {"rendered": True, "type": type, "source": source, "note": "The chart is shown to the user inline."}

    # ---------------------------------------------------------------- chart builders

    def _base(self, title):
        return {
            "title": {"text": title or "", "left": 0, "textStyle": {"fontSize": 13, "fontWeight": 600, "color": "#16191d"}},
            "tooltip": {"trigger": "item"},
        }

    def _bar(self, ids, cols, sql, title):
        ds = self.ds
        if sql:
            res = self.engine.run(sql)
            if len(res["columns"]) < 2:
                raise ToolError("Bar chart SQL must return a label column and a numeric value column")
            labels = [str(r[0]) for r in res["rows"]][:40]
            values = [r[1] for r in res["rows"]][:40]
            ylab = res["columns"][1]
            source = {"sql": res["sql"], "rows": len(labels)}
            colors = ["#00727f"] * len(values)
        else:
            sel = self._ids(ids)
            if not sel:
                raise ToolError("Bar chart needs ids or sql")
            col = cols[0] if cols else "total_risk_index"
            labels = sel
            values = [self._value(ds.pos[s], col) for s in sel]
            ylab = col
            source = {"ids": sel, "fields": [col]}
            if col in ds.score_cols or col == "total_risk_index":
                colors = [LEVEL_COLORS.get(index_model.level_of(v or 0, ds.bands), "#00727f") for v in values]
            else:
                colors = ["#00727f"] * len(values)
        opt = self._base(title)
        opt.update(
            grid={"left": 48, "right": 12, "top": 34, "bottom": 54},
            tooltip={"trigger": "axis", "axisPointer": {"type": "shadow"}},
            xAxis={"type": "category", "data": labels, "axisLabel": {"rotate": 30 if len(labels) > 5 else 0, "fontSize": 11}},
            yAxis={"type": "value", "name": ylab, "splitLine": {"lineStyle": {"color": "#eef0f2"}}},
            series=[{"type": "bar", "data": [{"value": v, "itemStyle": {"color": c, "borderRadius": [3, 3, 0, 0]}} for v, c in zip(values, colors)],
                     "label": {"show": len(values) <= 12, "position": "top", "fontSize": 11}, "barMaxWidth": 36}],
        )
        return opt, source

    def _radar(self, sel, cols, title):
        ds = self.ds
        opt = self._base(title)
        opt.update(
            legend={"bottom": 0},
            radar={"indicator": [{"name": category_label(c), "max": 100} for c in cols], "radius": "62%",
                   "axisName": {"fontSize": 10, "color": "#4b5259"}, "splitArea": {"show": False}},
            series=[{"type": "radar", "data": [
                {"name": s, "value": [self._value(ds.pos[s], c) for c in cols],
                 "lineStyle": {"color": SERIES[k], "width": 2}, "itemStyle": {"color": SERIES[k]},
                 "areaStyle": {"color": SERIES[k], "opacity": 0.06}}
                for k, s in enumerate(sel)
            ]}],
        )
        return opt

    def _heatmap(self, sel, cols, title):
        ds = self.ds
        data = [[x, y, self._value(ds.pos[s], c)] for y, s in enumerate(sel) for x, c in enumerate(cols)]
        opt = self._base(title)
        opt.update(
            grid={"left": 90, "right": 12, "top": 34, "bottom": 96},
            xAxis={"type": "category", "data": [category_label(c) for c in cols], "axisLabel": {"rotate": 45, "fontSize": 10}},
            yAxis={"type": "category", "data": sel, "inverse": True},
            visualMap={"type": "piecewise", "orient": "horizontal", "bottom": 0, "left": "center",
                       "pieces": [{"min": b["min"], "max": b["max"] + 0.999, "label": f"{b['level']} {b['min']}–{b['max']}",
                                   "color": LEVEL_COLORS.get(b["level"], "#a6401c")} for b in ds.bands]},
            series=[{"type": "heatmap", "data": data, "label": {"show": True, "fontSize": 10, "color": "#fff"},
                     "itemStyle": {"borderColor": "#fff", "borderWidth": 2}}],
        )
        return opt

    def _scatter(self, ids, cols, sql, title):
        ds = self.ds
        if sql:
            res = self.engine.run(sql)
            if len(res["columns"]) < 2:
                raise ToolError("Scatter SQL must return x and y columns")
            pts = [[r[0], r[1], str(r[2]) if len(r) > 2 else ""] for r in res["rows"]]
            xl, yl = res["columns"][0], res["columns"][1]
            source = {"sql": res["sql"], "rows": len(pts)}
        else:
            if len(cols) < 2:
                raise ToolError("Scatter needs two fields (x, y) or sql")
            xl, yl = cols[0], cols[1]
            sel = self._ids(ids, limit=10_000) if ids else list(ds.ids)
            pts = [[self._value(ds.pos[s], xl), self._value(ds.pos[s], yl), s] for s in sel]
            source = {"fields": [xl, yl], "ids": sel if ids else "all suppliers", "rows": len(pts)}
        opt = self._base(title)
        log_x = xl == "purchase_order_volume_eur"
        opt.update(
            grid={"left": 52, "right": 16, "top": 34, "bottom": 40},
            xAxis={"type": "log" if log_x else "value", "name": xl, "nameLocation": "middle", "nameGap": 26, "scale": True,
                   "splitLine": {"lineStyle": {"color": "#eef0f2"}}},
            yAxis={"type": "value", "name": yl, "scale": True, "splitLine": {"lineStyle": {"color": "#eef0f2"}}},
            series=[{"type": "scatter", "data": pts, "symbolSize": 4 if len(pts) > 500 else 8,
                     "itemStyle": {"color": "#00727f", "opacity": 0.6 if len(pts) > 500 else 0.9},
                     "large": len(pts) > 2000}],
        )
        return opt, source


def summarise_result(result: dict, max_rows: int = 30) -> dict:
    """Trimmed copy of a tool result for the trace shown in the UI."""
    out = dict(result)
    for key in ("rows", "values"):
        if isinstance(out.get(key), list) and len(out[key]) > max_rows:
            out[key] = out[key][:max_rows]
            out[f"{key}_truncated"] = True
    return out


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj
