"""Grounded chat: the model must get every number from a tool; every call is returned as the trace."""

from __future__ import annotations

import json
import re
import time

from . import llm
from .dataset import Dataset
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
    if not llm.configured():
        return _result("The assistant is not configured: set LLM_API_KEY (and LLM_MODEL) and restart.", trace, tb, error=True)

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
        return _fit(to_jsonable(result))
    except ToolError as exc:
        trace.append(_trace_entry(name, args, None, str(exc), (time.perf_counter() - t0) * 1000))
        return json.dumps({"error": str(exc)})


TOOL_RESULT_LIMIT = 24000


def _fit(result) -> str:
    """Tool result as JSON for the model; shortened structurally (never cut mid-JSON) when too large."""
    from .tools import _compact

    text = json.dumps(result, default=str)
    if len(text) <= TOOL_RESULT_LIMIT:
        return text
    text = json.dumps({"note": "result shortened: lists cut to 5 items", "result": _compact(result)}, default=str)
    if len(text) <= TOOL_RESULT_LIMIT:
        return text
    keys = list(result) if isinstance(result, dict) else []
    return json.dumps({"error": "result too large to return; narrow the request", "keys": keys})


def _has_numbers(text: str) -> bool:
    stripped = ID_RE.sub("", text or "")
    return bool(NUMBER_RE.search(stripped))


def _result(answer: str, trace: list[dict], tb: Toolbox, error: bool = False) -> dict:
    return {
        "answer": answer,
        "trace": trace,
        "charts": tb.charts,
        "actions": tb.actions,
        "model": llm.model_name(),
        "error": error,
    }
