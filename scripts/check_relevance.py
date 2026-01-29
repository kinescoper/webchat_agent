#!/usr/bin/env python3
"""
Проверка релевантности поиска для типовых запросов.
Загружает тесты из relevance_tests.json, выполняет поиск (как MCP),
проверяет, что ожидаемый источник в топ-N, выводит отчёт и рекомендации.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Конфиг (как в MCP-сервере)
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "papers")
VECTOR_NAME = "fast-all-minilm-l6-v2"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_FILE = SCRIPT_DIR / "relevance_tests.json"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _keyword_score(query: str, content: str) -> float:
    q = _tokenize(query)
    if not q:
        return 0.0
    c = _tokenize(content)
    return len(q & c) / len(q)


def run_search(
    query: str,
    embedder,
    client,
    limit_first: int = 20,
    limit_final: int = 5,
    alpha: float = 0.6,
):
    """Поиск: эмбеддинг + Qdrant + ре-ранжирование по словам. Возвращает список hit с payload."""
    vectors = list(embedder.embed([query]))
    v = vectors[0].tolist() if hasattr(vectors[0], "tolist") else list(vectors[0])
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=v,
        using=VECTOR_NAME,
        limit=limit_first,
        with_payload=True,
    )
    hits = getattr(response, "points", []) or []
    if not hits:
        return []
    # Ре-ранжирование
    scored = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        content = (payload.get("content") or "").strip()
        vec_s = float(getattr(hit, "score", 0.0))
        kw_s = _keyword_score(query, content)
        combined = alpha * vec_s + (1.0 - alpha) * kw_s
        scored.append((combined, hit))
    scored.sort(key=lambda x: -x[0])
    return [hit for _, hit in scored[:limit_final]]


def run_search_full(
    query: str,
    embedder,
    client,
    limit_first: int,
    alpha: float,
):
    """Поиск с ре-ранжированием, возвращает полный список (топ limit_first) для анализа позиций."""
    vectors = list(embedder.embed([query]))
    v = vectors[0].tolist() if hasattr(vectors[0], "tolist") else list(vectors[0])
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=v,
        using=VECTOR_NAME,
        limit=limit_first,
        with_payload=True,
    )
    hits = getattr(response, "points", []) or []
    scored = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        content = (payload.get("content") or "").strip()
        vec_s = float(getattr(hit, "score", 0.0))
        kw_s = _keyword_score(query, content)
        combined = alpha * vec_s + (1.0 - alpha) * kw_s
        scored.append((combined, hit))
    scored.sort(key=lambda x: -x[0])
    return [hit for _, hit in scored]


def find_expected_position(
    query: str,
    embedder,
    client,
    expected_contains: str,
    limit_first: int,
    alpha: float,
) -> int | None:
    """Позиция (1-based) ожидаемого источника после ре-ранжирования, или None."""
    ranked = run_search_full(query, embedder, client, limit_first, alpha)
    for i, hit in enumerate(ranked, 1):
        payload = getattr(hit, "payload", None) or {}
        section = (payload.get("section") or "") + " " + (payload.get("source") or "")
        if expected_contains.lower() in section.lower():
            return i
    return None


def main() -> int:
    if not TESTS_FILE.exists():
        print(f"Файл тестов не найден: {TESTS_FILE}", file=sys.stderr)
        return 1

    with open(TESTS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    tests = data.get("tests", [])
    params = data.get("params", {})
    limit_first = params.get("limit_first", 20)
    limit_final = params.get("limit_final", 5)
    alpha = params.get("rerank_alpha", 0.6)

    print("Загрузка модели и подключение к Qdrant...", flush=True)
    from fastembed import TextEmbedding
    from qdrant_client import QdrantClient

    embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    client = QdrantClient(url=QDRANT_URL)

    passed = 0
    failed = []

    for tc in tests:
        tid = tc.get("id", "?")
        query = tc.get("query", "")
        expected_contains = tc.get("expected_section_contains", "")
        expected_in_top = tc.get("expected_in_top", limit_final)

        if not query or not expected_contains:
            print(f"  [{tid}] пропущен: нет query или expected_section_contains")
            continue

        results = run_search(
            query,
            embedder,
            client,
            limit_first=limit_first,
            limit_final=limit_final,
            alpha=alpha,
        )

        found_at = None
        for i, hit in enumerate(results, 1):
            payload = getattr(hit, "payload", None) or {}
            section = (payload.get("section") or "") + " " + (payload.get("source") or "")
            if expected_contains.lower() in section.lower():
                found_at = i
                break

        if found_at is None:
            pos_in_full = find_expected_position(
                query, embedder, client, expected_contains, limit_first, alpha
            )
        else:
            pos_in_full = found_at

        if (found_at is not None and found_at <= expected_in_top) or (
            pos_in_full is not None and pos_in_full <= expected_in_top
        ):
            passed += 1
            display_pos = found_at if found_at is not None else pos_in_full
            print(f"  [OK] {tid}: «{query[:50]}...» — ожидаемый источник на месте {display_pos}")
        else:
            failed.append(
                {
                    "id": tid,
                    "query": query,
                    "expected_contains": expected_contains,
                    "found_at": found_at,
                    "position_in_candidates": pos_in_full,
                }
            )
            pos_msg = f" (в топ-{limit_first} на позиции {pos_in_full})" if pos_in_full else " (не найден в топе)"
            print(f"  [FAIL] {tid}: «{query[:50]}...» — ожидаемый источник не в топ-{expected_in_top}{pos_msg}")

    print()
    print(f"Итого: {passed}/{len(tests)} тестов пройдено.")
    if failed:
        print()
        print("Рекомендации по исправлению:")
        for f in failed:
            tid = f["id"]
            pos = f.get("position_in_candidates")
            if pos is not None and pos > limit_final:
                print(f"  - {tid}: ожидаемый результат на позиции {pos}. Можно снизить RERANK_ALPHA (например до 0.5) в relevance_tests.json params или в env MCP.")
            else:
                print(f"  - {tid}: ожидаемый раздел не попал в топ-{limit_first}. Проверьте формулировку запроса или добавьте контент в индекс.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
