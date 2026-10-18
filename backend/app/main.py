"""FastAPI app: auth, dataset upload, supplier data, weights, compare, chat, research, memo."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import compare as cmp
from . import descriptions, index_model
from . import weights as wmod
from .auth import COOKIE_NAME, current_user, make_session, read_session, users
from .config import settings
from .dataset import Dataset, DatasetError, category_label, registry

app = FastAPI(title="Supplier Compass", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=2048)

PUBLIC_API = {"/api/login"}


@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    request.state.user = read_session(request.cookies.get(COOKIE_NAME))
    if path.startswith("/api") and path not in PUBLIC_API and not request.state.user:
        return JSONResponse({"detail": "Not logged in"}, status_code=401)
    response = await call_next(request)
    if path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# --------------------------------------------------------------------------- auth


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


@app.post("/api/login")
def login(body: Login):
    if not users.verify(body.username, body.password):
        raise HTTPException(401, "Wrong user name or password")
    resp = JSONResponse({"user": body.username})
    resp.set_cookie(
        COOKIE_NAME, make_session(body.username), max_age=settings.session_max_age, httponly=True,
        samesite="lax", secure=settings.cookie_secure, path="/",
    )
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
def me(user: str = Depends(current_user)):
    from . import llm, search

    return {"user": user, "mock_llm": llm.is_mock(), "mock_search": search.is_mock(), "model": llm.model_name()}


# --------------------------------------------------------------------------- dataset


def dataset_for(user: str = Depends(current_user)) -> Dataset:
    ds = registry.get(user)
    if ds is None:
        raise HTTPException(409, "No dataset loaded. Upload one first.")
    return ds


def _public_meta(meta: dict) -> dict:
    out = {k: v for k, v in meta.items() if k != "descriptions"}
    d = meta.get("descriptions", {})
    out["descriptions"] = {"source": d.get("source"), "builtin": d.get("builtin"), "terms": len(d.get("entries", {}))}
    return out


@app.get("/api/dataset")
def dataset_info(user: str = Depends(current_user)):
    ds = registry.get(user)
    if ds is None:
        return {"loaded": False}
    meta = _public_meta(ds.meta)
    meta["loaded"] = True
    meta["presets"] = wmod.presets_for(ds)
    meta["categories"] = [
        {"column": c, "original": ds.original(c), "label": category_label(c), "weight_pct": int(w)}
        for c, w in zip(ds.score_cols, ds.weights)
    ]
    meta["mismatch_model"] = ds.mismatch_model
    return meta


@app.get("/api/dataset/descriptions")
def dataset_descriptions(ds: Dataset = Depends(dataset_for)):
    d = ds.meta["descriptions"]
    return {"source": d.get("source"), "builtin": d.get("builtin"), "text": d.get("text", "")}


def _accept(user: str, csv_path: Path, file_name: str, md: dict, replace: bool) -> dict:
    if registry.get(user) is not None and not replace:
        raise HTTPException(409, "A dataset is already loaded. Confirm replacing it.")
    try:
        meta = registry.replace(user, csv_path, file_name, md)
    except DatasetError as exc:
        return JSONResponse({"accepted": False, "error": str(exc), "report": exc.report}, status_code=422)
    _engines.pop(user, None)
    return {"accepted": True, "meta": _public_meta(meta)}


@app.post("/api/dataset/upload")
async def upload(
    request: Request,
    csv: UploadFile = File(...),
    descriptions_md: UploadFile | None = File(None),
    replace: bool = Form(False),
    user: str = Depends(current_user),
):
    length = request.headers.get("content-length")
    if length and int(length) > settings.max_upload_bytes + 1024 * 1024:
        raise HTTPException(413, "The upload is larger than 50 MB.")
    tmpdir = Path(tempfile.mkdtemp(prefix="upload-", dir=registry.user_dir(user)))
    try:
        csv_path = tmpdir / "upload.csv"
        size = 0
        with csv_path.open("wb") as fh:
            while chunk := await csv.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "The CSV is larger than 50 MB.")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(422, "The CSV file is empty.")
        if descriptions_md is not None and descriptions_md.filename:
            raw = await descriptions_md.read(descriptions.MAX_MD_BYTES + 1)
            md = descriptions.from_upload(raw, _clean_name(descriptions_md.filename))
            if not md["entries"]:
                md = descriptions.builtin()
                md["source"] += " (the uploaded Markdown had no '- **Term:** description' items)"
        else:
            md = descriptions.builtin()
        return _accept(user, csv_path, _clean_name(csv.filename or "upload.csv"), md, replace)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/dataset/sample")
def load_sample(replace: bool = Body(False, embed=True), user: str = Depends(current_user)):
    path = settings.sample_dir / "supplier_risk_dataset.csv"
    if not path.exists():
        raise HTTPException(404, "The challenge sample is not bundled in this build.")
    md = descriptions.builtin()
    return _accept(user, path, "supplier_risk_dataset.csv (challenge sample)", md, replace)


@app.delete("/api/dataset")
def delete_dataset(user: str = Depends(current_user)):
    registry.clear(user)
    _engines.pop(user, None)
    return {"ok": True}


def _clean_name(name: str) -> str:
    return Path(name).name[:200]


# --------------------------------------------------------------------------- suppliers


@app.get("/api/suppliers")
def suppliers(ds: Dataset = Depends(dataset_for)):
    """All suppliers in columnar form; the browser filters and sorts these locally."""
    levels = [b["level"] for b in ds.bands]
    return {
        "ids": ds.ids.tolist(),
        "names": ds.names.tolist(),
        "index": ds.index.tolist(),
        "level": [levels.index(index_model.level_of(v, ds.bands)) for v in ds.index],
        "official_rank": ds.official_rank.tolist(),
        "scores": ds.scores.astype(int).tolist() if np.all(ds.scores % 1 == 0) else ds.scores.tolist(),
        "categories": [
            {"column": c, "original": ds.original(c), "label": category_label(c), "weight_pct": int(w)}
            for c, w in zip(ds.score_cols, ds.weights)
        ],
        "metrics": {c: [None if np.isnan(v) else round(float(v), 2) for v in arr] for c, arr in ds.metrics.items()},
        "metric_labels": {c: ds.original(c) for c in ds.metrics},
        "sourcing": ds.text.get("sourcing_risk_level", np.array([])).tolist() or None,
        "complexity": ds.text.get("supply_chain_complexity", np.array([])).tolist() or None,
        "exposure_list": ds.exposure_flag.astype(int).tolist(),
        "exposure_eur": None if ds.exposure is None else np.round(ds.exposure, 0).tolist(),
        "mismatch": ds.mismatch.astype(int).tolist(),
        "residual": [None if np.isnan(v) else round(float(v), 2) for v in ds.residual],
        "bands": ds.bands,
        "features": {k: v["enabled"] for k, v in ds.meta["features"].items()},
        "exposure_rule": ds.meta.get("exposure_rule"),
    }


@app.get("/api/suppliers/{sid}")
def supplier_detail(sid: str, ds: Dataset = Depends(dataset_for)):
    try:
        return ds.detail(sid)
    except KeyError:
        raise HTTPException(404, f"No supplier {sid}")


# --------------------------------------------------------------------------- weights & compare


class WeightsBody(BaseModel):
    weights: dict[str, float] | None = None


@app.get("/api/presets")
def presets(ds: Dataset = Depends(dataset_for)):
    return wmod.presets_for(ds)


@app.post("/api/custom-index")
def custom_index(body: WeightsBody, ds: Dataset = Depends(dataset_for)):
    try:
        res = wmod.custom_index(ds, body.weights or {})
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {
        "weights_pct": res["weights_pct"],
        "official": wmod.is_official(ds, body.weights),
        "custom_index": res["custom_index"].tolist(),
        "custom_rank": res["custom_rank"].tolist(),
        "rank_change": res["rank_change"].tolist(),
    }


class CompareBody(BaseModel):
    ids: list[str] = Field(max_length=cmp.MAX_COMPARE)
    weights: dict[str, float] | None = None


@app.post("/api/compare")
def compare(body: CompareBody, ds: Dataset = Depends(dataset_for)):
    try:
        return cmp.compare(ds, body.ids, body.weights)
    except KeyError as exc:
        raise HTTPException(404, f"No supplier {exc.args[0]}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class WhyBody(BaseModel):
    a: str
    b: str
    weights: dict[str, float] | None = None


@app.post("/api/why")
def why(body: WhyBody, ds: Dataset = Depends(dataset_for)):
    try:
        return cmp.why(ds, body.a, body.b, body.weights)
    except KeyError as exc:
        raise HTTPException(404, f"No supplier {exc.args[0]}")


# --------------------------------------------------------------------------- query engine (chat SQL)

_engines: dict[str, object] = {}


def engine_for(user: str, ds: Dataset):
    from .sqlguard import QueryEngine

    key = (user, ds.meta["uploaded_at"])
    eng = _engines.get(user)
    if eng is None or eng[0] != key:
        eng = (key, QueryEngine(str(ds.db_path)))
        _engines[user] = eng
    return eng[1]


# --------------------------------------------------------------------------- static frontend


@app.get("/healthz")
def healthz():
    return {"ok": True}


def mount_frontend() -> None:
    static = settings.static_dir
    if not static.exists():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (static / path).resolve()
        if path and target.is_file() and static.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})


from . import routes_ai  # noqa: E402,F401  (chat, research, memo)

mount_frontend()
