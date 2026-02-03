# Kinescope — чат по базе знаний (Algolia Agent на Vercel)

Чат с ассистентом по документации Kinescope. Запросы идут **из браузера** напрямую в Algolia Agent Studio (без бэкенда), поэтому нет проблем с Cloudflare и «agent not found».

Стек: **Next.js**, запросы к Algolia Completions API через `fetch` и парсинг стрима (события `text-delta`). Совместимо с форматом AI SDK 5.

## Локальный запуск

```bash
cd algolia-chat-vercel
npm install
npm run dev
```

Откройте [http://localhost:3000](http://localhost:3000).

## Деплой на Vercel

1. Залейте проект в GitHub (или подключите репозиторий к Vercel).
2. В [Vercel](https://vercel.com): **Add New Project** → импортируйте репозиторий.
3. **Root Directory** укажите `algolia-chat-vercel` (если проект в подпапке монорепо).
4. При желании задайте переменные окружения (иначе используются значения по умолчанию из кода):
   - `NEXT_PUBLIC_ALGOLIA_APPLICATION_ID` — Application ID (например `SRC8UTYBUO`)
   - `NEXT_PUBLIC_ALGOLIA_API_KEY` — Search-Only API key
   - `NEXT_PUBLIC_ALGOLIA_AGENT_ID` — ID агента из Agent Studio
5. **Deploy**.

После деплоя чат будет доступен по ссылке вида `https://your-project.vercel.app`.

## Безопасность

В браузере доступны только переменные с префиксом `NEXT_PUBLIC_*`. Используется **Search-Only API key** Algolia — он предназначен для клиента и ограничивается настройками ACL в дашборде Algolia.
