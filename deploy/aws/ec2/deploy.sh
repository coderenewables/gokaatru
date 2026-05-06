#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/gokaatru}"

echo "Deploying GoKaatru from: ${APP_DIR}"
cd "${APP_DIR}"

if [[ ! -f .env.production ]]; then
  echo "Missing .env.production in ${APP_DIR}"
  echo "Create it from .env.production.example before deploying."
  exit 1
fi

docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

echo "Deployment complete"
docker compose --env-file .env.production -f docker-compose.prod.yml ps
