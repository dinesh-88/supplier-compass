"""Per-user supplier dataset: validated CSV load into DuckDB, plus derived fields.

Cell values never reach SQL text: the file path is a bound parameter and column names are
sanitised to [a-z0-9_] before they are used as identifiers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

from . import index_model
from .config import settings

ID_COL = "supplier_id"
INDEX_COL = "total_risk_index"

# Optional columns the app knows how to use, keyed by snake_case name.
KNOWN_NUMERIC = {
    "purchase_order_volume_eur": "spend",
    "order_change_rate": "change_rate",
    "supplier_delivery_rating": "delivery",
    "order_confirmation_rate": "confirmation",
}
KNOWN_TEXT = {
    "supplier_name": "name",
    "sourcing_risk_level": "sourcing",
    "supply_chain_complexity": "complexity",
}
FEATURES = {
    "spend": ("purchase_order_volume_eur",),
    "exposure": ("purchase_order_volume_eur",),
    "delivery": ("supplier_delivery_rating",),
    "confirmation": ("order_confirmation_rate",),
    "change_rate": ("order_change_rate",),
    "sourcing": ("sourcing_risk_level",),
    "complexity": ("supply_chain_complexity",),
    "mismatch": ("supplier_delivery_rating", "operational_resilience_score", "quality_risk_score"),
}
FEATURE_LABELS = {
    "spend": "Spend filter and spend column",
    "exposure": "Exposure (index × spend) and the exposure list",
    "delivery": "Delivery rating filter",
    "confirmation": "Confirmation rate filter",
    "change_rate": "Order change rate filter",
    "sourcing": "Sourcing Risk Level filter",
    "complexity": "Supply Chain Complexity filter",
    "mismatch": "“Delivery record doesn't match risk scores” flag",
}


class DatasetError(Exception):
    """Raised when an upload cannot be accepted; carries the validation report."""

    def __init__(self, message: str, report: dict | None = None):
        super().__init__(message)
        self.report = report or {"errors": [message]}


def snake(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "c_" + s
    return s


def qi(identifier: str) -> str:
    """Quote an identifier (original CSV header) for DuckDB."""
    return '"' + identifier.replace('"', '""') + '"'


def category_label(score_col: str) -> str:
    return score_col.removesuffix("_score").replace("_", " ").title().replace("Esg", "ESG")


def _with_timeout(con: duckdb.DuckDBPyConnection, seconds: float, fn):
    timer = threading.Timer(seconds, con.interrupt)
    timer.start()
    try:
        return fn()
    except duckdb.InterruptException as exc:
        raise DatasetError(f"Parsing took longer than {seconds:.0f} s and was stopped.") from exc
    finally:
        timer.cancel()


# --------------------------------------------------------------------------- loading


def build_database(csv_path: Path, db_path: Path, file_name: str, descriptions: dict) -> dict:
    """Validate the CSV and write a fresh DuckDB file. Returns the metadata (incl. report)."""
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        meta = _load(con, csv_path, file_name, descriptions)
    except Exception:
        con.close()
        db_path.unlink(missing_ok=True)
        raise
    con.close()
    return meta


def _load(con: duckdb.DuckDBPyConnection, csv_path: Path, file_name: str, descriptions: dict) -> dict:
    report: dict = {"errors": [], "warnings": [], "notices": []}

    def read():
        con.execute(
            "CREATE TEMP TABLE raw AS SELECT row_number() OVER () AS __row, * FROM "
            "read_csv(?, all_varchar = true, header = true, sample_size = -1, "
            "ignore_errors = true, store_rejects = true)",
            [str(csv_path)],
        )
        return con.execute("SELECT count(*) FROM reject_errors").fetchone()[0]

    try:
        rejected_lines = _with_timeout(con, settings.load_timeout_s, read)
    except duckdb.Error as exc:
        raise DatasetError(f"Could not read the file as CSV: {str(exc).splitlines()[0]}") from exc

    headers = [r[0] for r in con.execute("DESCRIBE raw").fetchall() if r[0] != "__row"]
    total_rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]

    # Map original headers to unique snake_case names.
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for h in headers:
        base = snake(h)
        name, i = base, 2
        while name in used:
            name, i = f"{base}_{i}", i + 1
        used.add(name)
        mapping[h] = name
    by_snake = {v: k for k, v in mapping.items()}

    score_cols = [s for s in mapping.values() if s.endswith("_score")]
    missing_required = []
    if ID_COL not in by_snake:
        missing_required.append("supplierID")
    if INDEX_COL not in by_snake:
        missing_required.append("Total_Risk_Index")
    if not score_cols:
        missing_required.append("at least one *_Score column")
    if missing_required:
        report["errors"].append("Missing required columns: " + ", ".join(missing_required))
    if total_rows == 0:
        report["errors"].append("The file has no data rows.")
    if report["errors"]:
        report.update(columns=headers, rows_in_file=total_rows)
        raise DatasetError(report["errors"][0], report)

    numeric_cols = [INDEX_COL] + score_cols
    level_cols = {}
    for s in [INDEX_COL] + score_cols:
        for cand in (f"{s}_level", f"{s.removesuffix('_score')}_level"):
            if cand in by_snake and cand not in level_cols.values():
                level_cols[s] = cand
                break
    optional_numeric = [c for c in KNOWN_NUMERIC if c in by_snake]
    known = {ID_COL, *numeric_cols, *level_cols.values(), *optional_numeric, *[c for c in KNOWN_TEXT if c in by_snake]}
    extra = [by_snake[s] for s in mapping.values() if s not in known]

    def num(col: str) -> str:
        return f"TRY_CAST(replace(replace(trim({qi(by_snake[col])}), '%', ''), ',', '') AS DOUBLE)"

    def blank(col: str) -> str:
        c = qi(by_snake[col])
        return f"({c} IS NULL OR trim({c}) = '')"

    # Missing values per column.
    missing_expr = ", ".join(f"count(*) FILTER (WHERE {blank(mapping[h])})" for h in headers)
    missing_counts = con.execute(f"SELECT {missing_expr} FROM raw").fetchone()
    missing = {h: int(n) for h, n in zip(headers, missing_counts) if n}

    # Row-level reasons for dropping.
    idc = qi(by_snake[ID_COL])
    reasons = [
        f"CASE WHEN {blank(ID_COL)} THEN 'missing supplierID' END",
        f"CASE WHEN NOT {blank(ID_COL)} AND row_number() OVER (PARTITION BY trim({idc}) ORDER BY __row) > 1 "
        f"THEN 'duplicate supplierID (first occurrence kept)' END",
    ]
    for col in numeric_cols:
        label = by_snake[col].replace("'", "''")
        reasons.append(f"CASE WHEN {blank(col)} THEN '{label}: missing' END")
        reasons.append(f"CASE WHEN NOT {blank(col)} AND {num(col)} IS NULL THEN '{label}: not a number' END")
        reasons.append(
            f"CASE WHEN {num(col)} IS NOT NULL AND ({num(col)} < 0 OR {num(col)} > 100) THEN '{label}: outside 0–100' END"
        )
    con.execute(
        "CREATE TEMP TABLE row_reasons AS SELECT __row, trim(" + idc + ") AS sid, "
        "list_filter([" + ", ".join(reasons) + "], x -> x IS NOT NULL) AS reasons FROM raw"
    )
    dropped_rows = con.execute(
        "SELECT __row, sid, reasons FROM row_reasons WHERE len(reasons) > 0 ORDER BY __row"
    ).fetchall()
    by_reason: dict[str, dict] = {}
    for row_no, sid, rs in dropped_rows:
        for r in rs:
            entry = by_reason.setdefault(r, {"reason": r, "count": 0, "examples": []})
            entry["count"] += 1
            if len(entry["examples"]) < 5:
                entry["examples"].append({"row": int(row_no) + 1, "supplierID": sid})

    kept = total_rows - len(dropped_rows)
    if kept == 0:
        report["errors"].append("Every row failed validation, so nothing could be loaded.")
        report.update(
            columns=headers, rows_in_file=total_rows, dropped=list(by_reason.values()), missing=missing
        )
        raise DatasetError(report["errors"][0], report)

    # Typed table with snake_case names.
    select = [f"trim({idc}) AS {ID_COL}"]
    for col in numeric_cols + optional_numeric:
        select.append(f"{num(col)} AS {col}")
    for col in by_snake:
        if col in (ID_COL, *numeric_cols, *optional_numeric):
            continue
        select.append(f"nullif(trim({qi(by_snake[col])}), '') AS {col}")
    con.execute(
        "CREATE TABLE suppliers AS SELECT " + ", ".join(select) + " FROM raw "
        "WHERE __row IN (SELECT __row FROM row_reasons WHERE len(reasons) = 0) ORDER BY __row"
    )
    bad_optional = {}
    for col in optional_numeric:
        n = con.execute(
            f"SELECT count(*) FROM raw WHERE NOT {blank(col)} AND {num(col)} IS NULL"
        ).fetchone()[0]
        if n:
            bad_optional[by_snake[col]] = int(n)
            report["warnings"].append(f"{by_snake[col]}: {n} non-numeric values were treated as missing.")

    # Index formula and level bands, inferred from what was loaded.
    arr = con.execute(f"SELECT {', '.join(numeric_cols)} FROM suppliers").fetchnumpy()
    scores = np.column_stack([arr[c].astype(float) for c in score_cols])
    index = arr[INDEX_COL].astype(float)
    formula = index_model.infer_formula(scores, index, score_cols)
    pairs = []
    for s, lvl in level_cols.items():
        vals = con.execute(f"SELECT {s}, {lvl} FROM suppliers").fetchall()
        pairs.append((np.array([v[0] for v in vals], float), np.array([v[1] or "" for v in vals], object)))
    bands, band_source = index_model.infer_bands(pairs)

    features = {}
    for feat, cols in FEATURES.items():
        missing_cols = [c for c in cols if c not in by_snake]
        features[feat] = {"enabled": not missing_cols, "label": FEATURE_LABELS[feat], "needs": [
            {"snake": c, "original": by_snake.get(c, _original_guess(c))} for c in missing_cols
        ]}
        if missing_cols:
            report["notices"].append(
                f"{FEATURE_LABELS[feat]} is off: the file has no "
                + ", ".join(_original_guess(c) for c in missing_cols)
                + " column."
            )
    if formula["status"] != "verified":
        report["notices"].append(
            f"The index formula could only be reconstructed approximately (R² = {formula['r2']:.3f}); "
            "index explanations are labelled as approximate."
        )
    if rejected_lines:
        report["warnings"].append(f"{rejected_lines} malformed CSV lines could not be parsed and were skipped.")

    report.update(
        rows_in_file=int(total_rows) + int(rejected_lines),
        rows_loaded=int(kept),
        rows_dropped=len(dropped_rows) + int(rejected_lines),
        malformed_lines=int(rejected_lines),
        dropped=sorted(by_reason.values(), key=lambda e: -e["count"]),
        missing=missing,
        non_numeric_optional=bad_optional,
        columns=headers,
        score_columns=[by_snake[c] for c in score_cols],
        level_columns=[by_snake[c] for c in level_cols.values()],
        optional_present=[by_snake[c] for c in [*optional_numeric, *[c for c in KNOWN_TEXT if c in by_snake]]],
        extra_columns=extra,
    )
    meta = {
        "file_name": file_name,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_count": int(kept),
        "report": report,
        "formula": formula,
        "bands": bands,
        "band_source": band_source,
        "mapping": mapping,
        "score_columns": score_cols,
        "level_columns": level_cols,
        "features": features,
        "descriptions": descriptions,
    }
    con.execute("CREATE TABLE meta (k VARCHAR, v VARCHAR)")
    con.execute("INSERT INTO meta VALUES ('meta', ?)", [json.dumps(meta)])
    con.execute("DROP TABLE raw")
    con.execute("DROP TABLE row_reasons")
    return meta


def _original_guess(snake_name: str) -> str:
    return {
        "purchase_order_volume_eur": "Purchase Order Volume (EUR)",
        "order_change_rate": "Order Change Rate",
        "supplier_delivery_rating": "Supplier Delivery Rating",
        "order_confirmation_rate": "Order Confirmation Rate",
        "sourcing_risk_level": "Sourcing Risk Level",
        "supply_chain_complexity": "Supply Chain Complexity",
        "operational_resilience_score": "Operational_Resilience_Score",
        "quality_risk_score": "Quality_Risk_Score",
    }.get(snake_name, snake_name)


# --------------------------------------------------------------------------- in-memory model


@dataclass
class Dataset:
    meta: dict
    ids: np.ndarray
    names: np.ndarray
    index: np.ndarray
    scores: np.ndarray  # n × k
    score_cols: list[str]
    metrics: dict[str, np.ndarray]
    text: dict[str, np.ndarray]
    db_path: Path
    pos: dict[str, int] = field(default_factory=dict)

    # derived
    weights: np.ndarray = None  # whole percent
    means: np.ndarray = None
    sorted_scores: np.ndarray = None
    sorted_index: np.ndarray = None
    official_rank: np.ndarray = None
    exposure: np.ndarray = None
    exposure_flag: np.ndarray = None
    residual: np.ndarray = None
    mismatch: np.ndarray = None
    mismatch_model: dict = None

    @classmethod
    def open(cls, db_path: Path) -> "Dataset":
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            meta = json.loads(con.execute("SELECT v FROM meta WHERE k = 'meta'").fetchone()[0])
            data = con.execute("SELECT * FROM suppliers").fetchnumpy()
        finally:
            con.close()
        score_cols = meta["score_columns"]
        n = len(data[ID_COL])
        ds = cls(
            meta=meta,
            ids=np.array([str(x) for x in data[ID_COL]], dtype=object),
            names=np.array(
                [str(x) if x is not None else "" for x in data.get("supplier_name", [""] * n)], dtype=object
            ),
            index=np.asarray(data[INDEX_COL], dtype=float),
            scores=np.column_stack([np.asarray(data[c], dtype=float) for c in score_cols]),
            score_cols=score_cols,
            metrics={c: _float_array(data[c]) for c in KNOWN_NUMERIC if c in data},
            text={
                c: np.array([x if x is not None else "" for x in data[c]], dtype=object)
                for c in data
                if c not in KNOWN_NUMERIC and c not in (ID_COL, INDEX_COL, *score_cols)
            },
            db_path=db_path,
        )
        ds._derive()
        return ds

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def bands(self) -> list[dict]:
        return self.meta["bands"]

    @property
    def formula(self) -> dict:
        return self.meta["formula"]

    @property
    def verified(self) -> bool:
        return self.formula["status"] == "verified"

    def feature(self, name: str) -> bool:
        return self.meta["features"][name]["enabled"]

    def original(self, snake_name: str) -> str:
        rev = {v: k for k, v in self.meta["mapping"].items()}
        return rev.get(snake_name, snake_name)

    def _derive(self) -> None:
        self.pos = {sid: i for i, sid in enumerate(self.ids)}
        self.weights = np.array([self.formula["weights"][c] for c in self.score_cols], dtype=float)
        self.means = self.scores.mean(axis=0)
        self.sorted_scores = np.sort(self.scores, axis=0)
        self.sorted_index = np.sort(self.index)
        self.official_rank = competition_rank(self.index)

        spend = self.metrics.get("purchase_order_volume_eur")
        if spend is not None:
            s = np.nan_to_num(spend)
            self.exposure = self.index / 100.0 * s
            top10 = s >= np.quantile(s, 0.9)
            critical_min = next((b["min"] for b in self.bands if b["level"] == "Critical"), self.bands[-1]["min"])
            self.exposure_flag = top10 & (self.index >= critical_min)
            self.meta["exposure_rule"] = {
                "spend_threshold": float(np.quantile(s, 0.9)),
                "index_threshold": critical_min,
            }
        else:
            self.exposure = None
            self.exposure_flag = np.zeros(self.n, dtype=bool)

        if self.feature("mismatch"):
            y = self.metrics["supplier_delivery_rating"]
            x1 = self.scores[:, self.score_cols.index("operational_resilience_score")]
            x2 = self.scores[:, self.score_cols.index("quality_risk_score")]
            ok = ~np.isnan(y)
            X = np.column_stack([np.ones(ok.sum()), x1[ok], x2[ok]])
            coef, *_ = np.linalg.lstsq(X, y[ok], rcond=None)
            resid = np.full(self.n, np.nan)
            resid[ok] = y[ok] - X @ coef
            sd = float(np.nanstd(resid, ddof=3))
            self.residual = resid
            self.mismatch = np.abs(np.nan_to_num(resid)) > 2 * sd
            self.mismatch_model = {
                "intercept": float(coef[0]),
                "operational_resilience": float(coef[1]),
                "quality_risk": float(coef[2]),
                "residual_sd": sd,
                "threshold": 2 * sd,
                "flagged": int(self.mismatch.sum()),
            }
        else:
            self.residual = np.full(self.n, np.nan)
            self.mismatch = np.zeros(self.n, dtype=bool)

    # ---------------------------------------------------------------- per-supplier views

    def percentile(self, col_idx: int | None, value: float) -> float:
        """Share of suppliers scoring below, counting ties as half (0–100)."""
        arr = self.sorted_index if col_idx is None else self.sorted_scores[:, col_idx]
        below = np.searchsorted(arr, value, side="left")
        at_or_below = np.searchsorted(arr, value, side="right")
        return float((below + at_or_below) / 2 / len(arr) * 100)

    def contributions(self, i: int) -> list[dict]:
        out = []
        for k, col in enumerate(self.score_cols):
            w = self.weights[k] / 100.0
            out.append(
                {
                    "column": col,
                    "original": self.original(col),
                    "label": category_label(col),
                    "score": float(self.scores[i, k]),
                    "weight_pct": int(self.weights[k]),
                    "contribution": round(w * self.scores[i, k], 2),
                    "mean_score": round(float(self.means[k]), 2),
                    "points_above_average": round(w * (self.scores[i, k] - self.means[k]), 2),
                    "level": index_model.level_of(self.scores[i, k], self.bands),
                    "percentile": round(self.percentile(k, self.scores[i, k]), 1),
                }
            )
        return out

    def explain(self, sid: str) -> dict:
        i = self.require(sid)
        contrib = self.contributions(i)
        weighted_sum = sum(c["contribution"] for c in contrib)
        mean_index = float(self.index.mean())
        return {
            "supplierID": sid,
            "name": self.names[i],
            "total_risk_index": float(self.index[i]),
            "level": index_model.level_of(self.index[i], self.bands),
            "percentile": round(self.percentile(None, self.index[i]), 1),
            "formula_status": self.formula["status"],
            "formula_label": self.formula["label"],
            "approximate": not self.verified,
            "weighted_sum": round(weighted_sum, 2),
            "average_index": round(mean_index, 2),
            "points_above_average_total": round(weighted_sum - float((self.weights / 100.0) @ self.means), 2),
            "contributions": sorted(contrib, key=lambda c: -c["contribution"]),
            "drivers": sorted(contrib, key=lambda c: -c["points_above_average"]),
            "note": (
                "Exact: the index equals the weighted sum rounded half to even."
                if self.verified
                else f"Approximate: the inferred weights reproduce the index with R² = {self.formula['r2']:.3f}."
            ),
        }

    def require(self, sid: str) -> int:
        sid = str(sid).strip().upper()
        if sid not in self.pos:
            raise KeyError(sid)
        return self.pos[sid]

    def row(self, i: int) -> dict:
        out = {
            "supplierID": self.ids[i],
            "name": self.names[i],
            "total_risk_index": float(self.index[i]),
            "level": index_model.level_of(self.index[i], self.bands),
            "official_rank": int(self.official_rank[i]),
        }
        for k, col in enumerate(self.score_cols):
            out[col] = float(self.scores[i, k])
        for col, arr in self.metrics.items():
            out[col] = None if np.isnan(arr[i]) else float(arr[i])
        for col in ("sourcing_risk_level", "supply_chain_complexity"):
            if col in self.text:
                out[col] = self.text[col][i]
        out["exposure_list"] = bool(self.exposure_flag[i])
        out["delivery_mismatch"] = bool(self.mismatch[i])
        return out

    def detail(self, sid: str) -> dict:
        i = self.require(sid)
        info = self.row(i)
        info.update(self.explain(sid))
        info["index_percentile"] = info["percentile"]
        info["metrics"] = [
            {
                "column": col,
                "original": self.original(col),
                "value": None if np.isnan(arr[i]) else float(arr[i]),
                "percentile": None
                if np.isnan(arr[i])
                else round(float((np.sum(arr < arr[i]) + np.sum(arr <= arr[i])) / 2 / np.sum(~np.isnan(arr)) * 100), 1),
            }
            for col, arr in self.metrics.items()
        ]
        if self.exposure is not None:
            info["exposure_eur"] = round(float(self.exposure[i]), 2)
        info["mismatch"] = self.mismatch_info(i)
        info["levels_in_file"] = {
            self.original(lvl): self.text.get(lvl, np.array([""] * self.n))[i]
            for lvl in self.meta["level_columns"].values()
        }
        return info

    def mismatch_info(self, i: int) -> dict | None:
        if not self.feature("mismatch"):
            return None
        m = self.mismatch_model
        k_op = self.score_cols.index("operational_resilience_score")
        k_q = self.score_cols.index("quality_risk_score")
        expected = m["intercept"] + m["operational_resilience"] * self.scores[i, k_op] + m["quality_risk"] * self.scores[i, k_q]
        actual = self.metrics["supplier_delivery_rating"][i]
        resid = self.residual[i]
        direction = "better" if resid > 0 else "worse"
        return {
            "flagged": bool(self.mismatch[i]),
            "label": "Delivery record doesn't match risk scores",
            "actual_delivery": None if np.isnan(actual) else round(float(actual), 2),
            "expected_delivery": round(float(expected), 2),
            "residual": None if np.isnan(resid) else round(float(resid), 2),
            "threshold": round(m["threshold"], 2),
            "explanation": (
                f"Given its Operational Resilience ({self.scores[i, k_op]:.0f}) and Quality Risk "
                f"({self.scores[i, k_q]:.0f}) scores, suppliers like this deliver about {expected:.1f}% on time. "
                f"This one delivers {actual:.1f}%, {abs(resid):.1f} points {direction} than expected"
                + (
                    f" (more than 2 sd = {m['threshold']:.1f} points)."
                    if self.mismatch[i]
                    else f", within the normal range of ±{m['threshold']:.1f} points."
                )
            ),
            "model": m,
        }


def _float_array(values) -> np.ndarray:
    if hasattr(values, "mask"):
        return np.ma.filled(values.astype(float), np.nan)
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def competition_rank(values: np.ndarray) -> np.ndarray:
    """Rank 1 = lowest risk; ties share the best rank ('1224' ranking)."""
    order = np.sort(values)
    return np.searchsorted(order, values, side="left") + 1


# --------------------------------------------------------------------------- registry


class Registry:
    """Datasets per user, each in its own DuckDB file under DATA_DIR/<user>/."""

    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, Dataset] = {}
        self._lock = threading.Lock()

    def user_dir(self, user: str) -> Path:
        d = self.root / user
        d.mkdir(parents=True, exist_ok=True)
        return d

    def db_path(self, user: str) -> Path:
        return self.user_dir(user) / "dataset.duckdb"

    def get(self, user: str) -> Dataset | None:
        with self._lock:
            if user in self._cache:
                return self._cache[user]
            path = self.db_path(user)
            if not path.exists():
                return None
            ds = Dataset.open(path)
            self._cache[user] = ds
            return ds

    def replace(self, user: str, csv_path: Path, file_name: str, descriptions: dict) -> dict:
        target = self.db_path(user)
        tmp = target.with_suffix(".duckdb.new")
        meta = build_database(csv_path, tmp, file_name, descriptions)
        with self._lock:
            self._cache.pop(user, None)
            os.replace(tmp, target)
            wal = tmp.with_suffix(tmp.suffix + ".wal")
            wal.unlink(missing_ok=True)
        return meta

    def clear(self, user: str) -> None:
        with self._lock:
            self._cache.pop(user, None)
            shutil.rmtree(self.root / user, ignore_errors=True)


registry = Registry(settings.data_dir)
