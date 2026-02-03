"""
Веб-бэкенд: чат с RAG и внешней LLM по API.
POST /chat — подмешивает результаты поиска в контекст LLM и возвращает ответ.
GET / — чат-интерфейс.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from backend.prompts import SYSTEM_PROMPT_TEMPLATE
from rag.search import search as rag_search

# Algolia Agent Studio: URL приложения https://{APPLICATION_ID}.algolia.net/agent-studio/1/agents/{agent_id}/completions
# Переопределение: ALGOLIA_AGENT_STUDIO_BASE_URL (например https://agent-studio.us.algolia.com для регионального эндпоинта)
ALGOLIA_APP_ID = (os.environ.get("ALGOLIA_APPLICATION_ID") or "").strip()
ALGOLIA_API_KEY = (os.environ.get("ALGOLIA_API_KEY") or "").strip()
ALGOLIA_AGENT_ID = (os.environ.get("ALGOLIA_AGENT_ID") or "1feae05a-7e87-4508-88c8-2d7da88e30de").strip()
ALGOLIA_AGENT_BASE_URL = (
    os.environ.get("ALGOLIA_AGENT_STUDIO_BASE_URL") or ""
).strip().rstrip("/")
if not ALGOLIA_AGENT_BASE_URL and ALGOLIA_APP_ID:
    ALGOLIA_AGENT_BASE_URL = f"https://{ALGOLIA_APP_ID.lower()}.algolia.net/agent-studio"
if not ALGOLIA_AGENT_BASE_URL:
    ALGOLIA_AGENT_BASE_URL = "https://agent-studio.us.algolia.com"

# Конфиг LLM из env (LLM_API_KEY или OPENAI_API_KEY). Читаем при каждом запросе — на случай смены env.
def _get_llm_api_key() -> str:
    return (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()


LLM_API_BASE_URL = os.environ.get("LLM_API_BASE_URL", "").rstrip("/")
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
    backend: str = "qdrant"  # "qdrant" | "algolia"


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
    api_key = _get_llm_api_key()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "Не задан API-ключ LLM. В файле .env на сервере укажите LLM_API_KEY=sk-... или OPENAI_API_KEY=sk-... "
                "(без пробелов вокруг =). Затем перезапустите backend: docker compose up -d --force-recreate backend"
            ),
        )
    client_kw: dict[str, Any] = {"api_key": api_key}
    if LLM_API_BASE_URL:
        client_kw["base_url"] = LLM_API_BASE_URL
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


def _stream_llm_content(system_content: str, user_message: str) -> Iterator[str]:
    """Стриминг ответа LLM: по одному куску текста (delta) за раз."""
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
            yield delta.content


def _algolia_reply(message: str) -> str:
    """One-shot reply from Algolia Agent Studio (no stream)."""
    if not ALGOLIA_APP_ID or not ALGOLIA_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Algolia Agent не настроен. Задайте ALGOLIA_APPLICATION_ID и ALGOLIA_API_KEY в .env на сервере.",
        )
    url = f"{ALGOLIA_AGENT_BASE_URL}/1/agents/{ALGOLIA_AGENT_ID}/completions?stream=false&compatibilityMode=ai-sdk-5"
    payload = {"messages": [{"role": "user", "parts": [{"text": message}]}]}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-algolia-application-id": ALGOLIA_APP_ID,
        "x-algolia-api-key": ALGOLIA_API_KEY,
    }
    with httpx.Client(timeout=90.0) as client:
        resp = client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        body = resp.text
        if body.strip().lower().startswith("<!doctype html>"):
            raise HTTPException(
                status_code=502,
                detail="Algolia вернул HTML (возможно Cloudflare). Используйте ALGOLIA_AGENT_STUDIO_BASE_URL=https://agent-studio.us.algolia.com в .env и перезапустите backend.",
            )
        try:
            err = resp.json()
            msg = err.get("message", body)
        except Exception:
            msg = body or f"HTTP {resp.status_code}"
        if "not found" in msg.lower() and "agent" in msg.lower():
            msg = (
                f"{msg} Проверьте в [Agent Studio](https://dashboard.algolia.com/generativeAi/agent-studio/agents): "
                "агент опубликован и ID совпадает. Задайте актуальный ALGOLIA_AGENT_ID в .env на сервере."
            )
        raise HTTPException(status_code=502, detail=f"Algolia Agent: {msg}")
    data = resp.json()
    parts = data.get("parts") or []
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()


def _algolia_stream(message: str) -> Iterator[str]:
    """Stream reply from Algolia Agent Studio (SSE-like: data lines with text-delta)."""
    if not ALGOLIA_APP_ID or not ALGOLIA_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Algolia Agent не настроен. Задайте ALGOLIA_APPLICATION_ID и ALGOLIA_API_KEY в .env на сервере.",
        )
    url = f"{ALGOLIA_AGENT_BASE_URL}/1/agents/{ALGOLIA_AGENT_ID}/completions?stream=true&compatibilityMode=ai-sdk-5"
    payload = {"messages": [{"role": "user", "parts": [{"text": message}]}]}
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-algolia-application-id": ALGOLIA_APP_ID,
        "x-algolia-api-key": ALGOLIA_API_KEY,
    }
    log = logging.getLogger(__name__)
    with httpx.stream("POST", url, json=payload, headers=headers, timeout=120.0) as resp:
        if resp.status_code != 200:
            body = resp.read().decode("utf-8", errors="replace")
            if body.strip().lower().startswith("<!doctype html>"):
                raise HTTPException(
                    status_code=502,
                    detail="Algolia вернул HTML (Cloudflare). Задайте ALGOLIA_AGENT_STUDIO_BASE_URL=https://agent-studio.us.algolia.com в .env.",
                )
            try:
                err = json.loads(body)
                msg = err.get("message", body)
            except Exception:
                msg = body or f"HTTP {resp.status_code}"
            if "not found" in msg.lower() and "agent" in msg.lower():
                msg = (
                    f"{msg} Укажите актуальный ALGOLIA_AGENT_ID в .env (ID из dashboard.algolia.com → Agent Studio → Agents, опубликованный агент)."
                )
            raise HTTPException(status_code=502, detail=f"Algolia Agent: {msg}")
        first_chunk = True
        yielded = 0
        for line in resp.iter_lines():
            if not line:
                continue
            if first_chunk and (line.strip().lower().startswith("<!doctype") or line.strip().lower().startswith("<html")):
                yield f"data: {json.dumps({'error': 'Algolia вернул HTML (Cloudflare). Попробуйте с другого региона или проверьте настройки агента.'}, ensure_ascii=False)}\n\n"
                return
            first_chunk = False
            if not line.startswith("data: "):
                continue
            raw = line[6:].strip()
            if raw.lower().startswith("<!doctype") or raw.lower().startswith("<html"):
                yield f"data: {json.dumps({'error': 'Algolia вернул HTML (Cloudflare).'}, ensure_ascii=False)}\n\n"
                return
            try:
                obj = json.loads(raw)
                if obj.get("type") == "text-delta" and "delta" in obj:
                    yield f"data: {json.dumps({'delta': obj['delta']}, ensure_ascii=False)}\n\n"
                    yielded += 1
                elif obj.get("type") == "text" and "text" in obj:
                    for c in obj["text"]:
                        yield f"data: {json.dumps({'delta': c}, ensure_ascii=False)}\n\n"
                    yielded += 1
            except (json.JSONDecodeError, KeyError):
                pass
        if yielded == 0:
            log.warning("Algolia stream: 200 OK but no text-delta/text events (url=%s)", url)
            yield f"data: {json.dumps({'error': 'Algolia не вернул текст (пустой стрим). Проверьте агента и индекс в дашборде.'}, ensure_ascii=False)}\n\n"


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


# Минимальная и максимальная длина блока при стриминге в Chatwoot (по абзацам/предложениям)
STREAM_MIN_CHARS = int(os.environ.get("CHATWOOT_STREAM_MIN_CHARS", "120"))
STREAM_MAX_CHARS = int(os.environ.get("CHATWOOT_STREAM_MAX_CHARS", "450"))


def _split_block(buffer: str, min_chars: int, max_chars: int) -> tuple[str, str]:
    """
    Отрезает от buffer один блок: по границе абзаца (\\n\\n) или предложения (. ),
    не меньше min_chars и не больше max_chars. Возвращает (block, remainder).
    """
    if len(buffer) < min_chars:
        return "", buffer
    # Ищем последнюю «хорошую» границу в пределах [min_chars, min(max_chars, len(buffer))]
    end = min(max_chars + 1, len(buffer))
    search = buffer[min_chars:end]
    for sep, shift in (("\n\n", 2), (". ", 2), (".\n", 2), (" ", 1)):
        idx = search.rfind(sep)
        if idx >= 0:
            cut = min_chars + idx + shift
            return buffer[:cut].strip(), buffer[cut:].lstrip()
    # Нет границы — режем по max_chars по последнему пробелу
    chunk = buffer[: max_chars + 1]
    last_space = chunk.rfind(" ")
    if last_space >= min_chars:
        return buffer[:last_space].strip(), buffer[last_space:].lstrip()
    return buffer[:max_chars].strip(), buffer[max_chars:].lstrip()


def stream_rag_reply(message: str) -> Iterator[str]:
    """
    RAG один раз, LLM — потоком; выдаёт блоки текста для постинга в Chatwoot.
    Используется при CHATWOOT_STREAM_REPLY=true.
    """
    message = (message or "").strip()
    if not message:
        return
    t0 = time.perf_counter()
    rag_text = rag_search(message)
    rag_sec = time.perf_counter() - t0
    log = logging.getLogger(__name__)
    log.info(
        "stream_rag_reply: query_len=%s rag_len=%s rag_sec=%.2f",
        len(message), len(rag_text or ""), rag_sec,
    )
    system_content = SYSTEM_PROMPT_TEMPLATE.replace("{{RAG_CONTEXT}}", rag_text)
    buffer = ""
    sources_start = False
    min_c, max_c = STREAM_MIN_CHARS, STREAM_MAX_CHARS
    try:
        for delta in _stream_llm_content(system_content, message):
            buffer += delta
            if "Источники:" in buffer or "Источник:" in buffer:
                sources_start = True
            if sources_start:
                continue
            while len(buffer) >= min_c:
                block, buffer = _split_block(buffer, min_c, max_c)
                if block:
                    yield block
        if buffer.strip():
            yield _clean_reply(buffer.strip()) if ("Источники:" in buffer or "Источник:" in buffer) else buffer.strip()
    except Exception as e:
        log.exception("stream_rag_reply failed: %s", e)
        if buffer.strip():
            yield buffer.strip()
    finally:
        log.info("stream_rag_reply: llm stream done total_sec=%.2f", time.perf_counter() - t0)


def get_rag_reply(message: str) -> str:
    """RAG + LLM reply for a single message. Used by Chatwoot webhook (bot + copilot)."""
    message = (message or "").strip()
    if not message:
        return ""
    t0 = time.perf_counter()
    rag_text = rag_search(message)
    rag_sec = time.perf_counter() - t0
    rag_empty = "ничего не найдено" in (rag_text or "") or len(rag_text or "") < 50
    log = logging.getLogger(__name__)
    log.info(
        "get_rag_reply: query_len=%s rag_len=%s rag_has_results=%s rag_sec=%.2f",
        len(message), len(rag_text or ""), not rag_empty, rag_sec,
    )
    system_content = SYSTEM_PROMPT_TEMPLATE.replace("{{RAG_CONTEXT}}", rag_text)
    t1 = time.perf_counter()
    try:
        reply = _call_llm(system_content, message)
    except Exception:
        return ""
    llm_sec = time.perf_counter() - t1
    log.info("get_rag_reply: llm_sec=%.2f total_sec=%.2f", llm_sec, time.perf_counter() - t0)
    return _clean_reply(reply)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Укажите message")
    backend = (request.backend or "qdrant").strip().lower()
    if backend == "algolia":
        try:
            reply = _algolia_reply(message)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Algolia: {e}")
        reply = _clean_reply(reply)
        return ChatResponse(reply=reply)
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
    backend = (request.backend or "qdrant").strip().lower()

    # Проверка конфига Algolia до начала стрима (иначе 503 после 200 ломает клиента)
    if backend == "algolia" and (not ALGOLIA_APP_ID or not ALGOLIA_API_KEY):
        raise HTTPException(
            status_code=503,
            detail="Algolia Agent не настроен. Задайте ALGOLIA_APPLICATION_ID и ALGOLIA_API_KEY в .env на сервере.",
        )

    def generate() -> Any:
        try:
            if backend == "algolia":
                for chunk in _algolia_stream(message):
                    yield chunk
            else:
                rag_text = rag_search(message)
                for chunk in _stream_llm(
                    SYSTEM_PROMPT_TEMPLATE.replace("{{RAG_CONTEXT}}", rag_text),
                    message,
                ):
                    yield chunk
        except HTTPException as e:
            yield f"data: {json.dumps({'error': e.detail or str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


try:
    from backend.chatwoot_webhook import router as chatwoot_router, set_reply_provider, set_stream_reply_provider
    set_reply_provider(get_rag_reply)
    set_stream_reply_provider(stream_rag_reply)
    app.include_router(chatwoot_router)
except ImportError:
    pass


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    """Favicon с kinescope.com."""
    favicon_path = _STATIC_DIR / "favicon.png"
    if not favicon_path.exists():
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(favicon_path, media_type="image/png")


@app.get("/")
def index() -> FileResponse:
    """Чат-интерфейс."""
    index_html = _STATIC_DIR / "index.html"
    if not index_html.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(
        index_html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )
