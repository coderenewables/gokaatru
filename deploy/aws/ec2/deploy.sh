#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/gokaatru}"
RUN_USER="${RUN_USER:-$USER}"

echo "Deploying GoKaatru from: ${APP_DIR}"
cd "${APP_DIR}"

if [[ ! -f .env.production ]]; then
  echo "Missing .env.production in ${APP_DIR}"
  echo "Create it from .env.production.example before deploying."
  exit 1
fi

set -a
source .env.production
set +a

if [[ -z "${DOMAIN:-}" || -z "${LETSENCRYPT_EMAIL:-}" ]]; then
  echo "DOMAIN and LETSENCRYPT_EMAIL must be set in .env.production"
  exit 1
fi

echo "[1/7] Preparing Python virtual environment"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip setuptools wheel
./.venv/bin/pip install -e ".[ml]"

echo "[2/7] Building frontend assets"
cd frontend
npm ci
npm run build
cd "${APP_DIR}"

echo "[3/7] Installing systemd service for API"
sudo tee /etc/systemd/system/gokaatru-api.service >/dev/null <<EOF
[Unit]
Description=GoKaatru FastAPI Service
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env.production
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[4/7] Installing systemd service for MCP SSE"
sudo tee /etc/systemd/system/gokaatru-mcp.service >/dev/null <<EOF
[Unit]
Description=GoKaatru MCP SSE Service
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env.production
ExecStart=${APP_DIR}/.venv/bin/python -m server.main --transport sse --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[5/7] Writing Caddy reverse-proxy config"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMAIN} {
  encode zstd gzip
  tls ${LETSENCRYPT_EMAIL}

  @api path /api/*
  reverse_proxy @api 127.0.0.1:8000

  @mcp path /sse /sse/*
  reverse_proxy @mcp 127.0.0.1:8080

  root * ${APP_DIR}/frontend/dist
  try_files {path} /index.html
  file_server
}
EOF

echo "[6/7] Reloading and starting services"
sudo systemctl daemon-reload
sudo systemctl enable gokaatru-api gokaatru-mcp caddy
sudo systemctl restart gokaatru-api gokaatru-mcp caddy

echo "[7/7] Deployment status"
sudo systemctl --no-pager --full status gokaatru-api | sed -n '1,12p'
sudo systemctl --no-pager --full status gokaatru-mcp | sed -n '1,12p'
sudo systemctl --no-pager --full status caddy | sed -n '1,12p'

echo "Deployment complete"
echo "App URL: https://${DOMAIN}"
