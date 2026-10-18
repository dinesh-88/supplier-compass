"""Grounded chat: the model must get every number from a tool; every call is returned as the trace."""

from __future__ import annotations

import json
import re
import time

from . import llm
from .dataset import Dataset, category_label
from .descriptions import GLOSSARY
from .sqlguard import QueryEngine
from .tools import Toolbox, ToolError, openai_tools, summarise_result, to_jsonable

MAX_ROUNDS = 6
ID_RE = re.compile(r"\bSUPP_\d{5}\b", re.I)
NUMBER_RE = re.compile(r"(?<![A-Z_\d])\d+(?:[.,]\d+)?")


def system_prompt(ds: Dataset, engine: QueryEngine, context_ids: list[str]) -> str:
    f = ds.formula
    weights = ", ".join(f"{c} {w}%" for c, w in sorted(f["weights"].items(), key=lambda kv: -kv[1]))
    schema = ", ".join(f"{name} {typ}" for name, typ in engine.schema())
    bands = ", ".join(f"{b['level']} {b['min']}–{b['max']}" for b in ds.bands)
    ctx = (
        f"The user's current compare set / selection: {', '.join(context_ids)}. 'These' or 'them' refers to these."
        if context_ids
        else "The user has no suppliers selected."
    )
    approx = (
        ""
        if ds.verified
        else f"\nIMPORTANT: the index formula is only approximate (R² = {f['r2']:.3f}). Say 'approximately' in every index explanation."
    )
    return f"""You are Supplier Compass, an assistant for a rail procurement buyer choosing train component suppliers.
You answer questions about one supplier risk dataset of {ds.n:,} suppliers.

Rules:
- Never state a number, ranking or supplier fact from memory. Get it from a tool in this conversation first.
- For "why is the index high/low", call explain_index and lead with points_above_average (weight × (score − mean),
  i.e. how far each category pushes the supplier above an average supplier), not the raw contributions.
- Never infer a level (Low/Medium/High/Critical) yourself; use the level fields returned by the tools.
- Prefer explain_index for index explanations, compare for "which is better/lower on X",
  query_suppliers for counts, filters, top-N and aggregates, define for meanings of terms.
- When an everyday term maps to several columns (e.g. "financial risk" → financial_health_score and
  credit_rating_score), report each column separately, say clearly when they disagree, and then give the combined view
  using the index weights. Never silently pick one column.
- All scores are 0–100 where 100 = maximum risk, so lower is better. Delivery and confirmation rates are % where higher is better.
- Use make_chart when a chart helps (bar, radar, heatmap or scatter only). Use add_to_compare when the user asks to
  compare or shortlist suppliers.
- Be concise: a direct answer first, then the key numbers (with supplier IDs), then caveats. Use Markdown lists or small tables.
- If a tool returns an error, fix the call or say what you could not determine.

Dataset facts (from the loaded file, not from memory):
- Table `suppliers` columns: {schema}
- Total_Risk_Index = round_half_to_even(Σ weight × score) with weights: {weights}. Formula status: {f['label']}.{approx}
- Level bands: {bands}.
- Glossary terms you can pass to define/compare: {', '.join(sorted(GLOSSARY)[:40])}.
{ctx}"""


def _trace_entry(name: str, args: dict, result: dict | None, error: str | None, ms: float) -> dict:
    entry = {"tool": name, "args": args, "ms": round(ms, 1)}
    if error:
        entry["error"] = error
    else:
        entry["result"] = summarise_result(to_jsonable(result))
        if isinstance(result, dict) and "sql" in result:
            entry["sql"] = result["sql"]
    return entry


