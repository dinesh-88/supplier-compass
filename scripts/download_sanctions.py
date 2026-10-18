#!/usr/bin/env python3
"""Download the OFAC SDN list and the EU consolidated sanctions list and cache them as one JSON file.

Run at build time (the Dockerfile does) or by hand:  python scripts/download_sanctions.py [out_dir]
Only the standard library is used. A list that fails to download is recorded as unavailable;
the app then says the check could not be run against that list.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OFAC_SDN = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_ALT = "https://www.treasury.gov/ofac/downloads/alt.csv"
EU_CSV = "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
OFAC_ENTRY_URL = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id={id}"
EU_ENTRY_URL = "https://webgate.ec.europa.eu/fsd/fsf#!/files"

csv.field_size_limit(10_000_000)


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "supplier-compass/1.0 (sanctions cache)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean(v: str | None) -> str:
    v = (v or "").strip()
    return "" if v == "-0-" else v


def ofac() -> list[dict]:
    sdn = fetch(OFAC_SDN).decode("latin-1")
    alt = fetch(OFAC_ALT).decode("latin-1")
    aliases: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(alt)):
        if len(row) >= 4 and clean(row[3]):
            aliases.setdefault(row[0].strip(), []).append(clean(row[3]))
    out = []
    for row in csv.reader(io.StringIO(sdn)):
        if len(row) < 4 or not clean(row[1]):
            continue
        ent = row[0].strip()
        out.append({
            "list": "OFAC SDN",
            "id": ent,
            "name": clean(row[1]),
            "aliases": aliases.get(ent, []),
            "type": clean(row[2]) or "entity",
            "programs": clean(row[3]),
            "remarks": clean(row[11]) if len(row) > 11 else "",
            "url": OFAC_ENTRY_URL.format(id=ent),
        })
    return out


def eu() -> list[dict]:
    raw = fetch(EU_CSV).decode("utf-8-sig", errors="replace")
    entries: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(raw), delimiter=";"):
        lid = (row.get("Entity_LogicalId") or "").strip()
        name = (row.get("NameAlias_WholeName") or "").strip()
        if not lid or not name:
            continue
        e = entries.setdefault(lid, {
            "list": "EU consolidated",
            "id": lid,
            "name": name,
            "aliases": [],
            "type": (row.get("Entity_SubjectType") or "").strip() or "entity",
            "programs": (row.get("Entity_Regulation_Programme") or "").strip(),
            "remarks": (row.get("Entity_EU_ReferenceNumber") or "").strip(),
            "country": (row.get("Address_CountryDescription") or "").strip(),
            "url": (row.get("Entity_Regulation_PublicationUrl") or "").strip() or EU_ENTRY_URL,
        })
        if name != e["name"] and name not in e["aliases"]:
            e["aliases"].append(name)
    return list(entries.values())


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "sanctions"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sources, entries = [], []
    for name, url, fn in (("OFAC SDN", OFAC_SDN, ofac), ("EU consolidated", EU_CSV, eu)):
        try:
            items = fn()
            entries.extend(items)
            sources.append({"list": name, "url": url, "downloaded_at": now, "entries": len(items), "available": True})
            print(f"{name}: {len(items)} entries")
        except Exception as exc:  # noqa: BLE001 - record and continue
            sources.append({"list": name, "url": url, "downloaded_at": now, "entries": 0, "available": False,
                            "error": str(exc)[:200]})
            print(f"{name}: FAILED ({exc})", file=sys.stderr)
    target = out_dir / "sanctions.json"
    target.write_text(json.dumps({"generated_at": now, "sources": sources, "entries": entries}), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
