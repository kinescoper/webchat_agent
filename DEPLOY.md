# Развёртывание на внешнем сервере

Пошаговая инструкция по развёртыванию веб-чата с RAG (Qdrant + бэкенд) на внешнем сервере (VPS, облако).

## Требования

- Сервер с Docker и Docker Compose (или совместимый оркестратор).
- Доступ по SSH.
- Файл `.env` с ключом LLM API (OpenAI или совместимый).

## 1. Копирование проекта на сервер

Склонируйте репозиторий или скопируйте проект на сервер:

```bash
git clone <url-репозитория> /opt/rag-chat
cd /opt/rag-chat
```

Либо загрузите архив и распакуйте в нужную директорию.

## 2. Настройка переменных окружения

Создайте файл `.env` в корне проекта (рядом с `docker-compose.yml`):

```bash
cp .env.example .env
nano .env   # или любой редактор
```

Заполните обязательные переменные:

```env
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

Не коммитьте `.env` в репозиторий — в нём хранятся секреты.

При интеграции с **Chatwoot** (webhook на `agent.kn.pe`) добавьте в `.env` переменные из [docs/CHATWOOT-PRE-CHAT-FORM.md](docs/CHATWOOT-PRE-CHAT-FORM.md) (`CHATWOOT_BASE_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_ACCESS_TOKEN`). Чтобы ответ бота шёл блоками (стриминг), задайте `CHATWOOT_STREAM_REPLY=true`.

Чтобы в веб-чате работала модель **Algolia** (селектор в интерфейсе), добавьте в `.env` на сервере: `ALGOLIA_APPLICATION_ID`, `ALGOLIA_API_KEY` (search-only key). Опционально: `ALGOLIA_AGENT_ID`. По умолчанию используется US-эндпоинт `https://agent-studio.us.algolia.com` (для серверных запросов без Cloudflare challenge). При необходимости EU: `ALGOLIA_AGENT_STUDIO_BASE_URL=https://agent-studio.eu.algolia.com`. После изменения `.env`: `docker compose up -d --force-recreate backend`.

## 3. Запуск сервисов

Из корня проекта:

```bash
docker compose up -d
```

Будут запущены:

- **qdrant** — векторная БД (порты 6333, 6334), данные в volume `qdrant_storage`.
- **backend** — веб-бэкенд и чат (порт 8000), подключается к Qdrant по имени сервиса `qdrant`.

Проверка:

```bash
docker compose ps
curl http://localhost:8000/health
```

Чат будет доступен по адресу: `http://<IP-сервера>:8000`.

## 4. Заполнение коллекции papers (первый запуск)

После первого запуска коллекция `papers` в Qdrant пуста — чат не сможет отвечать по базе знаний. Нужно один раз заполнить её.

### Вариант А: переиндексация на сервере

Если на сервере есть исходные документы (например, папка `docs_crawl` с .md файлами):

1. Установите зависимости индексатора и скопируйте папку `docs_crawl` (или получите её через crawl).
2. Выполните на хосте (не в контейнере), указав URL Qdrant:

```bash
pip install -r requirements-indexer.txt
QDRANT_URL=http://localhost:6333 python scripts/index_to_qdrant.py
```

Коллекция будет создана и заполнена. После этого перезапуск не нужен.

### Вариант Б: перенос snapshot с текущей машины

Если коллекция уже есть на вашей машине (например, локальный Qdrant):

1. На текущей машине создайте snapshot коллекции `papers` (REST API или клиент Qdrant).
2. Скопируйте файл snapshot на сервер.
3. Восстановите коллекцию из snapshot на Qdrant на сервере (см. документацию Qdrant: restore from snapshot).
4. Либо скопируйте volume `qdrant_storage` с текущей машины на сервер и смонтируйте его в контейнер `qdrant`.

После заполнения коллекции чат начнёт отдавать ответы по базе знаний.

## 5. Доступ с интернета: nginx (порты 80/443)

Чтобы открывать сайт по **http://kn.pe/** (без порта), на VPS нужен обратный прокси. Рекомендуемый стек — **nginx**.

### Вариант A: скрипт с локальной машины

Из корня репозитория (при настроенном SSH Host `gdrant-agent`):

```bash
./scripts/setup-nginx-vps.sh
```

Скрипт установит nginx на VPS, скопирует конфиг из `nginx/kn.pe.conf`, включит сайт `kn.pe` и перезагрузит nginx. Прокси: порт 80 → `http://127.0.0.1:8000`. Для стриминга `/chat/stream` в конфиге отключена буферизация и увеличен таймаут.

### Вариант B: вручную на VPS

1. Установите nginx: `apt-get update && apt-get install -y nginx`
2. Скопируйте конфиг: `cp /opt/rag-chat/nginx/kn.pe.conf /etc/nginx/sites-available/kn.pe.conf`
3. Включите сайт: `ln -sf /etc/nginx/sites-available/kn.pe.conf /etc/nginx/sites-enabled/` и при необходимости удалите `sites-enabled/default`
4. Проверьте и перезагрузите: `nginx -t && systemctl reload nginx`

### DNS и HTTPS

- В DNS для **kn.pe** (и при необходимости **www.kn.pe**) укажите A-запись на IP вашего VPS.
- Для поддоменов **chatwoot.kn.pe** и **agent.kn.pe**: добавьте A-записи на тот же IP; разнесение по поддоменам и конфиги nginx описаны в [docs/subdomains-kn-pe.md](docs/subdomains-kn-pe.md).
- На **kn.pe** по умолчанию отображается лендинг со списком сервисов (ссылки на Chatwoot и Knowledge base web chat). Файлы лендинга: `nginx/kn.pe-landing/`; на VPS скопируйте их в `/var/www/kn.pe/`.
- Для HTTPS: получите сертификат (например, `certbot --nginx -d kn.pe`), затем добавьте в `nginx/kn.pe.conf` блок `server { listen 443 ssl; ... }` с путями к сертификату (в файле есть закомментированный пример).

### Прочее

- **Порт 8000** можно не открывать в файрволе — доступ только через nginx на 80/443.
- **Caddy**: в корне проекта есть `Caddyfile.example` как альтернатива nginx.
- Переменные backend (`QDRANT_URL`, `COLLECTION_NAME`) менять не нужно.

## 6. Обновление и перезапуск

После изменений в коде или конфиге:

```bash
cd /opt/rag-chat
git pull   # если используете git
docker compose build backend
docker compose up -d
```

**Скрипт деплоя (с локальной машины):** из корня репозитория можно запустить `./scripts/deploy-to-vps.sh`: он синхронизирует проект на VPS (Host `gdrant-agent`) в `/opt/rag-chat`, затем выполняет на сервере `docker compose up -d --build` и проверяет `/health`. Файл `.env` на сервер не копируется — создайте его один раз вручную (см. шаг 2). Опция `--no-sync` только перезапускает контейнеры без rsync.

Логи:

```bash
docker compose logs -f backend
docker compose logs -f qdrant
```

## 7. Резервное копирование

- **Qdrant**: данные в volume `qdrant_storage`. Делайте бэкап этого volume или создавайте snapshot коллекции `papers` средствами Qdrant.
- **.env**: храните копию `.env` в безопасном месте (без коммита в репозиторий).

---

Кратко: скопировать проект → создать `.env` из `.env.example` → `docker compose up -d` → один раз заполнить коллекцию `papers` (переиндексация или snapshot) → при необходимости настроить прокси и HTTPS.
