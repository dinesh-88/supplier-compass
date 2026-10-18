"""Shortlist memo: tables and numbers come from the data; the LLM only writes prose, which is number-checked."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import compare as cmp
from . import index_model, llm
from . import weights as wmod
from .dataset import Dataset, category_label

ID_RE = re.compile(r"SUPP_\d{5}")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _eur(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    if v >= 1e6:
        return f"€{v / 1e6:.2f}M"
    if v >= 1e3:
        return f"€{v / 1e3:.0f}k"
    return f"€{v:.0f}"


def _num(v, d=0) -> str:
    if v is None:
        return "–"
    return f"{v:.{d}f}"


def build_facts(ds: Dataset, ids: list[str], weights: dict | None, preset_label: str, research: list[dict]) -> dict:
    official = wmod.is_official(ds, weights)
    custom = None if official else wmod.custom_index(ds, weights)
    comp = cmp.compare(ds, ids, weights)
    rows = comp["suppliers"]
    key = (lambda r: r["custom_index"]) if custom else (lambda r: r["total_risk_index"])
    rows.sort(key=lambda r: (key(r), r["supplierID"]))
    shortlist = []
    for k, r in enumerate(rows, 1):
        i = ds.pos[r["supplierID"]]
        shortlist.append({
            "position": k,
            "supplierID": r["supplierID"],
            "name": r["name"],
            "official_index": r["total_risk_index"],
            "official_level": r["level"],
            "official_rank": r["official_rank"],
            "custom_index": r.get("custom_index"),
            "custom_level": index_model.level_of(r["custom_index"], ds.bands) if custom else None,
            "custom_rank": r.get("custom_rank"),
            "rank_change": r.get("rank_change"),
            "spend": r.get("purchase_order_volume_eur"),
            "delivery": r.get("supplier_delivery_rating"),
            "sourcing": r.get("sourcing_risk_level"),
            "exposure_list": r["exposure_list"],
            "delivery_mismatch": r["delivery_mismatch"],
            "mismatch_note": ds.mismatch_info(i)["explanation"] if r["delivery_mismatch"] and ds.mismatch_info(i) else None,
        })

    wtable = []
    for k, c in enumerate(ds.score_cols):
        off = int(ds.weights[k])
        cu = custom["weights_pct"][c] if custom else off
        change = "raised" if cu - off >= 0.5 else "lowered" if off - cu >= 0.5 else ""
        wtable.append({"column": c, "label": category_label(c), "official": off, "custom": round(cu, 1), "changed": bool(change), "change": change})

    diffs = None
    if len(shortlist) >= 2:
        diffs = cmp.why(ds, shortlist[0]["supplierID"], shortlist[1]["supplierID"], weights)

    risks = []
    for s in shortlist:
        i = ds.pos[s["supplierID"]]
        drivers = [d for d in ds.explain(s["supplierID"])["drivers"] if d["level"] in ("High", "Critical")][:3]
        items = [f"{d['label']} score {d['score']:.0f} ({d['level']}, {d['points_above_average']:+.1f} index points vs average)" for d in drivers]
        if s["exposure_list"]:
            items.append(f"on the exposure list: spend {_eur(s['spend'])} with a Critical index")
        if s["delivery_mismatch"] and s["mismatch_note"]:
            items.append("delivery record doesn't match risk scores: " + s["mismatch_note"])
        if s.get("sourcing") == "High":
            items.append("Sourcing Risk Level High (hard to replace)")
        risks.append({"supplierID": s["supplierID"], "items": items or ["no category at High or Critical"]})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": ds.meta["file_name"],
        "formula": ds.formula["label"],
        "official_weights": official,
        "preset_label": "Official index" if official else preset_label,
        "weights": wtable,
        "shortlist": shortlist,
        "most_different": [category_label(c) for c in comp["most_different"]],
        "top_two": diffs,
        "risks": risks,
        "research": [
            {"id": r["id"], "company": r["company"], "country": r.get("country", ""), "date": r["research_date"],
             "overall_level": r["overall_level"], "confidence": r["confidence"]["level"], "summary": r["executive_summary"],
             "sanctions": r["sanctions"]["status"],
             "categories": [{"label": c["label"], "level": c["level"], "red_flags": c["red_flags"]} for c in r["categories"]],
             "red_flags": [{"id": f["id"], "quote": f["quote"], "url": f["url"], "domain": f["domain"], "single_source": f.get("single_source", True)}
                           for c in r["categories"] for f in c["evidence"] if f["classification"] == "red_flag"][:8],
             "mock": r.get("mock", {})}
            for r in research
        ],
    }


# --------------------------------------------------------------------------- prose


def _numbers(obj) -> set[str]:
    out = set()
    for n in NUM_RE.findall(ID_RE.sub("", json.dumps(obj))):
        out.add(n)
        try:
            f = float(n.replace(",", "."))
        except ValueError:
            continue
        out.update({f"{f:.0f}", f"{f:.1f}", f"{f:.2f}", f"{abs(f):.0f}", f"{abs(f):.1f}"})
    return out


def _entity_numbers(facts: dict) -> dict[str, set[str]]:
    """Numbers that may be stated about each supplier, category and researched company."""
    ents: dict[str, set[str]] = {}
    for s in facts["shortlist"]:
        risk = next((r for r in facts["risks"] if r["supplierID"] == s["supplierID"]), {})
        ents[s["supplierID"].lower()] = _numbers(s) | _numbers(risk)
    t = facts.get("top_two")
    if t:
        for sid in (t["a"], t["b"]):
            ents[sid.lower()] = ents.get(sid.lower(), set()) | _numbers(t)
        for d in t["differences"]:
            ents.setdefault(d["label"].lower(), set()).update(_numbers(d))
    for w in facts["weights"]:
        ents.setdefault(w["label"].lower(), set()).update(_numbers(w))
    for r in facts["research"]:
        ents[r["company"].lower()] = _numbers(r)
    return ents


def check_numbers(prose: str, facts: dict) -> tuple[str, list[str]]:
    """Remove sentences whose numbers are not facts about the suppliers, categories or companies they name."""
    ents = _entity_numbers(facts)
    generic = {str(len(facts["shortlist"])), "10", "100"}
    kept, removed = [], []
    for para in prose.split("\n"):
        good = []
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            nums = NUM_RE.findall(ID_RE.sub("", sentence))
            if not nums:
                good.append(sentence)
                continue
            low = sentence.lower()
            named = [k for k in ents if k in low]
            allowed = set().union(*(ents[k] for k in named)) | generic if named else generic
            if all(n in allowed for n in nums):
                good.append(sentence)
            else:
                removed.append(sentence)
        kept.append(" ".join(good))
    return "\n".join(kept).strip(), removed


def write_prose(facts: dict, rationale: str) -> dict:
    sl = facts["shortlist"]
    if llm.is_mock() or not sl:
        return {"text": _template_prose(facts, rationale), "removed": [], "source": "template (mock LLM)" if llm.is_mock() else "template"}
    prompt = (
        "Write the prose part of a supplier shortlist memo for a rail procurement buyer: two short paragraphs, "
        "(1) recommendation: which supplier to prefer and why, (2) what the buyer should do before awarding "
        "(mitigations, verifications). Use only these facts; any number you write must appear in the facts. "
        "Refer to suppliers by ID. Lower index = lower risk. Mention if a recommendation depends on custom weights. "
        "If research reports are attached, mention their red flags and that sanctions matches are only possible matches.\n\n"
        f"Buyer's reason for the weights: {rationale or '(not given)'}\n\nFacts:\n{json.dumps(facts)[:14000]}"
    )
    try:
        text = llm.chat([{"role": "system", "content": "You write concise, factual procurement memos."},
                         {"role": "user", "content": prompt}], max_tokens=700)["content"]
    except llm.LLMError:
        return {"text": _template_prose(facts, rationale), "removed": [], "source": "template (LLM unavailable)"}
    text, removed = check_numbers(text, facts)
    return {"text": text or _template_prose(facts, rationale), "removed": removed, "source": llm.model_name()}


def _template_prose(facts: dict, rationale: str) -> str:
    sl = facts["shortlist"]
    if not sl:
        return "No suppliers selected."
    top = sl[0]
    basis = "your custom weights" if not facts["official_weights"] else "the official Total Risk Index"
    idx = f"{_num(top['custom_index'], 1)} under {facts['preset_label']} (official {_num(top['official_index'])})" if top["custom_index"] is not None else _num(top["official_index"])
    p1 = f"{llm.MOCK_LABEL if llm.is_mock() else ''} Prefer {top['supplierID']} ({top['name']}): it has the lowest index in the shortlist by {basis}, {idx}, {top['official_level']}.".strip()
    if facts.get("top_two"):
        t = facts["top_two"]
        if t["index_gap"]:
            p1 += f" Against {t['b']} the official gap is {t['index_gap']:+.0f} points."
        else:
            p1 += f" It ties with {t['b']} on the official index, so the buyer weights decide the order."
    risks = next(r for r in facts["risks"] if r["supplierID"] == top["supplierID"])["items"]
    p2 = "Before awarding, address: " + "; ".join(risks) + "."
    if facts["research"]:
        p2 += " Review the attached research reports; any sanctions name match is only a possible match to verify."
    return p1 + "\n\n" + p2


# --------------------------------------------------------------------------- markdown


def to_markdown(facts: dict, prose: dict, rationale: str, title: str) -> str:
    L: list[str] = []
    L.append(f"# {title or 'Supplier shortlist memo'}")
    L.append("")
    L.append(f"Generated {facts['generated_at'][:16].replace('T', ' ')} UTC from {facts['dataset']}. Index formula: {facts['formula']}. "
             "All numbers come from the dataset; the prose is written by the assistant and number-checked.")
    L.append("")
    L.append("## Recommendation")
    L.append("")
    L.append(prose["text"])
    if prose.get("removed"):
        L.append("")
        L.append(f"_{len(prose['removed'])} sentence(s) removed because they contained numbers not found in the data._")
    L.append("")
    L.append("## Weights used and why")
    L.append("")
    L.append(f"**{facts['preset_label']}**. {rationale or 'No reason given.'}")
    L.append("")
    changed = [w for w in facts["weights"] if w["changed"]]
    if facts["official_weights"]:
        L.append("The official Total_Risk_Index weights were used (custom index = official index).")
    else:
        L.append("| Category | Official weight | Buyer weight |")
        L.append("|---|---|---|")
        for w in sorted(facts["weights"], key=lambda w: -w["custom"]):
            mark = f" ({w['change']})" if w["change"] == "raised" else ""
            L.append(f"| {w['label']}{mark} | {w['official']}% | {w['custom']:.1f}% |")
        L.append("")
        raised = [w["label"] for w in facts["weights"] if w["change"] == "raised"]
        L.append(f"Raised: {', '.join(raised) or 'none'}. The other {len(changed) - len(raised)} changed categories were lowered only by renormalising to 100%. "
                 "The official index is unchanged and shown alongside.")
    L.append("")
    L.append("## Ranked shortlist")
    L.append("")
    custom = not facts["official_weights"]
    head = "| # | Supplier | Name | Official index | " + ("Custom index | Rank change | " if custom else "") + "Spend | Delivery |"
    L.append(head)
    L.append("|" + "---|" * (head.count("|") - 1))
    for s in facts["shortlist"]:
        row = f"| {s['position']} | {s['supplierID']} | {s['name']} | {_num(s['official_index'])} {s['official_level']} | "
        if custom:
            ch = s["rank_change"] or 0
            row += f"{_num(s['custom_index'], 1)} {s['custom_level']} | {'↑ ' + str(ch) if ch > 0 else '↓ ' + str(-ch) if ch < 0 else '0'} | "
        row += f"{_eur(s['spend'])} | {_num(s['delivery'], 1)}% |"
        L.append(row)
    L.append("")
    L.append("Lower index = lower risk. Rank change compares the supplier's position among all suppliers under the buyer weights with its official position.")
    L.append("")
    L.append("## Key differences")
    L.append("")
    if facts["most_different"]:
        L.append("Categories where the shortlisted suppliers differ most: " + ", ".join(facts["most_different"]) + ".")
        L.append("")
    t = facts.get("top_two")
    if t:
        L.append(f"**{t['a']} vs {t['b']}**: official index {t['index_a']:.0f} vs {t['index_b']:.0f} (gap {t['index_gap']:+.0f}). Categories differing by 10 points or more:")
        L.append("")
        L.append("| Category | " + t["a"] + " | " + t["b"] + " | Weight | Effect on index |")
        L.append("|---|---|---|---|---|")
        for d in t["differences"]:
            L.append(f"| {d['label']} | {d['score_a']:.0f} | {d['score_b']:.0f} | {d['weight_pct']}% | {d['effect_official']:+.2f} |")
        if not t["differences"]:
            L.append("| (none) | | | | |")
    L.append("")
    L.append("## Risks to mitigate")
    L.append("")
    for r in facts["risks"]:
        L.append(f"- **{r['supplierID']}**: " + "; ".join(r["items"]) + ".")
    if facts["research"]:
        L.append("")
        L.append("## Attached research reports")
        for r in facts["research"]:
            L.append("")
            mock = " (mock data)" if r["mock"].get("search") else ""
            L.append(f"### {r['company']}{(' (' + r['country'] + ')') if r['country'] else ''}: {r['overall_level']}{mock}")
            L.append("")
            L.append(f"Research date {r['date']} · confidence {r['confidence']} · sanctions screening: {r['sanctions']}.")
            L.append("")
            L.append(r["summary"])
            L.append("")
            L.append("| Category | Risk | Red flags |")
            L.append("|---|---|---|")
            for c in r["categories"]:
                L.append(f"| {c['label']} | {c['level']} | {c['red_flags']} |")
            if r["red_flags"]:
                L.append("")
                for f in r["red_flags"]:
                    L.append(f"- {f['id']}: “{f['quote']}” [{f['domain']}]({f['url']}){' (single source)' if f['single_source'] else ''}")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- PDF

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]
LATIN1_FIX = {"€": "EUR", "↑": "+", "↓": "-", "–": "-", "—": "-", "−": "-", "“": '"', "”": '"', "’": "'", "‘": "'",
              "≥": ">=", "≤": "<=", "≠": "!=", "…": "...", "·": "-", "→": "->", "²": "2"}


def _size_table_columns(html: str) -> str:
    """fpdf2 splits table width evenly; give each column a share based on its longest cell."""

    def fix(m: re.Match) -> str:
        table = m.group(0)
        rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)
        lengths: list[int] = []
        for r in rows:
            for k, cell in enumerate(re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)):
                text = re.sub(r"<[^>]+>", "", cell)
                longest_word = max((len(w) for w in text.split()), default=0)
                need = max(min(len(text), 28), round(longest_word * 1.25), 4)
                if k >= len(lengths):
                    lengths.append(need)
                else:
                    lengths[k] = max(lengths[k], need)
        total = sum(lengths) or 1
        widths = iter(f'{max(6, round(n / total * 100))}%' for n in lengths)
        head = re.search(r"<tr>(.*?)</tr>", table, re.S)
        if not head:
            return table
        new_head = re.sub(r"<th(?=[ >])", lambda _: f'<th width="{next(widths, "10%")}"', head.group(1))
        return table.replace(head.group(1), new_head, 1)

    return re.sub(r"<table>.*?</table>", fix, html, flags=re.S)


def to_pdf(markdown_text: str) -> bytes:
    from fpdf import FPDF, FontFace
    from markdown_it import MarkdownIt

    html = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown_text)
    html = _size_table_columns(html)
    pdf = FPDF(format="A4")
    pdf.set_margins(16, 16, 16)
    pdf.set_auto_page_break(True, margin=16)
    font = next((p for p in FONT_PATHS if Path(p).exists()), None)
    family = "Helvetica"
    if font:
        try:
            pdf.add_font("Body", "", font)
            pdf.add_font("Body", "B", font)
            pdf.add_font("Body", "I", font)
            family = "Body"
        except Exception:  # noqa: BLE001 - fall back to a core font
            family = "Helvetica"
    if family == "Helvetica":
        for a, b in LATIN1_FIX.items():
            html = html.replace(a, b)
        html = html.encode("latin-1", "replace").decode("latin-1")
    pdf.add_page()
    pdf.set_font(family, size=10)
    ink = (22, 25, 29)
    styles = {
        "h1": FontFace(color=ink, size_pt=18, emphasis="BOLD"),
        "h2": FontFace(color=(0, 90, 100), size_pt=13, emphasis="BOLD"),
        "h3": FontFace(color=ink, size_pt=11, emphasis="BOLD"),
        "a": FontFace(color=(0, 114, 127)),
    }
    try:
        pdf.write_html(html, font_family=family, table_line_separators=True, tag_styles=styles)
    except TypeError:  # older fpdf2 without tag_styles
        pdf.write_html(html, font_family=family, table_line_separators=True)
    return bytes(pdf.output())