def run_chat(ds: Dataset, engine: QueryEngine, messages: list[dict], context_ids: list[str]) -> dict:
    tb = Toolbox(ds, engine)
    trace: list[dict] = []
    context_ids = [c for c in context_ids if c in ds.pos][:20]
    if llm.is_mock():
        answer = mock_answer(tb, trace, messages, context_ids)
        return _result(answer, trace, tb, mock=True)

    convo = [{"role": "system", "content": system_prompt(ds, engine, context_ids)}]
    for m in messages[-12:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            convo.append({"role": m["role"], "content": m["content"][:4000]})
    nudged = False
    answer = ""
    for _ in range(MAX_ROUNDS):
        try:
            out = llm.chat(convo, tools=openai_tools(), max_tokens=1800)
        except llm.LLMError as exc:
            return _result(f"The language model could not be reached ({exc}).", trace, tb, error=True)
        if out["tool_calls"]:
            convo.append({
                "role": "assistant",
                "content": out["content"] or "",
                "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                    for c in out["tool_calls"]
                ],
            })
            for c in out["tool_calls"]:
                content = _execute(tb, trace, c["name"], c["arguments"])
                convo.append({"role": "tool", "tool_call_id": c["id"], "content": content})
            continue
        answer = out["content"]
        if not trace and _has_numbers(answer) and not nudged:
            # Grounding guard: numbers without any tool call are not allowed.
            nudged = True
            convo.append({"role": "assistant", "content": answer})
            convo.append({"role": "user", "content": "Do not answer from memory. Call the tools to get the numbers, then answer."})
            continue
        break
    if not trace and _has_numbers(answer):
        answer += "\n\n_Note: no tool was called for this answer, so its numbers are not verified against the dataset._"
    return _result(answer or "I could not produce an answer.", trace, tb)


def _execute(tb: Toolbox, trace: list[dict], name: str, args: dict) -> str:
    t0 = time.perf_counter()
    try:
        result = tb.call(name, args)
        trace.append(_trace_entry(name, args, result, None, (time.perf_counter() - t0) * 1000))
        text = json.dumps(to_jsonable(result), default=str)
        return text[:12000]
    except ToolError as exc:
        trace.append(_trace_entry(name, args, None, str(exc), (time.perf_counter() - t0) * 1000))
        return json.dumps({"error": str(exc)})


def _has_numbers(text: str) -> bool:
    stripped = ID_RE.sub("", text or "")
    return bool(NUMBER_RE.search(stripped))


def _result(answer: str, trace: list[dict], tb: Toolbox, mock: bool = False, error: bool = False) -> dict:
    return {
        "answer": answer,
        "trace": trace,
        "charts": tb.charts,
        "actions": tb.actions,
        "mock": mock,
        "model": llm.model_name(),
        "error": error,
    }


# --------------------------------------------------------------------------- mock planner


def _call(tb: Toolbox, trace: list[dict], name: str, args: dict) -> dict | None:
    t0 = time.perf_counter()
    try:
        res = tb.call(name, args)
        trace.append(_trace_entry(name, args, res, None, (time.perf_counter() - t0) * 1000))
        return res
    except ToolError as exc:
        trace.append(_trace_entry(name, args, None, str(exc), (time.perf_counter() - t0) * 1000))
        return None


def _term_in(text: str) -> str | None:
    t = text.lower()
    for g in sorted(GLOSSARY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(g)}\b", t):
            return g
    return None


