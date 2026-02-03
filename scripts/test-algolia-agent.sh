#!/usr/bin/env bash
# Проверка Algolia Agent Studio API: отправка вопроса агенту и вывод ответа.
# По умолчанию используется stream=true (рекомендуется для gpt-5 — избегает 504).
# Требуется: ALGOLIA_APPLICATION_ID и ALGOLIA_API_KEY (Search-Only или Admin).
# Использование:
#   ./scripts/test-algolia-agent.sh
#   ./scripts/test-algolia-agent.sh "Ваш вопрос"
#   ALGOLIA_AGENT_STREAM=0 ./scripts/test-algolia-agent.sh   # без стрима (может дать 504)
# Или положите переменные в .env в корне проекта.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

APP_ID="${ALGOLIA_APPLICATION_ID:-src8utybuo}"
API_KEY="${ALGOLIA_API_KEY}"
AGENT_ID="${ALGOLIA_AGENT_ID:-1feae05a-7e87-4508-88c8-2d7da88e30de}"
QUESTION="${1:-Как загрузить видео?}"
USE_STREAM="${ALGOLIA_AGENT_STREAM:-1}"

if [[ -z "$API_KEY" ]]; then
  echo "Ошибка: задайте ALGOLIA_API_KEY (в .env или export)." >&2
  echo "Пример: export ALGOLIA_API_KEY=your_search_only_api_key" >&2
  exit 1
fi

STREAM_PARAM="stream=true"
[[ "$USE_STREAM" = "0" ]] && STREAM_PARAM="stream=false"
URL="https://${APP_ID}.algolia.net/agent-studio/1/agents/${AGENT_ID}/completions?${STREAM_PARAM}&compatibilityMode=ai-sdk-5"
echo "Запрос к агенту: $QUESTION"
echo "---"

# Экранируем вопрос для JSON (поддержка без jq)
QUESTION_JSON="${QUESTION//\\/\\\\}"
QUESTION_JSON="${QUESTION_JSON//\"/\\\"}"
QUESTION_JSON="${QUESTION_JSON//$'\n'/\\n}"
BODY="{\"messages\": [{\"role\": \"user\", \"parts\": [{\"text\": \"$QUESTION_JSON\"}]}]}"

if [[ "$USE_STREAM" = "0" ]]; then
  RESP=$(curl -s -m 120 -w "\nHTTP_CODE:%{http_code}" -X POST "$URL" \
    -H "Content-Type: application/json" \
    -H "x-algolia-application-id: $APP_ID" \
    -H "x-algolia-api-key: $API_KEY" \
    --data-raw "$BODY")
  HTTP_BODY="${RESP%HTTP_CODE:*}"
  HTTP_CODE="${RESP##*HTTP_CODE:}"
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "HTTP $HTTP_CODE" >&2
    echo "$HTTP_BODY" | jq -r . 2>/dev/null || echo "$HTTP_BODY"
    exit 1
  fi
  echo "$HTTP_BODY" | jq -r '
    if .parts then (.parts[] | select(.type == "text") | .text) // empty
    else .content // . end
  ' 2>/dev/null || echo "$HTTP_BODY"
else
  TMP_STREAM=$(mktemp)
  trap 'rm -f "$TMP_STREAM"' EXIT
  if ! curl -s -m 120 -N -X POST "$URL" \
    -H "Content-Type: application/json" \
    -H "x-algolia-application-id: $APP_ID" \
    -H "x-algolia-api-key: $API_KEY" \
    --data-raw "$BODY" > "$TMP_STREAM"; then
    echo "Ошибка запроса или таймаут." >&2
    exit 1
  fi
  python3 -c "
import json, sys
p = sys.argv[1]
out = []
for line in open(p):
    if line.startswith('data: '):
        try:
            d = json.loads(line[6:].strip())
            if d.get('type') == 'text-delta' and 'delta' in d:
                out.append(d['delta'])
        except: pass
sys.stdout.write(''.join(out))
" "$TMP_STREAM"
fi
