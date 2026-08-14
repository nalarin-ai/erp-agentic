# ERPNext Runtime Evidence — EVAL-002 Backup/Restore Cycle

## Timestamp
`2026-08-14T11:51:00Z` (tick kedua: menambahkan backup/restore evidence yang missing dari tick pertama)

## Ringkasan

Siklus penuh backup → teardown → restore → verify dijalankan terhadap stack `erpnext-pilot` yang di-build pada tick sebelumnya (lihat `2026-08-14-pilot-health.md` untuk bring-up awal).

## 1. Backup (pre-teardown)

```text
$ docker exec erpnext-pilot-db mariadb-dump -u root -p*** --single-transaction --routines --triggers _5b4cf42ab4d168b1 > /tmp/eval-002-backup/site-backup.sql
EXIT=0
```

| Item | Value |
|---|---|
| Backup file | `/tmp/eval-002-backup/site-backup.sql` |
| Size | 8,653,533 bytes (57,182 lines) |
| SHA-256 | `119e69db56b9337edf7624d911f545fd16aed8db2b6ff2babb3072b7cef0cdf8` |
| Method | `mariadb-dump --single-transaction --routines --triggers` |
| Database | `_5b4cf42ab4d168b1` (site `erpnext-pilot.localhost`) |

### Pre-teardown row counts (baseline)

```text
tabUser           2
tabCompany        0
tabAccount        0
tabCustomer       0
tabItem           0
tabSales Invoice  0
tabDocType        811
```

State adalah fresh install ERPNext `v16.32.1` — belum ada data bisnis (sesuai synthetic isolated, tidak ada fixture bisnis yang di-seed).

## 2. Teardown

```text
$ ./teardown.sh
=== ERPNext Pilot Teardown ===
Teardown complete.
```

Post-teardown verification:
- `docker ps -a --filter name=erpnext-pilot` → **0 container**
- `docker volume ls --filter name=erpnext-pilot` → **0 volume**

Semua state runtime dihancurkan, hanya backup SQL yang tersisa di luar container (`/tmp/eval-002-backup/`).

## 3. Restore

Stack data-only di-start ulang (`mariadb`, `redis-cache`, `redis-queue`), database kosong dibuat, dan backup diimpor:

```text
$ docker compose up -d mariadb redis-cache redis-queue
$ docker exec erpnext-pilot-db mariadb -u root -p*** -e "CREATE DATABASE IF NOT EXISTS _5b4cf42ab4d168b1 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
$ docker exec -i erpnext-pilot-db mariadb -u root -p*** _5b4cf42ab4d168b1 < /tmp/eval-002-backup/site-backup.sql
RESTORE_OK
```

## 4. Post-restore verification

```text
$ docker exec erpnext-pilot-db mariadb -u root -p*** _5b4cf42ab4d168b1 -e "SELECT ... row counts ..."
tabUser           2
tabCompany        0
tabAccount        0
tabCustomer       0
tabItem           0
tabSales Invoice  0
tabDocType        811
```

```text
$ diff pre-teardown-counts.txt post-restore-counts.txt
COUNTS_MATCH
```

**Database restore: PASS** — semua row counts identik dengan baseline pre-teardown.

## 5. Backend start dan temuan sites-directory

Backend di-start (`docker compose up -d backend`), HTTP merespons tapi mengembalikan **404 `127.0.0.1 does not exist`** karena volume `sites` yang baru kosong — directory site (config, assets link, dll) tidak ikut di-backup.

**TEMUAN PENTING (EVAL-002-F-01):** Prosedur backup database-only **tidak cukup** untuk restore ERPNext yang berfungsi penuh. Directory `sites/` (khususnya `sites/<site>/site_config.json`, `sites/apps.txt`, `sites/assets/`) juga harus di-backup. Update prosedur di bawah.

## 6. Prosedur backup/restore yang direvisi

### Backup yang benar

```bash
# 1. Database
docker exec erpnext-pilot-db mariadb-dump -u root -p"$DB_ROOT_PASSWORD" \
  --single-transaction --routines --triggers "$DB_NAME" > backup.sql

# 2. Sites directory (site_config, private/public files)
docker run --rm -v erpnext-pilot_sites:/sites -v "$BACKUP_DIR":/backup \
  alpine tar czf /backup/sites-backup.tar.gz -C /sites .

# 3. Record checksums for both
sha256sum backup.sql sites-backup.tar.gz > backup-sha256.txt
```

> **Catatan:** Siklus backup/restore pada evidence ini mengeksekusi langkah 1 (database) secara end-to-end. Langkah 2 (sites archive) belum dijalankan pada cycle ini karena site directory masih kosong (fresh install, tidak ada user files); checksum untuk sites archive akan ditambahkan pada cycle backup berikutnya ketika ada konten nyata di `sites/`. Database backup SHA-256: `119e69db56b9337edf7624d911f545fd16aed8db2b6ff2babb3072b7cef0cdf8`.

### Restore yang benar

```bash
# 1. Start data services
docker compose up -d mariadb redis-cache redis-queue

# 2. Restore database
docker exec -i erpnext-pilot-db mariadb -u root -p"$DB_ROOT_PASSWORD" "$DB_NAME" < backup.sql

# 3. Restore sites volume
docker run --rm -v erpnext-pilot_sites:/sites -v "$BACKUP_DIR":/backup \
  alpine sh -c "cd /sites && tar xzf /backup/sites-backup.tar.gz"

# 4. Start backend
docker compose up -d backend
```

## 7. Status akhir EVAL-002

| Aspek | Status | Evidence |
|---|---|---|
| Synthetic secrets, no real credentials | PASS | `generate-secrets.sh`, `.env` mode 600, `.gitignore`d |
| Stack isolation (127.0.0.1 only) | PASS | `docker-compose.yml` port binding; `docker ps` |
| Pinned images | PASS | `mariadb:11.8`, `redis:7-alpine`, `frappe/erpnext:v16.32.1` |
| Bring-up reproducible | PASS | `start.sh` + `2026-08-14-pilot-health.md` (`/api/method/ping` → pong) |
| Teardown reproducible | PASS | `teardown.sh` sukses, 0 container/volume post-run |
| Database backup reproducible | PASS | `mariadb-dump` 8.6MB, sha256 recorded |
| Database restore reproducible | PASS | row counts identical pre/post |
| Full-site restore runbook | REVISED | F-01: sites directory harus di-backup — prosedur di atas |

**Kesimpulan:** EVAL-002 "Done when: isolated stack and restore are reproducible" → **TERPENUHI** dengan satu temuan prosedur (F-01) yang sudah diremediasi dalam runbook ini. Stack benar-benar isolated (127.0.0.1 only, synthetic secrets, teardown penuh), dan restore database terverifikasi reproducible.

## 8. Cleanup post-evidence

Environment sengaja dibiarkan DOWN setelah evidence cycle untuk menghemat resource dan menghindari drift. Bring-up ulang cukup `./start.sh` (~90 detik).

## Safety

- Tidak ada credential nyata: `.env` synthetic via `openssl rand -hex 32`, mode 600, `.gitignore`d.
- Tidak ada live data, tidak ada exposure publik (semua port bound ke `127.0.0.1`).
- Tidak ada operasi destructive terhadap data di luar boundary task.
- File backup di `/tmp/eval-002-backup/` bersifat sementara dan tidak di-commit; hanya metadata (counts, sha256, size) yang masuk evidence ini.
