#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/gokaatru}"
BRANCH="${BRANCH:-main}"

echo "Updating GoKaatru in ${APP_DIR} (branch: ${BRANCH})"
cd "${APP_DIR}"

git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

bash ./deploy/aws/ec2/deploy.sh
