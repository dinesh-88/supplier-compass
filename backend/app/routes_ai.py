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
