#!/usr/bin/env bash
# Проиндексировать все .md из docs_crawl в Algolia.
# Требуется: ALGOLIA_APPLICATION_ID и ALGOLIA_API_KEY (или ALGOLIA_WRITE_API_KEY) в .env.
# Usage: ./scripts/algolia-index.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a && source "$PROJECT_ROOT/.env" && set +a
fi
# Для индексации нужен write key; если задан ALGOLIA_WRITE_API_KEY — используем его
if [[ -n "${ALGOLIA_WRITE_API_KEY:-}" ]]; then
  export ALGOLIA_API_KEY="$ALGOLIA_WRITE_API_KEY"
fi

DOCS_DIR="${DOCS_DIR:-$PROJECT_ROOT/docs_crawl}"
AGENT_DIR="$PROJECT_ROOT/algolia-agent"

if [[ ! -d "$DOCS_DIR" ]]; then
  echo "DOCS_DIR not found: $DOCS_DIR. Run crawl first: python scripts/crawl_docs.py"
  exit 1
fi

if [[ ! -f "$AGENT_DIR/algolia-agent" ]]; then
  echo "Building algolia-agent..."
  (cd "$AGENT_DIR" && go build -o algolia-agent .)
fi

export ALGOLIA_DOCS_DIR="$DOCS_DIR"
export ALGOLIA_INDEX_NAME="${ALGOLIA_INDEX_NAME:-kinescope_docs}"
cd "$AGENT_DIR"
./algolia-agent index
