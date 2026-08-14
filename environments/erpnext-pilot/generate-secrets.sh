#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ENV_DIR"

if [[ -f .env ]]; then
  echo "ERROR: .env already exists. Remove it first to regenerate." >&2
  exit 1
fi

SITE_NAME="erpnext-pilot.localhost"
DB_ROOT_PASSWORD=$(openssl rand -hex 32)
ADMIN_PASSWORD=$(openssl rand -hex 32)

cat > .env <<ENVEOF
SITE_NAME=${SITE_NAME}
DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ENVEOF

chmod 600 .env
echo "Synthetic secrets generated in ${ENV_DIR}/.env (mode 600)"
echo "SITE_NAME=${SITE_NAME}"
