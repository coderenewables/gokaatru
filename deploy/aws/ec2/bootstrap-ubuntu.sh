#!/usr/bin/env bash
set -euo pipefail

echo "[1/6] Updating apt index"
sudo apt-get update -y

echo "[2/6] Installing base packages"
sudo apt-get install -y git curl ca-certificates gnupg python3 python3-venv python3-pip build-essential

echo "[3/6] Installing Node.js 20"
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "[4/6] Installing Caddy"
sudo apt-get install -y caddy

echo "[5/6] Enabling Caddy service"
sudo systemctl enable --now caddy

echo "[6/6] Bootstrap complete"
echo "Python, Node.js, and Caddy are ready."
