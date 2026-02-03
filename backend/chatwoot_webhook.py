"""
Chatwoot webhook handler: bot mode (reply to customer) and copilot mode (private suggestion).
Subscribe to message_created; use conversation (or contact) custom attribute support_mode: "bot" | "human".

Portable: no dependency on a specific RAG/LLM. Set reply provider via set_reply_provider(get_reply)
so any project can plug in its own AI backend (e.g. RAG+LLM, another API).
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time as _time
from typing import Any, Callable, Iterator

# Chatwoot иногда присылает content с HTML (<p>текст</p>) — убираем теги перед RAG
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Сообщения только с email (Pre Chat Form) не отправляем в RAG — не постим "не нашёл"
_EMAIL_ONLY_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", re.IGNORECASE)
# Короткие служебные фразы виджета — пропускаем, не вызываем RAG
_SKIP_PHRASES = frozenset(
    s.lower()
    for s in (
        "get notified by email",
        "please enter your email",
        "give the team a way to reach you",
    )
)

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from backend.chatwoot_client import is_configured, post_message

logger = logging.getLogger(__name__)

SUPPORT_MODE_ATTR = os.environ.get("CHATWOOT_SUPPORT_MODE_ATTR", "support_mode")
COPILOT_PREFIX = "[RAG suggestion – use or edit]\n\n"
# Мгновенное сообщение в чат, пока AI готовит ответ (режим bot)
AUTO_REPLY_PLACEHOLDER = "Спасибо за обращение. Наш AI ассистент уже работает над ответом, подождите пожалуйста несколько секунд."

# Reply provider: (message: str) -> str | None. Injected by the host app (e.g. RAG backend).
ReplyProvider = Callable[[str], str | None]
# Stream reply provider: (message: str) -> Iterator[str]. Yields blocks to post to Chatwoot (bot mode only).
StreamReplyProvider = Callable[[str], Iterator[str]]
_reply_provider: ReplyProvider | None = None
_stream_reply_provider: StreamReplyProvider | None = None

# Стримить ответ бота блоками (true) или одним сообщением (false). При true placeholder не постится.
STREAM_REPLY_ENABLED = os.environ.get("CHATWOOT_STREAM_REPLY", "").lower() in ("1", "true", "yes")


def set_reply_provider(provider: ReplyProvider | None) -> None:
    """Set the function used to generate replies (e.g. RAG+LLM). Required for webhook to work."""
    global _reply_provider
    _reply_provider = provider


def set_stream_reply_provider(provider: StreamReplyProvider | None) -> None:
    """Set the stream reply provider (yields blocks). Used when CHATWOOT_STREAM_REPLY=true."""
    global _stream_reply_provider
    _stream_reply_provider = provider


def get_reply_provider() -> ReplyProvider | None:
    return _reply_provider


def get_stream_reply_provider() -> StreamReplyProvider | None:
    return _stream_reply_provider


router = APIRouter(prefix="/chatwoot", tags=["chatwoot"])


class WebhookPayload(BaseModel):
    """Chatwoot webhook body (flexible)."""
    event: str = ""
    id: str | int | None = None
    content: str = ""
    message_type: str = ""
    content_type: str = "text"
    sender: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    conversation: dict[str, Any] | None = None

    class Config:
        extra = "allow"


def _normalize_support_mode(value: str) -> str:
    """Map raw attribute value (e.g. 'bot', 'AI агент', 'human') to 'bot' or 'human'."""
    v = (value or "").strip().lower()
    if v in ("bot", "human"):
        return v
    # Display labels: "AI агент", "ai agent", etc. -> bot
    if v in ("ai агент", "ai agent", "agent") or "bot" in v or "ai" in v or "agent" in v:
        return "bot"
    # "Человек", "human", "operator" -> human
    if "human" in v or "человек" in v or "operator" in v or "оператор" in v:
        return "human"
    return "human"


def _support_mode(payload: WebhookPayload) -> str:
    """Return 'bot' | 'human' from conversation or contact custom_attributes (Pre Chat Form or SDK)."""
    for source in (payload.conversation, payload.contact):
        if not source:
            continue
        attrs = source.get("custom_attributes") or source.get("additional_attributes") or {}
        raw = (attrs.get(SUPPORT_MODE_ATTR) or attrs.get("preferred_channel") or "")
        if isinstance(raw, str) and raw.strip():
            return _normalize_support_mode(raw)
        if raw is not None and str(raw).strip():
            return _normalize_support_mode(str(raw))
    # При пустых атрибутах (первое сообщение до отправки формы) по умолчанию human:
    # ответ уходит как приватная заметка оператору, клиент не видит «не нашёл» на не-вопрос.
    # После выбора «AI агент» в форме атрибуты заполняются и ответы идут публично (bot).
    return "human"


def _conversation_id(payload: WebhookPayload) -> int | None:
    """Numeric conversation id for API."""
    conv = payload.conversation or {}
    cid = conv.get("id")
    if cid is not None:
        try:
            return int(cid)
        except (TypeError, ValueError):
            pass
    return None


def _is_email_only(content: str, content_type: str) -> bool:
    """Пропускаем сообщения с только email (Pre Chat Form), чтобы не постить «не нашёл»."""
    if (content_type or "").strip().lower() in ("input_email", "input_csat"):
        return True
    line = content.strip()
    if not line or "\n" in line:
        return False
    return bool(_EMAIL_ONLY_RE.match(line))


def _is_skip_phrase(content: str) -> bool:
    """Пропускаем короткие служебные фразы виджета (не вопрос пользователя)."""
    line = (content or "").strip()
    if not line or "\n" in line:
        return True
    return line.lower() in _SKIP_PHRASES


def _strip_html(text: str) -> str:
    """Убираем HTML-теги из content (Chatwoot может присылать <p>...</p>)."""
    if not text:
        return ""
    return _HTML_TAG_RE.sub(" ", text).strip()


def _process_message(payload: WebhookPayload) -> None:
    """Call reply provider and post reply (public for bot, private for copilot)."""
    cid = _conversation_id(payload)
    mode = _support_mode(payload)
    raw_content = (payload.content or "").strip()
    content = _strip_html(raw_content)
    if raw_content != content:
        logger.info("chatwoot: stripped HTML from content raw_len=%s clean_len=%s", len(raw_content), len(content))
    content_type = (payload.content_type or "text").strip()
    conv_attrs = (payload.conversation or {}).get("custom_attributes") or {}
    raw_mode_conv = conv_attrs.get(SUPPORT_MODE_ATTR) or conv_attrs.get("preferred_channel")
    content_preview = (content[:80] + "…") if len(content) > 80 else content
    logger.info(
        "chatwoot webhook process: conversation_id=%s support_mode=%s content_type=%s content_preview=%r",
        cid,
        mode,
        content_type,
        content_preview,
    )
    if not is_configured():
        logger.warning("Chatwoot client not configured; skipping webhook processing")
        return
    provider = get_reply_provider()
    if not provider:
        logger.warning("Reply provider not set; skipping webhook processing")
        return
    if cid is None:
        logger.warning("No conversation id in webhook payload")
        return
    if not content:
        logger.info("Empty content; skipping")
        return
    if _is_email_only(content, content_type):
        logger.info("Skipping email-only / pre-chat contact message; not calling RAG")
        return
    if _is_skip_phrase(content):
        logger.info("Skipping widget system phrase; not calling RAG")
        return

    stream_provider = get_stream_reply_provider() if mode == "bot" else None
    use_stream = mode == "bot" and STREAM_REPLY_ENABLED and stream_provider is not None

    if mode == "bot" and not use_stream:
        post_message(cid, AUTO_REPLY_PLACEHOLDER, private=False)

    t0 = _time.perf_counter()
    if use_stream:
        block_count = 0
        try:
            for block in stream_provider(content):
                if not (block or "").strip():
                    continue
                block_count += 1
                ok = post_message(cid, block.strip(), private=False)
                if not ok:
                    logger.error("Failed to post stream block %s to conversation_id=%s", block_count, cid)
                    break
        except Exception as e:
            logger.exception("Stream reply provider failed for conversation_id=%s: %s", cid, e)
        total_sec = _time.perf_counter() - t0
        print(
            f"[chatwoot] stream_blocks={block_count} total_sec={total_sec:.2f} mode={mode}",
            file=sys.stderr,
            flush=True,
        )
        return

    try:
        reply = provider(content)
    except Exception as e:
        logger.exception("Reply provider failed for conversation_id=%s: %s", cid, e)
        return
    if not reply:
        logger.warning("Reply provider returned empty for conversation_id=%s content_len=%s", cid, len(content))
        return
    total_sec = _time.perf_counter() - t0
    print(f"[chatwoot] reply_len={len(reply)} total_sec={total_sec:.2f} mode={mode}", file=sys.stderr, flush=True)
    if mode == "bot":
        ok = post_message(cid, reply, private=False)
        if not ok:
            logger.error("Failed to post bot reply to conversation_id=%s", cid)
    else:
        ok = post_message(cid, COPILOT_PREFIX + reply, private=True)
        if not ok:
            logger.error("Failed to post copilot suggestion to conversation_id=%s", cid)


class CopilotRequest(BaseModel):
    """Request body for /copilot (suggestion only, no post to Chatwoot)."""
    message: str = Field(..., min_length=1)


class CopilotResponse(BaseModel):
    suggestion: str


@router.post("/copilot", response_model=CopilotResponse)
def copilot_suggest(req: CopilotRequest) -> CopilotResponse:
    """
    Return AI suggestion for the given message (for operators).
    Does not post to Chatwoot; operator can use or edit the text.
    """
    provider = get_reply_provider()
    reply = (provider(req.message) if provider else None) or ""
    return CopilotResponse(suggestion=reply)


@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """
    Chatwoot webhook: message_created.
    - Incoming only; bot mode -> post public reply; human mode -> post private suggestion.
    """
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("chatwoot webhook: invalid JSON body %s", e)
        return {"status": "ok"}
    event = body.get("event", "")
    message_type = body.get("message_type", "")
    cid = None
    conv = body.get("conversation") or {}
    if conv:
        try:
            cid = int(conv.get("id"))
        except (TypeError, ValueError):
            pass
    logger.info(
        "chatwoot webhook: event=%s message_type=%s conversation_id=%s",
        event,
        message_type,
        cid,
    )
    if event != "message_created":
        logger.debug("chatwoot webhook: skip event %s", event)
        return {"status": "ok"}
    if message_type != "incoming":
        logger.debug("chatwoot webhook: skip message_type %s", message_type)
        return {"status": "ok"}
    content = (body.get("content") or "").strip()
    conv_attrs = conv.get("custom_attributes") or conv.get("additional_attributes") or {}
    print(
        f"[chatwoot] content={repr(content)[:120]} cid={cid} support_mode={conv_attrs.get(SUPPORT_MODE_ATTR)}",
        file=sys.stderr,
        flush=True,
    )
    payload = WebhookPayload(
        event=event,
        id=body.get("id"),
        content=body.get("content", ""),
        message_type=message_type,
        content_type=body.get("content_type", "text"),
        sender=body.get("sender"),
        contact=body.get("contact"),
        conversation=conv,
    )
    background_tasks.add_task(_process_message, payload)
    return {"status": "ok"}
