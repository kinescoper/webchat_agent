# MCP-сервер поиска в Qdrant (papers)

Заменяет `mcp-server-qdrant` для инструмента **qdrant-find**: возвращает результат только как **text** (один блок `TextContent`), чтобы Cursor не падал с ошибкой `'document'`.

- **Инструмент:** `qdrant-find(query)` — семантический поиск по коллекции `papers`.
- **Ускорение:** ленивые синглтоны эмбеддера и Qdrant-клиента; LRU-кэш эмбеддингов запросов.
- **Релевантность:** двухэтапный поиск (топ-20 из Qdrant → ре-ранжирование по словам или кросс-энкодер → топ-5).

**Конфиг (env):**

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `QDRANT_URL` | `http://localhost:6333` | URL Qdrant |
| `COLLECTION_NAME` | `papers` | Коллекция |
| `LIMIT_FIRST` | `20` | Сколько кандидатов тянуть из Qdrant |
| `LIMIT_FINAL` | `5` | Сколько отдавать после ре-ранжирования |
| `RERANK_ALPHA` | `0.6` | Баланс: alpha * vector_score + (1-alpha) * keyword_score |
| `CACHE_MAX_SIZE` | `200` | Размер LRU-кэша эмбеддингов запросов |
| `USE_CROSS_ENCODER` | — | `1`/`true` — ре-ранжировать кросс-энкодером (нужен `sentence-transformers`) |

**Запуск:** через Cursor MCP (указан в `~/.cursor/mcp.json`) или вручную:
```bash
cd /Users/insty/test_mcp && .venv/bin/python mcp_server/server.py
```

Зависимости: `mcp`, `fastembed`, `qdrant-client` (см. `requirements-mcp-server.txt`). Для кросс-энкодера опционально: `sentence-transformers`.
