"""
Веб-бэкенд: чат с RAG и внешней LLM по API.
POST /chat — подмешивает результаты поиска в контекст LLM и возвращает ответ.
GET / — чат-интерфейс.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from backend.prompts import SYSTEM_PROMPT_TEMPLATE
from rag.search import search as rag_search

# Конфиг LLM из env
LLM_API_BASE_URL = os.environ.get("LLM_API_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

app = FastAPI(title="RAG Chat API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


def _get_openai_client() -> Any:
    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Установите пакет openai: pip install openai",
        )
    client_kw: dict[str, Any] = {}
    if LLM_API_BASE_URL:
        client_kw["base_url"] = LLM_API_BASE_URL
    if LLM_API_KEY:
        client_kw["api_key"] = LLM_API_KEY
    return OpenAI(**client_kw)


def _call_llm(system_content: str, user_message: str) -> str:
    """Вызов OpenAI-совместимого Chat API."""
    client = _get_openai_client()
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
    )
    choice = response.choices[0] if response.choices else None
    if not choice or not getattr(choice, "message", None):
        raise HTTPException(status_code=502, detail="Пустой ответ от LLM")
    return (choice.message.content or "").strip()


def _stream_llm(system_content: str, user_message: str):
    """Стриминг ответа LLM (SSE: data: {"delta": "..."})."""
    client = _get_openai_client()
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]
    stream = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and getattr(delta, "content", None):
            yield f"data: {json.dumps({'delta': delta.content}, ensure_ascii=False)}\n\n"


# Заключительные фразы-шаблоны (удаляем перед отдачей, чтобы ответ был в стиле Cursor)
_FILLER_STARTS = (
    "Таким образом",
    "Теперь вы можете",
    "Дополнительную информацию",
    "После этого",
    "Вы также можете",
)


def _clean_reply(reply: str) -> str:
    """Убирает заключительные шаблонные фразы перед блоком «Источники»."""
    if "Источники:" not in reply and "Источник:" not in reply:
        return reply
    parts = reply.split("Источники:", 1)
    if len(parts) != 2:
        parts = reply.split("Источник:", 1)
    if len(parts) != 2:
        return reply
    before, sources_block = parts[0].strip(), "Источники:" + parts[1]
    paragraphs = [p.strip() for p in before.split("\n\n") if p.strip()]
    while paragraphs:
        last = paragraphs[-1]
        if any(last.startswith(phrase) for phrase in _FILLER_STARTS):
            paragraphs.pop()
        else:
            break
    cleaned_before = "\n\n".join(paragraphs)
    return (cleaned_before + "\n\n" + sources_block.strip()).strip()


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Укажите message")
    rag_text = rag_search(message)
    system_content = SYSTEM_PROMPT_TEMPLATE.replace("{{RAG_CONTEXT}}", rag_text)
    try:
        reply = _call_llm(system_content, message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка вызова LLM: {e}")
    reply = _clean_reply(reply)
    return ChatResponse(reply=reply)


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Стриминг ответа (SSE). Для плавного появления текста в чате."""
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Укажите message")
    rag_text = rag_search(message)
    system_content = SYSTEM_PROMPT_TEMPLATE.replace("{{RAG_CONTEXT}}", rag_text)

    def generate() -> Any:
        try:
            for chunk in _stream_llm(system_content, message):
                yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def index() -> FileResponse:
    """Чат-интерфейс."""
    index_html = _STATIC_DIR / "index.html"
    if not index_html.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_html)
