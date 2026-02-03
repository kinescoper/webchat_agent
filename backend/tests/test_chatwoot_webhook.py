"""
Tests for Chatwoot webhook: support_mode parsing, webhook acceptance, and reply flow.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.chatwoot_webhook import (
    AUTO_REPLY_PLACEHOLDER,
    WebhookPayload,
    _conversation_id,
    _is_email_only,
    _is_skip_phrase,
    _normalize_support_mode,
    _strip_html,
    _support_mode,
    router,
    set_reply_provider,
)


# --- _normalize_support_mode ---


@pytest.mark.parametrize(
    "value,expected",
    [
        ("bot", "bot"),
        ("human", "human"),
        ("BOT", "bot"),
        ("AI агент", "bot"),
        ("ai agent", "bot"),
        ("agent", "bot"),
        ("Человек", "human"),
        ("operator", "human"),
        ("", "human"),
        ("unknown", "human"),
    ],
)
def test_normalize_support_mode(value: str, expected: str) -> None:
    assert _normalize_support_mode(value) == expected


# --- _support_mode ---


def test_support_mode_from_conversation_bot() -> None:
    payload = WebhookPayload(
        conversation={"custom_attributes": {"support_mode": "bot"}},
    )
    assert _support_mode(payload) == "bot"


def test_support_mode_from_conversation_human() -> None:
    payload = WebhookPayload(
        conversation={"custom_attributes": {"support_mode": "human"}},
    )
    assert _support_mode(payload) == "human"


def test_support_mode_from_conversation_display_label() -> None:
    payload = WebhookPayload(
        conversation={"custom_attributes": {"support_mode": "AI агент"}},
    )
    assert _support_mode(payload) == "bot"


def test_support_mode_fallback_to_contact() -> None:
    payload = WebhookPayload(
        conversation={},
        contact={"custom_attributes": {"support_mode": "bot"}},
    )
    assert _support_mode(payload) == "bot"


def test_support_mode_default_human_when_no_attrs() -> None:
    """Когда Pre Chat Form ещё не отправлен, атрибуты пустые — ответ приватный (human)."""
    payload = WebhookPayload(conversation={}, contact={})
    assert _support_mode(payload) == "human"


def test_support_mode_preferred_channel_key() -> None:
    payload = WebhookPayload(
        conversation={"custom_attributes": {"preferred_channel": "bot"}},
    )
    assert _support_mode(payload) == "bot"


# --- _conversation_id ---


def test_conversation_id_from_conversation() -> None:
    payload = WebhookPayload(conversation={"id": 123})
    assert _conversation_id(payload) == 123


def test_conversation_id_none_when_missing() -> None:
    payload = WebhookPayload(conversation={})
    assert _conversation_id(payload) is None


# --- Webhook endpoint ---


@pytest.fixture
def client() -> TestClient:
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_webhook_accepts_message_created_incoming(client: TestClient) -> None:
    set_reply_provider(lambda msg: "Reply" if msg else None)
    with patch("backend.chatwoot_webhook.is_configured", return_value=True), patch(
        "backend.chatwoot_webhook.post_message", return_value={"id": 1}
    ):
        r = client.post(
            "/chatwoot/webhook",
            json={
                "event": "message_created",
                "message_type": "incoming",
                "content": "Как загрузить видео?",
                "conversation": {"id": 42, "custom_attributes": {"support_mode": "bot"}},
            },
        )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_webhook_skips_non_message_created(client: TestClient) -> None:
    r = client.post(
        "/chatwoot/webhook",
        json={"event": "conversation_created", "message_type": "incoming"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_webhook_skips_outgoing(client: TestClient) -> None:
    r = client.post(
        "/chatwoot/webhook",
        json={
            "event": "message_created",
            "message_type": "outgoing",
            "content": "Hi",
            "conversation": {"id": 1},
        },
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_webhook_process_posts_bot_reply(client: TestClient) -> None:
    set_reply_provider(lambda msg: f"Echo: {msg}")
    with patch("backend.chatwoot_webhook.is_configured", return_value=True) as mock_cfg, patch(
        "backend.chatwoot_webhook.post_message", return_value={"id": 1}
    ) as mock_post:
        r = client.post(
            "/chatwoot/webhook",
            json={
                "event": "message_created",
                "message_type": "incoming",
                "content": "Test question",
                "conversation": {"id": 99, "custom_attributes": {"support_mode": "bot"}},
            },
        )
    assert r.status_code == 200
    assert mock_post.call_count == 2
    first_call = mock_post.call_args_list[0]
    assert first_call[0][0] == 99
    assert first_call[0][1] == AUTO_REPLY_PLACEHOLDER
    assert first_call[1]["private"] is False
    second_call = mock_post.call_args_list[1]
    assert second_call[0][0] == 99
    assert "Echo: Test question" in second_call[0][1]
    assert second_call[1]["private"] is False


# --- _is_email_only ---


@pytest.mark.parametrize(
    "content,content_type,expected",
    [
        ("user@example.com", "text", True),
        ("hh@jd.com", "text", True),
        ("Admin@Kinescope.IO", "text", True),
        ("Как загрузить видео?", "text", False),
        ("user@example.com\nsecond line", "text", False),
        ("", "text", False),
        ("user@example.com", "input_email", True),
        ("hello", "input_email", True),
    ],
)
def test_is_email_only(content: str, content_type: str, expected: bool) -> None:
    assert _is_email_only(content, content_type) == expected


@pytest.mark.parametrize(
    "content,expected",
    [
        ("Get notified by email", True),
        ("Please enter your email", True),
        ("Как загрузить видео на Kinescope?", False),
        ("", True),
        ("hello", False),
    ],
)
def test_is_skip_phrase(content: str, expected: bool) -> None:
    assert _is_skip_phrase(content) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<p>Как загрузить видео?</p>", "Как загрузить видео?"),
        ("<p>Hello</p>", "Hello"),
        ("No tags", "No tags"),
        ("", ""),
        ("<br/>", ""),
    ],
)
def test_strip_html(text: str, expected: str) -> None:
    assert _strip_html(text).strip() == expected.strip()


def test_webhook_skips_email_only_does_not_post(client: TestClient) -> None:
    """Сообщение только с email (Pre Chat Form) не уходит в RAG и не постится «не нашёл»."""
    set_reply_provider(lambda msg: "не нашёл" if "@" in msg else "OK")
    with patch("backend.chatwoot_webhook.is_configured", return_value=True), patch(
        "backend.chatwoot_webhook.post_message", return_value={"id": 1}
    ) as mock_post:
        r = client.post(
            "/chatwoot/webhook",
            json={
                "event": "message_created",
                "message_type": "incoming",
                "content": "hh@jd.com",
                "content_type": "text",
                "conversation": {"id": 5, "custom_attributes": {"support_mode": "bot"}},
            },
        )
    assert r.status_code == 200
    mock_post.assert_not_called()


def test_webhook_skips_system_phrase_does_not_post(client: TestClient) -> None:
    """Служебная фраза виджета (Get notified by email) не уходит в RAG."""
    set_reply_provider(lambda msg: "не нашёл")
    with patch("backend.chatwoot_webhook.is_configured", return_value=True), patch(
        "backend.chatwoot_webhook.post_message", return_value={"id": 1}
    ) as mock_post:
        r = client.post(
            "/chatwoot/webhook",
            json={
                "event": "message_created",
                "message_type": "incoming",
                "content": "Get notified by email",
                "conversation": {"id": 5, "custom_attributes": {"support_mode": "bot"}},
            },
        )
    assert r.status_code == 200
    mock_post.assert_not_called()
