# Risk-analysis plugins

Analyses such as fault tree analysis are plugins. A plugin runs on the selected suppliers and returns
generic blocks. The **Analyses** page, the Compare button and the chat tool `run_analysis` pick it up
automatically, so a new plugin needs no frontend code.

## Add a plugin

Create one Python module in `backend/app/plugins/`. Every module there is imported at startup.

```python
# backend/app/plugins/concentration.py
from . import register
from .base import Param, Result, RiskAnalysisPlugin


@register
class ConcentrationPlugin(RiskAnalysisPlugin):
    id = "concentration"                      # URL and chat name
    name = "Spend concentration"
    description = "Share of spend with the selected suppliers."
    requires_columns = ("purchase_order_volume_eur",)   # unavailable (with a reason) if missing
    min_suppliers, max_suppliers = 1, 20

    def params(self, ds):
        return [Param("top_n", "Top N", "number", 3, min=1, max=20, step=1)]

    def run(self, ds, ids, params):
        spend = ds.metrics["purchase_order_volume_eur"]
        rows = sorted(((sid, float(spend[ds.pos[sid]])) for sid in ids), key=lambda r: -r[1])
        total = sum(v for _, v in rows) or 1.0
        top = sum(v for _, v in rows[: int(params["top_n"])]) / total
        return Result(
            title="Spend concentration",
            summary=f"The top {int(params['top_n'])} suppliers hold {top:.0%} of the selected spend.",
            blocks=[
                {"type": "metrics", "items": [{"label": "Top-N share", "value": f"{top:.0%}"}]},
                {"type": "table", "columns": ["Supplier", "Spend (EUR)"], "rows": [[s, f"{v:,.0f}"] for s, v in rows]},
            ],
            assumptions=["Spend is Purchase Order Volume (EUR) from the dataset."],
            data={"chat": {"top_share": top}},   # optional: what the assistant sees
        )
```

Restart the backend. The plugin appears on the Analyses page and the assistant can call it.

## Contract

| Member | Meaning |
|---|---|
| `id`, `name`, `description`, `version` | metadata shown in the UI |
| `requires_columns` | snake_case columns the plugin needs; override `available(ds)` for other checks |
| `min_suppliers`, `max_suppliers` | how many suppliers can be selected |
| `params(ds) -> list[Param]` | form fields: `number` (min, max, step), `select` (options), `boolean` |
| `run(ds, ids, params) -> Result` | `params` are already coerced and clamped; raise `PluginError` for user errors |

`ds` is the loaded `Dataset` (`backend/app/dataset.py`): `ids`, `names`, `index`, `scores` (n × k) with
`score_cols`, `metrics`, `bands`, `weights`, `pos[supplier_id] → row`, and helpers such as `explain(id)`.

## Blocks the UI renders

| Block | Shape |
|---|---|
| `metrics` | `{"type": "metrics", "items": [{"label", "value", "sub"?}]}` |
| `text` | `{"type": "text", "markdown": "..."}` (rendered safely, no HTML) |
| `table` | `{"type": "table", "title"?, "columns": [...], "rows": [[...]], "note"?}` |
| `chart` | `{"type": "chart", "title"?, "option": <ECharts option>, "height"?}`: bar, scatter, radar, heatmap, tree |
| `fault_tree` | `{"type": "fault_tree", "title"?, "tree": <node>}` (see below) |
| `tabs` | `{"type": "tabs", "tabs": [{"label", "blocks": [...]}]}` |

## Fault tree analysis

`backend/app/plugins/fault_tree.py`, with tree templates in `backend/app/plugins/fault_trees/*.json`.

- **Tree file.** Gate nodes have `id`, `label`, `gate` (`OR`, `AND`, or `VOTE` with `k`) and `children`.
  A basic event has `id`, `label` and a score `column`. `{"ref": "<basic id>", "label": "..."}` reuses an event
  elsewhere in the tree (a repeated event). Add a JSON file to add a tree; it appears in the "Fault tree" field.
- **Probabilities.** Each basic event's yearly probability comes from the supplier's 0–100 score, log-linear
  (or linear) between "probability at score 0" and "probability at score 100", both adjustable. Risk scores
  are not calibrated probabilities, so read the results as relative rankings. The UI and the chat say so.
- **Computation.** The top-event and gate probabilities are exact for independent events, including repeated
  events (Shannon decomposition over the repeated events, checked against brute-force enumeration in
  `tests/test_plugins.py`). Minimal cut sets come from MOCUS. For each cause the plugin reports Fussell-Vesely
  importance (the share of the top-event probability that disappears if the cause is removed), Birnbaum
  importance, and the effect of a mitigation that lowers its score by N points.
- **Output.** A ranking of suppliers by top-event probability, branch probabilities, and per supplier: the
  tree with probabilities, importance and cut-set tables.
