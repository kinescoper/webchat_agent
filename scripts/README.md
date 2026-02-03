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

### Индексация в Algolia (опционально)

Чтобы загрузить те же .md из `docs_crawl/` в Algolia:

1. В корневом `.env` задайте `ALGOLIA_APPLICATION_ID` и `ALGOLIA_API_KEY` (API Key с правами на запись).
2. Запустите:
   ```bash
   ./scripts/algolia-index.sh
   ```
   Или из каталога агента: `cd algolia-agent && ./algolia-agent index` (при этом подхватится `../.env`). Индекс по умолчанию: `kinescope_docs`.

### Проверка Algolia Agent Studio

Если вы создали агента в [Agent Studio](https://dashboard.algolia.com/generativeAi/agent-studio/agents) и хотите проверить его по API (например, вопрос «Как загрузить видео?»):

1. В `.env` задайте `ALGOLIA_APPLICATION_ID` (например `src8utybuo`) и `ALGOLIA_API_KEY` (Search-Only API key из дашборда).
2. Опционально: `ALGOLIA_AGENT_ID` — ID опубликованного агента (по умолчанию используется агент из проекта).
3. Запустите:
   ```bash
   ./scripts/test-algolia-agent.sh
   ./scripts/test-algolia-agent.sh "Как загрузить видео?"
   ```
   Скрипт отправит вопрос в Agent Studio Completions API и выведет ответ ассистента.

## Проверка релевантности типовых запросов

Скрипт `check_relevance.py` проверяет, что для заданных запросов ожидаемые источники попадают в топ-N:

```bash
python scripts/check_relevance.py
```

Тест-кейсы задаются в `relevance_tests.json`: для каждого запроса указывается `expected_section_contains` (подстрока в section/source). В `params` можно задать `limit_first`, `limit_final`, `rerank_alpha` (как в MCP). При падении теста скрипт выводит рекомендацию (например, снизить `rerank_alpha` или проверить индекс).

## Облачные агенты (cloud agents)

После перезапуска Cursor desktop можно посмотреть список агентов и краткое «где мы остановились» по каждому, затем подключиться к нужному через Remote-SSH.

### Список агентов и последняя сессия

Регистрация агентов: `scripts/cloud-agents.json`. Добавьте туда id, name, host, summary_path для каждого VPS/агента.

Показать всех агентов и сохранённое резюме последней сессии:

```bash
python scripts/list-cloud-agents.py
```

Подключение: Cursor → Remote-SSH → выберите хост из списка.

### Сохранить, на чём остановились

После работы с удалённым агентом сохраните краткое резюме — тогда после перезапуска Cursor при выводе списка агентов вы увидите, что делали и что делать дальше:

```bash
./scripts/cloud-agent-summary.sh gdrant-agent "Интегрировали webhook Chatwoot. Дальше: проверить из UI Chatwoot."
# или
python scripts/cloud-agent-summary.py gdrant-agent "Текст резюме"
```

Резюме записывается на VPS в `summary_path` (по умолчанию `/root/.cursor/last-session-summary.md`).

### Запуск агента на VPS

Запуск Cursor CLI agent на VPS одной командой: `./scripts/remote-agent-gdrant.sh "prompt"`.

### Сброс чатов агента

После закрытия desktop Cursor состояние чатов на VPS может мешать восстановлению. Чтобы начать с чистого листа:

```bash
./scripts/revoke-remote-agent-chats.sh           # очистить все чаты (с бэкапом)
./scripts/revoke-remote-agent-chats.sh --latest   # очистить только последний разговор
./scripts/revoke-remote-agent-chats.sh --no-backup   # без бэкапа
```

Бэкапы сохраняются на VPS в `/root/.cursor/chats-backup-YYYYMMDD-HHMMSS`. Хост задаётся через `VPS_HOST` (по умолчанию `gdrant-agent`).

## Переменные

- `DOCS_DIR` — каталог с .md (по умолчанию `docs_crawl/`)
- `QDRANT_URL` — адрес Qdrant (по умолчанию `http://localhost:6333`)
- В индексере используется модель `sentence-transformers/all-MiniLM-L6-v2` (384 dim), как в mcp-server-qdrant.
