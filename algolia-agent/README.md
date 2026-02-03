# Algolia Agent

Минимальный HTTP-сервис с клиентом [Algolia Search API v4](https://github.com/algolia/algoliasearch-client-go) для Go.

## Зависимость

```bash
go get github.com/algolia/algoliasearch-client-go/v4
```

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `ALGOLIA_APPLICATION_ID` | Application ID из Algolia Dashboard |
| `ALGOLIA_API_KEY` | API Key (Search-Only или Admin) |
| `ALGOLIA_AGENT_ADDR` | Адрес слушать (по умолчанию `:8080`) |
| `ALGOLIA_DOCS_DIR` | Путь к каталогу с .md (для `index`; по умолчанию `docs_crawl`) |
| `ALGOLIA_INDEX_NAME` | Имя индекса при загрузке (по умолчанию `kinescope_docs`) |

## Сборка

```bash
cd algolia-agent
go build -o algolia-agent .
```

Кросс-компиляция для Linux (например, с Mac для VPS):

```bash
GOOS=linux GOARCH=amd64 go build -o algolia-agent .
```

## Режимы работы

### HTTP-сервер (по умолчанию)

- **GET /health** — всегда 200, `{"status":"ok","algolia":"configured"}`
- **GET /search?q=...&index=...** — поиск в индексе Algolia. `index` по умолчанию `content`.

### Команда `index` — загрузка .md в Algolia

Читает все `.md` из каталога (например `docs_crawl/` после краула docs.kinescope.ru) и отправляет их в Algolia батчами (addObject). У каждого объекта: `objectID` (путь), `content`, `source` (URL), `section`, `title`.

```bash
export ALGOLIA_APPLICATION_ID=...
export ALGOLIA_API_KEY=...
export ALGOLIA_DOCS_DIR=/opt/rag-chat/docs_crawl   # или docs_crawl относительно текущей папки
export ALGOLIA_INDEX_NAME=kinescope_docs           # опционально

./algolia-agent index
```

## Запуск на VPS

1. Скопировать бинарник и задать переменные:

   ```bash
   scp algolia-agent gdrant-agent:/opt/rag-chat/algolia-agent/
   ssh gdrant-agent
   export ALGOLIA_APPLICATION_ID=...
   export ALGOLIA_API_KEY=...
   cd /opt/rag-chat/algolia-agent && ./algolia-agent
   ```

2. Или собрать на самом VPS (нужен Go):

   ```bash
   ssh gdrant-agent "cd /opt/rag-chat/algolia-agent && go build -o algolia-agent ."
   ```

3. Запуск в фоне (nohup или systemd):

   ```bash
   nohup ./algolia-agent > algolia-agent.log 2>&1 &
   ```

   Для постоянного сервиса создайте unit-файл в `/etc/systemd/system/algolia-agent.service` (см. пример ниже).

### Пример systemd unit

```ini
[Unit]
Description=Algolia Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/rag-chat/algolia-agent
ExecStart=/opt/rag-chat/algolia-agent/algolia-agent
Environment=ALGOLIA_APPLICATION_ID=xxx
Environment=ALGOLIA_API_KEY=xxx
Environment=ALGOLIA_AGENT_ADDR=:8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

После создания: `sudo systemctl daemon-reload && sudo systemctl enable --now algolia-agent`.
