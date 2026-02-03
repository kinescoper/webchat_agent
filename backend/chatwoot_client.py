"""
Chatwoot Application API client: post messages (public reply or private note).
Used by the webhook handler for RAG bot replies and copilot suggestions.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CHATWOOT_BASE_URL = (os.environ.get("CHATWOOT_BASE_URL") or "").rstrip("/")
CHATWOOT_ACCOUNT_ID = os.environ.get("CHATWOOT_ACCOUNT_ID", "")
CHATWOOT_API_ACCESS_TOKEN = (os.environ.get("CHATWOOT_API_ACCESS_TOKEN") or "").strip()


def is_configured() -> bool:
    return bool(CHATWOOT_BASE_URL and CHATWOOT_ACCOUNT_ID and CHATWOOT_API_ACCESS_TOKEN)


def post_message(
    conversation_id: int,
    content: str,
    *,
    private: bool = False,
) -> dict[str, Any] | None:
    """
    Post a message to a Chatwoot conversation (Application API).
    private=True: only agents see it (copilot suggestion).
    private=False: customer sees it (bot reply).
    """
    if not is_configured():
        logger.warning("Chatwoot client: not configured, cannot post message")
        return None
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    payload: dict[str, Any] = {
        "content": content,
        "message_type": "outgoing",
        "private": private,
    }
    with httpx.Client(timeout=30.0) as client:
        try:
            r = client.post(
                url,
                json=payload,
                headers={
                    "api_access_token": CHATWOOT_API_ACCESS_TOKEN,
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            logger.info(
                "Chatwoot client: message posted conversation_id=%s private=%s",
                conversation_id,
                private,
            )
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Chatwoot client: post_message failed conversation_id=%s status=%s body=%s",
                conversation_id,
                e.response.status_code,
                (e.response.text or "")[:500],
            )
            return None
        except (httpx.HTTPError, Exception) as e:
            logger.exception("Chatwoot client: post_message error conversation_id=%s %s", conversation_id, e)
            return None
