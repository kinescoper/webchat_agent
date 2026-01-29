# Веб-чат с RAG (база знаний)

Чат-интерфейс с доступом к RAG: поиск по Qdrant + ответ внешней LLM по API с системным промптом по образцу Cursor.

**Развёртывание на внешнем сервере:** см. [DEPLOY.md](DEPLOY.md).

## Архитектура

- **Frontend**: одна страница чата (`backend/static/index.html`), запросы на `POST /chat`.
- **Backend**: FastAPI — для каждого сообщения вызывает RAG ([rag/search.py](rag/search.py)), подмешивает результаты в системный промпт и вызывает внешнюю LLM (OpenAI-совместимый API).
- **Qdrant**: векторная БД с коллекцией `papers` (section, source, content). Разворачивается отдельно или через docker-compose.

## Переменные окружения

### Backend (веб)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `QDRANT_URL` | `http://localhost:6333` | URL Qdrant |
| `COLLECTION_NAME` | `papers` | Коллекция |
| `LLM_API_BASE_URL` | — | Базовый URL Chat API (OpenAI, Ollama и т.д.) |
| `LLM_API_KEY` | — | API-ключ (для OpenAI и др.; для Ollama можно пустой) |
| `LLM_MODEL` | `gpt-4o-mini` | Имя модели |

Параметры RAG (эмбеддинг, ре-ранжирование) — те же, что у [mcp_server](mcp_server/README.md): `LIMIT_FIRST`, `LIMIT_FINAL`, `RERANK_ALPHA`, `USE_CROSS_ENCODER` и т.д.

## Запуск локально

1. Убедитесь, что Qdrant запущен и коллекция `papers` заполнена (см. [scripts/README.md](scripts/README.md): crawl + index_to_qdrant).

2. Установите зависимости веб-бэкенда:
   ```bash
   pip install -r requirements-web.txt
   ```

3. Задайте переменные для LLM, например:
   ```bash
   export LLM_API_BASE_URL=https://api.openai.com/v1
   export LLM_API_KEY=sk-...
   export LLM_MODEL=gpt-4o-mini
   ```
   Для Ollama:
   ```bash
   export LLM_API_BASE_URL=http://localhost:11434/v1
   export LLM_API_KEY=optional
   export LLM_MODEL=llama3.2
   ```

4. Запуск бэкенда:
   ```bash
   uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

5. Откройте в браузере: http://localhost:8000

## Запуск через Docker Compose

1. Создайте файл `.env` в корне проекта (или задайте переменные в окружении):
   ```
   LLM_API_BASE_URL=https://api.openai.com/v1
   LLM_API_KEY=sk-...
   LLM_MODEL=gpt-4o-mini
   ```

2. Запуск Qdrant и бэкенда:
   ```bash
   docker compose up -d
   ```

3. После первого запуска коллекция `papers` на Qdrant пуста. Варианты:
   - **Переиндексация**: на хосте с доступом к `docs_crawl` выполните один раз:
     ```bash
     QDRANT_URL=http://localhost:6333 python scripts/index_to_qdrant.py
     ```
   - **Snapshot**: создайте snapshot коллекции на старом Qdrant, скопируйте на сервер и восстановите в контейнере (см. документацию Qdrant).

4. Чат: http://localhost:8000

## API

- `GET /` — чат-интерфейс (HTML).
- `POST /chat` — тело `{"message": "текст вопроса"}`, ответ `{"reply": "ответ ассистента"}`.
- `GET /health` — проверка работы сервиса.
