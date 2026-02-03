#!/usr/bin/env bash
# Собрать Algolia agent и скопировать на VPS. Не запускает сервис — только sync.
# На VPS задайте ALGOLIA_APPLICATION_ID и ALGOLIA_API_KEY (в .env или systemd).
# Usage: ./scripts/deploy-algolia-agent.sh [--build-linux]
set -e

VPS_HOST="${VPS_HOST:-gdrant-agent}"
REMOTE_DIR="${REMOTE_DIR:-/opt/rag-chat}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$PROJECT_ROOT/algolia-agent"

build_linux=0
for arg in "$@"; do
  [[ "$arg" == "--build-linux" ]] && build_linux=1
done

echo "==> Building algolia-agent ..."
cd "$AGENT_DIR"
if [[ "$build_linux" -eq 1 ]]; then
  GOOS=linux GOARCH=amd64 go build -o algolia-agent .
else
  go build -o algolia-agent .
fi

echo "==> Syncing algolia-agent to $VPS_HOST:$REMOTE_DIR/algolia-agent ..."
rsync -avz --exclude '.git' "$AGENT_DIR/" "$VPS_HOST:$REMOTE_DIR/algolia-agent/"

echo "Done. On VPS: cd $REMOTE_DIR/algolia-agent && ALGOLIA_APPLICATION_ID=... ALGOLIA_API_KEY=... ./algolia-agent"
