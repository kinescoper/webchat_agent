# Реиндексация базы знаний Kinescope в Qdrant

Источник: [docs.kinescope.ru](https://docs.kinescope.ru/). Документы сохраняются в `.md` с иерархией, затем индексируются в коллекцию `papers` с именованным вектором `fast-all-minilm-l6-v2` (совместимо с MCP Qdrant).

## Шаги

1. **Краул** — скачать все страницы в `docs_crawl/`:

   ```bash
   pip install -r requirements-indexer.txt
   python scripts/crawl_docs.py
   ```

2. **Индексация** — разбить на чанки, эмбеддить и загрузить в Qdrant:

   ```bash
   python scripts/index_to_qdrant.py
   ```

Убедитесь, что Qdrant запущен на `http://localhost:6333`. Коллекция `papers` будет создана при первом запуске индексера (если ещё не создана MCP).

## Проверка релевантности типовых запросов

Скрипт `check_relevance.py` проверяет, что для заданных запросов ожидаемые источники попадают в топ-N:

```bash
python scripts/check_relevance.py
```

Тест-кейсы задаются в `relevance_tests.json`: для каждого запроса указывается `expected_section_contains` (подстрока в section/source). В `params` можно задать `limit_first`, `limit_final`, `rerank_alpha` (как в MCP). При падении теста скрипт выводит рекомендацию (например, снизить `rerank_alpha` или проверить индекс).

## Переменные

- `DOCS_DIR` — каталог с .md (по умолчанию `docs_crawl/`)
- `QDRANT_URL` — адрес Qdrant (по умолчанию `http://localhost:6333`)
- В индексере используется модель `sentence-transformers/all-MiniLM-L6-v2` (384 dim), как в mcp-server-qdrant.
