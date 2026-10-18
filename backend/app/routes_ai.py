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
