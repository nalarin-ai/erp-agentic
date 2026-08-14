#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ENV_DIR"

echo "=== ERPNext Pilot Teardown ==="
docker compose down -v --remove-orphans 2>/dev/null || true
docker rm -f erpnext-pilot-db erpnext-pilot-redis-cache erpnext-pilot-redis-queue erpnext-pilot-create-site erpnext-pilot-backend 2>/dev/null || true
echo "Teardown complete."
