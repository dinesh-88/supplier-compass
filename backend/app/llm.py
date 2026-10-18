"""OpenAI-compatible chat client (default: Nemotron on Nebius Token Factory), with tool calling."""

from __future__ import annotations

import json
import re
import uuid

import httpx

from .config import settings

class LLMError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.llm_api_key)


def model_name(fast: bool = False) -> str:
    return settings.fast_model if fast else settings.llm_model


_TOOLCALL_RE = re.compile(r"<TOOLCALL>\s*(\[.*?\])\s*</TOOLCALL>", re.S)
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def chat(messages: list[dict], tools: list[dict] | None = None, fast: bool = False, temperature: float = 0.2,
         max_tokens: int = 1500, json_mode: bool = False, timeout: float = 90.0) -> dict:
    """One completion. Returns {"content": str, "tool_calls": [{"id","name","arguments"}]}."""
    if not configured():
        raise LLMError("LLM_API_KEY is not set")
    body: dict = {
        "model": model_name(fast),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        resp = httpx.post(url, json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {settings.llm_api_key}"})
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    if resp.status_code >= 400 and json_mode:
        body.pop("response_format")
        resp = httpx.post(url, json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {settings.llm_api_key}"})
    if resp.status_code >= 400:
        raise LLMError(f"LLM returned {resp.status_code}: {resp.text[:300]}")
    msg = resp.json()["choices"][0]["message"]
    content = _THINK_RE.sub("", msg.get("content") or "").strip()
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        calls.append({"id": tc.get("id") or uuid.uuid4().hex[:12], "name": fn.get("name"),
                      "arguments": _loads(fn.get("arguments"))})
    if not calls:
        # Some Nemotron builds emit tool calls inline: <TOOLCALL>[{"name":..,"arguments":{..}}]</TOOLCALL>
        m = _TOOLCALL_RE.search(content)
        if m:
            for tc in _loads(m.group(1)) or []:
                if isinstance(tc, dict) and tc.get("name"):
                    calls.append({"id": uuid.uuid4().hex[:12], "name": tc["name"],
                                  "arguments": tc.get("arguments") or {}})
            content = _TOOLCALL_RE.sub("", content).strip()
    return {"content": content, "tool_calls": calls}


def complete_json(system: str, user: str, fast: bool = True, max_tokens: int = 1500) -> dict | list | None:
    """Ask for a JSON answer; returns None if the model does not produce valid JSON."""
    out = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], fast=fast,
               json_mode=True, max_tokens=max_tokens, temperature=0.1)
    return extract_json(out["content"])


def extract_json(text: str):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1], text[text.find("["): text.rfind("]") + 1]):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _loads(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
