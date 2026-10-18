"""Fuzzy screening against the cached OFAC SDN and EU consolidated lists. Never reports a confirmed match."""

from __future__ import annotations

import json
import re
import threading
import unicodedata

from rapidfuzz import fuzz, process

from .config import settings

LEGAL_SUFFIXES = {
    "AG", "GMBH", "MBH", "KG", "SE", "LTD", "LIMITED", "INC", "INCORPORATED", "LLC", "LLP", "LP", "CO", "CORP",
    "CORPORATION", "COMPANY", "SA", "SAS", "SARL", "SPA", "SRL", "BV", "NV", "PLC", "OOO", "OAO", "ZAO", "PAO",
    "JSC", "PJSC", "OJSC", "CJSC", "AO", "AB", "AS", "ASA", "OY", "OYJ", "KK", "PTE", "PTY", "BHD", "SDN", "THE",
    "GROUP", "HOLDING", "HOLDINGS", "INTERNATIONAL", "AND", "OF",
}
THRESHOLD = 90

_lock = threading.Lock()
_cache: dict | None = None


def normalise(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)


def _load() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = settings.sanctions_dir / "sanctions.json"
        if not path.exists():
            _cache = {"available": False, "sources": [], "names": [], "refs": [], "generated_at": None}
            return _cache
        data = json.loads(path.read_text(encoding="utf-8"))
        names, refs = [], []
        for k, e in enumerate(data.get("entries", [])):
            for n in [e["name"], *e.get("aliases", [])]:
                norm = normalise(n)
                if len(norm) >= 3:
                    names.append(norm)
                    refs.append((k, n))
        _cache = {
            "available": any(s.get("available") for s in data.get("sources", [])),
            "sources": data.get("sources", []),
            "entries": data.get("entries", []),
            "names": names,
            "refs": refs,
            "generated_at": data.get("generated_at"),
        }
        return _cache


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def check(company: str, limit: int = 5) -> dict:
    db = _load()
    result = {
        "query": company,
        "normalised": normalise(company),
        "lists": [{k: s.get(k) for k in ("list", "entries", "downloaded_at", "available", "url")} for s in db["sources"]],
        "available": db["available"],
        "matches": [],
        "status": "not checked",
        "note": "",
    }
    if not db["available"]:
        result["note"] = "Sanctions lists are not available in this build; run scripts/download_sanctions.py."
        return result
    q = result["normalised"]
    if not q:
        result["status"] = "no match"
        return result
    hits = process.extract(q, db["names"], scorer=fuzz.ratio, limit=50, score_cutoff=THRESHOLD - 10)
    seen = set()
    for _name, score, idx in hits:
        k, original = db["refs"][idx]
        tsr = fuzz.token_sort_ratio(q, db["names"][idx])
        best = max(score, tsr)
        if best < THRESHOLD or k in seen:
            continue
        seen.add(k)
        e = db["entries"][k]
        result["matches"].append({
            "status": "possible match, verify",
            "score": round(best, 1),
            "matched_name": original,
            "list": e["list"],
            "entry_id": e["id"],
            "entry_name": e["name"],
            "type": e.get("type"),
            "programs": e.get("programs"),
            "country": e.get("country", ""),
            "url": e.get("url"),
        })
        if len(result["matches"]) >= limit:
            break
    result["status"] = "possible match, verify" if result["matches"] else "no match"
    result["note"] = (
        "Fuzzy name screening only. A possible match must be verified against the official list entry "
        "(identifiers, addresses, ownership) before any conclusion."
    )
    return result
