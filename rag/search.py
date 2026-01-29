"""
Поиск по базе знаний (Qdrant): эмбеддинг запроса, векторный поиск, ре-ранжирование.
Используется MCP-сервером и веб-бэкендом.
"""
from __future__ import annotations

import functools
import os
import re
from typing import Any

# Конфиг из env
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "papers")
VECTOR_NAME = "fast-all-minilm-l6-v2"
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
LIMIT_FIRST = int(os.environ.get("LIMIT_FIRST", "20"))
LIMIT_FINAL = int(os.environ.get("LIMIT_FINAL", "5"))
RERANK_ALPHA = float(os.environ.get("RERANK_ALPHA", "0.6"))
CACHE_MAX_SIZE = int(os.environ.get("CACHE_MAX_SIZE", "200"))
USE_CROSS_ENCODER = os.environ.get("USE_CROSS_ENCODER", "").lower() in ("1", "true", "yes")

_embedder: Any = None
_qdrant_client: Any = None
_cross_encoder: Any = None


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _embedder


def _get_qdrant_client() -> Any:
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        _qdrant_client = QdrantClient(url=QDRANT_URL)
    return _qdrant_client


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _keyword_score(query: str, content: str) -> float:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0
    c_tokens = _tokenize(content)
    return len(q_tokens & c_tokens) / len(q_tokens)


def _rerank_by_keyword(
    query: str,
    hits: list[Any],
    alpha: float = RERANK_ALPHA,
) -> list[Any]:
    scored: list[tuple[float, Any]] = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        content = (payload.get("content") or "").strip()
        vec_score = float(getattr(hit, "score", 0.0))
        kw_score = _keyword_score(query, content)
        combined = alpha * vec_score + (1.0 - alpha) * kw_score
        scored.append((combined, hit))
    scored.sort(key=lambda x: -x[0])
    return [hit for _, hit in scored]


def _rerank_by_cross_encoder(
    query: str,
    hits: list[Any],
    limit: int = LIMIT_FINAL,
) -> list[Any]:
    global _cross_encoder
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception:
            return _rerank_by_keyword(query, hits)[:limit]
    payloads = [getattr(h, "payload", None) or {} for h in hits]
    contents = [(p.get("content") or "").strip() for p in payloads]
    pairs = [(query, c) for c in contents]
    scores = _cross_encoder.predict(pairs)
    scored = list(zip(scores, hits))
    scored.sort(key=lambda x: -float(x[0]))
    return [h for _, h in scored[:limit]]


@functools.lru_cache(maxsize=CACHE_MAX_SIZE)
def _embed_query_cached(query: str) -> tuple[float, ...]:
    vectors = list(_get_embedder().embed([query]))
    v = vectors[0]
    if hasattr(v, "tolist"):
        v = v.tolist()
    else:
        v = list(v)
    return tuple(v)


def search(
    query: str,
    limit_first: int | None = None,
    limit_final: int | None = None,
    alpha: float | None = None,
    use_cross_encoder: bool | None = None,
) -> str:
    """
    Синхронный поиск: эмбеддинг (с кэшем) + Qdrant + ре-ранжирование.
    Возвращает текст с нумерованными результатами (section, source, content).
    """
    q = query.strip()
    lf = limit_first if limit_first is not None else LIMIT_FIRST
    lfinal = limit_final if limit_final is not None else LIMIT_FINAL
    a = alpha if alpha is not None else RERANK_ALPHA
    use_ce = use_cross_encoder if use_cross_encoder is not None else USE_CROSS_ENCODER

    client = _get_qdrant_client()
    v = list(_embed_query_cached(q))
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=v,
        using=VECTOR_NAME,
        limit=lf,
        with_payload=True,
    )
    results = getattr(response, "points", []) or []
    if not results:
        return f"По запросу «{q}» ничего не найдено."
    if use_ce:
        results = _rerank_by_cross_encoder(q, results, limit=lfinal)
    else:
        results = _rerank_by_keyword(q, results, alpha=a)[:lfinal]

    lines = [f"Результаты по запросу «{q}»:\n"]
    for i, hit in enumerate(results, 1):
        score = getattr(hit, "score", None)
        payload = getattr(hit, "payload", None) or {}
        section = payload.get("section", "")
        source = payload.get("source", "")
        content = payload.get("content", "").strip()
        lines.append(f"{i}. (score: {score:.3f}) {section}")
        lines.append(f"   Источник: {source}")
        if content:
            lines.append(f"   Текст: {content}")
        lines.append("")
    return "\n".join(lines).strip()
