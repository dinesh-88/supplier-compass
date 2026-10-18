"""Column descriptions (from the uploaded Markdown or the built-in copy) and the everyday-term glossary."""

from __future__ import annotations

import re

from .config import settings
from .dataset import snake

BUILTIN_FILE = settings.sample_dir / "risk_criteria_description.md"
MAX_MD_BYTES = 512 * 1024

ITEM_RE = re.compile(r"^\s*-\s+\*\*(?P<term>[^*]+?):?\*\*:?\s*(?P<desc>.+)$")
SUB_RE = re.compile(r"^\s{2,}-\s+(?P<text>.+)$")

# Everyday words → dataset columns (snake_case). Only columns present in the dataset are used.
GLOSSARY: dict[str, list[str]] = {
    "financial risk": ["financial_health_score", "credit_rating_score"],
    "financial stability": ["financial_health_score", "credit_rating_score"],
    "bankruptcy": ["financial_health_score"],
    "insolvency": ["financial_health_score"],
    "liquidity": ["financial_health_score"],
    "creditworthiness": ["credit_rating_score"],
    "credit": ["credit_rating_score"],
    "legal risk": ["compliance_risk_score"],
    "lawsuits": ["compliance_risk_score"],
    "regulatory risk": ["compliance_risk_score"],
    "compliance": ["compliance_risk_score"],
    "safety": ["safety_incident_score"],
    "accidents": ["safety_incident_score"],
    "quality": ["quality_risk_score"],
    "defects": ["quality_risk_score"],
    "recalls": ["quality_risk_score"],
    "operational risk": ["operational_resilience_score"],
    "production risk": ["operational_resilience_score"],
    "delivery risk": ["supplier_delivery_rating", "operational_resilience_score"],
    "delivery": ["supplier_delivery_rating", "order_confirmation_rate"],
    "reliability": ["supplier_delivery_rating", "order_confirmation_rate", "operational_resilience_score"],
    "reputation": ["media_sentiment_score", "market_sentiment_score"],
    "reputational risk": ["media_sentiment_score", "market_sentiment_score"],
    "news": ["media_sentiment_score"],
    "esg": ["esg_performance_score", "governance_risk_score", "environmental_exposure_score"],
    "sustainability": ["esg_performance_score"],
    "governance": ["governance_risk_score", "esg_performance_score"],
    "ethics": ["governance_risk_score"],
    "cyber risk": ["digital_security_score"],
    "cyber": ["digital_security_score"],
    "it security": ["digital_security_score"],
    "data breach": ["digital_security_score"],
    "country risk": ["geopolitical_risk_score", "political_stability_score"],
    "geopolitical": ["geopolitical_risk_score", "political_stability_score"],
    "political risk": ["political_stability_score", "geopolitical_risk_score"],
    "natural disasters": ["environmental_exposure_score"],
    "climate risk": ["environmental_exposure_score"],
    "strikes": ["labor_stability_score"],
    "labour risk": ["labor_stability_score"],
    "labor risk": ["labor_stability_score"],
    "sub-tier risk": ["sub_tier_visibility_score"],
    "supply chain visibility": ["sub_tier_visibility_score"],
    "tier-n": ["sub_tier_visibility_score"],
    "peer comparison": ["industry_benchmark_score"],
    "benchmark": ["industry_benchmark_score"],
    "third-party intelligence": ["external_intelligence_score"],
    "spend": ["purchase_order_volume_eur"],
    "exposure": ["purchase_order_volume_eur", "total_risk_index"],
    "replaceability": ["sourcing_risk_level"],
    "dependency": ["sourcing_risk_level"],
    "complexity": ["supply_chain_complexity"],
    "overall risk": ["total_risk_index"],
}


def parse_markdown(text: str) -> dict[str, dict]:
    """Extract "- **Term:** description" items (and indented sub-bullets) keyed by snake_case column name."""
    entries: dict[str, dict] = {}
    current: str | None = None
    for line in text.splitlines():
        m = ITEM_RE.match(line)
        if m:
            term = m.group("term").strip().rstrip(":")
            key = snake(term)
            entries[key] = {"term": term, "description": m.group("desc").strip()}
            current = key
            continue
        sub = SUB_RE.match(line)
        if sub and current:
            entries[current]["description"] += " " + sub.group("text").strip()
            continue
        if line.strip() and not line.startswith(" "):
            current = None
    note = re.search(r"\*\*Note:\*\*\s*(.+)", text)
    if note:
        entries["_note"] = {"term": "Note", "description": note.group(1).strip()}
    return entries


def builtin() -> dict:
    text = BUILTIN_FILE.read_text(encoding="utf-8") if BUILTIN_FILE.exists() else ""
    return {"source": "built-in copy of the challenge's risk_criteria_description.md", "builtin": True,
            "text": text, "entries": parse_markdown(text)}


def from_upload(raw: bytes, file_name: str) -> dict:
    text = raw[:MAX_MD_BYTES].decode("utf-8", errors="replace")
    entries = parse_markdown(text)
    return {"source": f"uploaded file {file_name}", "builtin": False, "text": text, "entries": entries}


def define(term: str, descriptions: dict, columns: list[str], weights: dict[str, int]) -> dict:
    """Look a term up as a column name first, then in the glossary."""
    t = term.strip().lower()
    key = snake(term)
    entries = descriptions.get("entries", {})
    hits: list[str] = []
    for cand in (key, f"{key}_score", key.removesuffix("_score")):
        if cand in columns:
            hits = [cand]
            break
    glossary_term = None
    if not hits:
        for g in sorted(GLOSSARY, key=len, reverse=True):
            if g == t or re.search(rf"\b{re.escape(g)}\b", t):
                glossary_term = g
                hits = [c for c in GLOSSARY[g] if c in columns]
                break
    if not hits:
        partial = [c for c in columns if key and key in c]
        hits = partial[:3]

    defs = []
    for col in hits:
        e = entries.get(col) or entries.get(col.removesuffix("_score")) or {}
        defs.append(
            {
                "column": col,
                "definition": e.get("description", "No description in the descriptions file."),
                "index_weight_pct": weights.get(col),
            }
        )
    out = {
        "term": term,
        "glossary_term": glossary_term,
        "columns": hits,
        "definitions": defs,
        "source": descriptions.get("source"),
        "scale_note": entries.get("_note", {}).get("description"),
    }
    if len(hits) > 1:
        ws = [weights.get(c) for c in hits]
        out["ambiguous"] = True
        out["guidance"] = (
            "This term maps to several columns. Report each column separately, say where they disagree, "
            "and if you combine them use the index weights"
            + (f" ({':'.join(str(w) for w in ws)})" if all(ws) else "")
            + "."
        )
    if not hits:
        out["guidance"] = "No column matches this term. Say so instead of guessing."
    return out