def mock_answer(tb: Toolbox, trace: list[dict], messages: list[dict], context_ids: list[str]) -> str:
    """Deterministic, clearly labelled stand-in for the LLM that still calls the real tools."""
    ds = tb.ds
    q = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "") or ""
    ql = q.lower()
    ids = [i.upper() for i in ID_RE.findall(q)]
    if not ids and re.search(r"\b(these|them|selected|selection|compare set|shortlist)\b", ql):
        ids = context_ids
    head = llm.MOCK_LABEL + "\n\n"
    term = _term_in(q)

    if ids and len(ids) == 1 and re.search(r"\bwhy\b", ql):
        e = _call(tb, trace, "explain_index", {"id": ids[0]})
        if not e:
            return head + f"I could not find {ids[0]} in the dataset."
        approx = "approximately " if e["approximate"] else ""
        lines = [
            f"**{e['supplierID']}** has a Total Risk Index of **{e['total_risk_index']:.0f}** ({e['level']}, "
            f"{int(e['percentile'])}th percentile). That is {approx}**{e['points_above_average_total']:+.1f} points** above an "
            f"average supplier ({e['average_index']:.1f}).",
            "",
            "Largest drivers (weight × (score − mean score)):",
        ]
        for d in e["top_drivers"][:5]:
            lines.append(
                f"- {d['label']}: score {d['score']:.0f} ({d['level']}) × {d['weight_pct']}% → **{d['points_above_average']:+.1f}** points"
            )
        off = [d for d in e["biggest_offsets"] if d["points_above_average"] < 0]
        if off:
            lines.append("")
            lines.append("Partly offset by: " + ", ".join(f"{d['label']} {d['points_above_average']:+.1f}" for d in off) + ".")
        lines.append("")
        lines.append(f"Formula: {e['formula']}.")
        return head + "\n".join(lines)

    if term and ids:
        d = _call(tb, trace, "define", {"term": term})
        c = _call(tb, trace, "compare", {"ids": ids, "fields": [term]})
        if not c:
            return head + "I could not compare those suppliers."
        lines = []
        cols = c["columns"]
        if d and d.get("ambiguous"):
            lines.append(f"“{term}” maps to **{len(cols)} columns**: " + ", ".join(f"`{x}`" for x in cols) + ". Here is each one:")
        lines.append("")
        lines.append("| Supplier | " + " | ".join(category_label(x) for x in cols) + " |")
        lines.append("|---|" + "---|" * len(cols))
        for r in c["rows"]:
            lines.append(f"| {r['supplierID']} | " + " | ".join(_fmt(r[x]) for x in cols) + " |")
        for g in c["multi_column_terms"]:
            lines.append("")
            for col, b in g["best_per_column"].items():
                lines.append(f"- Best on {category_label(col)}: **{b['supplierID']}** ({_fmt(b['value'])}, {b['direction']}).")
            if g["columns_disagree"]:
                worst = g["worst_per_column"]
                for col, b in g["best_per_column"].items():
                    for col2, w in worst.items():
                        if col2 != col and w["supplierID"] == b["supplierID"]:
                            lines.append(
                                f"- The columns **disagree**: {b['supplierID']} is best on {category_label(col)} but worst on "
                                f"{category_label(col2)} ({_fmt(w['value'])})."
                            )
            if "combined" in g:
                vals = ", ".join(f"{v['supplierID']} {v['combined']:.1f}" for v in g["combined"]["values"])
                lines.append(f"- Combined, {g['combined']['method']}: {vals}. Lowest: **{g['combined']['lowest']}**.")
        if not c["multi_column_terms"] and len(cols) == 1:
            best = min(c["rows"], key=lambda r: r[cols[0]] if r[cols[0]] is not None else 1e9)
            lines.append("")
            lines.append(f"Lowest {category_label(cols[0])}: **{best['supplierID']}** ({_fmt(best[cols[0]])}).")
        return head + "\n".join(lines)

    if ids and re.search(r"\b(compare|shortlist|side by side|add)\b", ql):
        c = _call(tb, trace, "compare", {"ids": ids, "fields": ["overall risk"]})
        _call(tb, trace, "make_chart", {"type": "radar", "title": "Category scores", "ids": ids[:5]})
        _call(tb, trace, "add_to_compare", {"ids": ids})
        if not c:
            return head + "I could not compare those suppliers."
        lines = ["| Supplier | Index | Level |", "|---|---|---|"]
        for r in sorted(c["index"], key=lambda r: r["total_risk_index"]):
            lines.append(f"| {r['supplierID']} | {r['total_risk_index']:.0f} | {r['level']} |")
        diff = c.get("most_different_categories") or []
        if diff:
            lines.append("")
            lines.append("They differ most on " + ", ".join(category_label(x) for x in diff) + ".")
        lines.append("")
        lines.append("Use the button below to add them to your compare set.")
        return head + "\n".join(lines)

    if re.search(r"\b(chart|plot|visuali[sz]e|graph)\b", ql):
        if ids:
            _call(tb, trace, "make_chart", {"type": "bar", "title": "Total Risk Index", "ids": ids, "fields": ["total_risk_index"]})
            return head + "Here is the Total Risk Index for those suppliers, coloured by level."
        sql = (
            "SELECT CASE WHEN total_risk_index >= 75 THEN 'Critical' WHEN total_risk_index >= 50 THEN 'High' "
            "WHEN total_risk_index >= 25 THEN 'Medium' ELSE 'Low' END AS level, count(*) AS suppliers "
            "FROM suppliers GROUP BY 1 ORDER BY min(total_risk_index)"
        )
        _call(tb, trace, "make_chart", {"type": "bar", "title": "Suppliers per level", "sql": sql})
        return head + "Here is how many suppliers fall in each level of the Total Risk Index."

    if re.search(r"\b(what is|what does|define|meaning|mean)\b", ql) and term:
        d = _call(tb, trace, "define", {"term": term})
        if d:
            parts = [f"- `{x['column']}` (index weight {x['index_weight_pct']}%): {x['definition']}" for x in d["definitions"]]
            return head + f"“{term}” in this dataset:\n" + "\n".join(parts) + f"\n\nSource: {d['source']}."

    if ids:
        g = _call(tb, trace, "get_suppliers", {"ids": ids, "fields": ["total_risk_index"]})
        if g:
            rows = "\n".join(f"- **{r['supplierID']}** ({r['name']}): index {r['total_risk_index']:.0f}, {r['level']}, rank #{r['official_rank']}" for r in g["rows"])
            return head + rows

    m = re.search(r"\btop\s+(\d+)", ql)
    if m or re.search(r"\b(lowest|safest|best)\b", ql):
        n = min(int(m.group(1)) if m else 10, 50)
        order = "DESC" if re.search(r"\b(highest|riskiest|worst)\b", ql) else "ASC"
        sql = f"SELECT supplier_id, supplier_name, total_risk_index FROM suppliers ORDER BY total_risk_index {order}, supplier_id LIMIT {n}"
        r = _call(tb, trace, "query_suppliers", {"sql": sql})
        if r:
            rows = "\n".join(f"{k + 1}. **{x[0]}** ({x[1]}): {x[2]:.0f}" for k, x in enumerate(r["rows"]))
            return head + f"{'Highest' if order == 'DESC' else 'Lowest'}-risk suppliers by Total Risk Index:\n{rows}"

    if re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", ql):
        level = next((b for b in ds.bands if b["level"].lower() in ql), None)
        if level:
            sql = f"SELECT count(*) AS suppliers FROM suppliers WHERE total_risk_index BETWEEN {level['min']} AND {level['max']}"
        else:
            sql = "SELECT count(*) AS suppliers FROM suppliers"
        r = _call(tb, trace, "query_suppliers", {"sql": sql})
        if r:
            what = f"with a {level['level']} Total Risk Index ({level['min']}–{level['max']})" if level else "in the dataset"
            return head + f"There are **{r['rows'][0][0]:,}** suppliers {what}."

    r = _call(tb, trace, "query_suppliers", {"sql": "SELECT count(*) AS suppliers, round(avg(total_risk_index), 1) AS mean_index, "
                                              "min(total_risk_index) AS min_index, max(total_risk_index) AS max_index FROM suppliers"})
    if r:
        n, mean, lo, hi = r["rows"][0]
        return head + (
            f"The mock assistant only understands a few question shapes (why is X high, which of X/Y/Z has the lowest <term>, "
            f"compare these, top N, how many, chart). Dataset overview: **{n:,}** suppliers, mean index {mean}, range {lo:.0f}–{hi:.0f}."
        )
    return head + "I could not answer that."


def _fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.0f}" if v.is_integer() else f"{v:.1f}"
    return str(v)
