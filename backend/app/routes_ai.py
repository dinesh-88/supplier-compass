"""Chat, research and memo routes."""

from __future__ import annotations

from fastapi import Depends
from pydantic import BaseModel, Field

from . import chat as chatmod
from .auth import current_user
from .dataset import Dataset
from .main import app, dataset_for, engine_for


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatBody(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    context_ids: list[str] = Field(default_factory=list, max_length=20)


@app.post("/api/chat")
def chat(body: ChatBody, user: str = Depends(current_user), ds: Dataset = Depends(dataset_for)):
    engine = engine_for(user, ds)
    return chatmod.run_chat(ds, engine, [m.model_dump() for m in body.messages], body.context_ids)


# --------------------------------------------------------------------------- research

import json  # noqa: E402
import re  # noqa: E402

from fastapi import HTTPException, Query  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from . import research as rmod  # noqa: E402
from .dataset import registry  # noqa: E402

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(text: str, n: int) -> str:
    return _CTRL.sub(" ", text or "").strip()[:n]


@app.get("/api/research/stream")
def research_stream(
    company: str = Query(min_length=2, max_length=120),
    country: str = Query("", max_length=60),
    website: str = Query("", max_length=200),
    user: str = Depends(current_user),
):
    agent = rmod.ResearchAgent(_clean(company, 120), _clean(country, 60), _clean(website, 200))
    user_dir = registry.user_dir(user)

    def events():
        try:
            for ev in agent.run():
                if ev["type"] == "report":
                    rmod.save(user_dir, ev["report"])
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - report to the client, then end the stream
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(exc)[:300]})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/research")
def research_list(user: str = Depends(current_user)):
    return rmod.list_reports(registry.user_dir(user))


@app.get("/api/research/{rid}")
def research_get(rid: str, user: str = Depends(current_user)):
    r = rmod.load(registry.user_dir(user), rid)
    if r is None:
        raise HTTPException(404, "No such report")
    return r


@app.delete("/api/research/{rid}")
def research_delete(rid: str, user: str = Depends(current_user)):
    if rmod.load(registry.user_dir(user), rid) is None:
        raise HTTPException(404, "No such report")
    (rmod.reports_dir(registry.user_dir(user)) / f"{rid}.json").unlink(missing_ok=True)
    return {"ok": True}


# --------------------------------------------------------------------------- memo

from fastapi.responses import Response  # noqa: E402

from . import memo as memomod  # noqa: E402


class MemoBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=20)
    weights: dict[str, float] | None = None
    preset_label: str = Field("Custom weights", max_length=80)
    rationale: str = Field("", max_length=2000)
    research_ids: list[str] = Field(default_factory=list, max_length=10)
    title: str = Field("Supplier shortlist memo", max_length=120)


@app.post("/api/memo")
def memo(body: MemoBody, user: str = Depends(current_user), ds: Dataset = Depends(dataset_for)):
    reports = [r for r in (rmod.load(registry.user_dir(user), rid) for rid in body.research_ids) if r]
    try:
        facts = memomod.build_facts(ds, body.ids, body.weights, body.preset_label, reports)
    except KeyError as exc:
        raise HTTPException(404, f"No supplier {exc.args[0]}")
    prose = memomod.write_prose(facts, body.rationale)
    md = memomod.to_markdown(facts, prose, body.rationale, body.title)
    return {"markdown": md, "facts": facts, "prose": prose}


class PdfBody(BaseModel):
    markdown: str = Field(max_length=200_000)
    filename: str = Field("shortlist-memo", max_length=80)


@app.post("/api/memo/pdf")
def memo_pdf(body: PdfBody):
    pdf = memomod.to_pdf(body.markdown)
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", body.filename).strip("-") or "shortlist-memo"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


# --------------------------------------------------------------------------- risk-analysis plugins

from . import plugins  # noqa: E402


@app.get("/api/plugins")
def plugin_list(ds: Dataset = Depends(dataset_for)):
    return [p.describe(ds) for p in plugins.all_plugins()]


class PluginRunBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=20)
    params: dict = Field(default_factory=dict)


@app.post("/api/plugins/{plugin_id}/run")
def plugin_run(plugin_id: str, body: PluginRunBody, ds: Dataset = Depends(dataset_for)):
    try:
        return plugins.run(ds, plugin_id, body.ids, body.params)
    except plugins.PluginError as exc:
        raise HTTPException(422, str(exc))
