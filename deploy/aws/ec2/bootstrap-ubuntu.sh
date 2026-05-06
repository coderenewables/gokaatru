#!/usr/bin/env bash
set -euo pipefail

echo "[1/5] Updating apt index"
sudo apt-get update -y

echo "[2/5] Installing Docker, Compose plugin, Git"
sudo apt-get install -y docker.io docker-compose-plugin git

echo "[3/5] Enabling Docker service"
sudo systemctl enable --now docker

echo "[4/5] Allowing current user to run Docker"
sudo usermod -aG docker "$USER"

echo "[5/5] Bootstrap complete"
echo "Log out and back in once so Docker group membership applies."
