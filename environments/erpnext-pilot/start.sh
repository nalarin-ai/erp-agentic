#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ENV_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Generate synthetic secrets first." >&2
  exit 1
fi

source .env

echo "=== ERPNext Pilot Environment ==="
echo "SITE_NAME: ${SITE_NAME}"
echo "ADMIN_PASSWORD: [REDACTED]"
echo "DB_ROOT_PASSWORD: [REDACTED]"
echo ""

echo "--- 1. Starting MariaDB + Redis ---"
docker compose up -d mariadb redis-cache redis-queue

echo "--- 2. Waiting for MariaDB ---"
for i in $(seq 1 30); do
  if docker exec erpnext-pilot-db mariadb-admin ping -h 127.0.0.1 -u root -p"${DB_ROOT_PASSWORD}" 2>/dev/null; then
    echo "MariaDB ready after ${i}s"
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "ERROR: MariaDB not ready after 30s" >&2
    exit 1
  fi
  sleep 1
done

echo "--- 3. Creating site ---"
docker compose up create-site

echo "--- 4. Starting backend ---"
docker compose up -d backend

echo "--- 5. Health check ---"
for i in $(seq 1 60); do
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:18080/api/method/ping" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    echo "ERPNext API healthy after ${i}s (HTTP ${HTTP})"
    break
  fi
  if [[ $i -eq 60 ]]; then
    echo "ERROR: ERPNext not healthy after 60s (last HTTP ${HTTP})" >&2
    docker compose logs --tail 50 backend
    exit 1
  fi
  sleep 1
done

echo ""
echo "=== PILOT READY ==="
echo "URL: http://127.0.0.1:18080"
echo "Site: ${SITE_NAME}"
echo "Admin: administrator / [REDACTED]"
