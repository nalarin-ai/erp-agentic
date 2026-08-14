# Backup & Restore Runbook (OPS-001)

Status: `PILOT_STAGE` — fixture drill fully automated; pilot drill guarded.
Requirements: R-008, R-009, R-016. Architecture: §8 (observability), §9
(backup and recovery).

## Recovery targets (chosen defaults, pilot stage)

| Target | Value | Note |
|---|---|---|
| RPO | **24 hours** (`rpo_target_seconds=86400`) | Daily backup cadence. |
| RTO | **4 hours** (`rto_target_seconds=14400`) | Restore + verify within one working half-day. |

Production tightening of these targets is an **owner decision** (requires
qualified review per R-009) and must be re-recorded in the manifest defaults
and here before production use.

## Covered stores (ARCHITECTURE.md §9)

| Store | Fixture source | Pilot source |
|---|---|---|
| `erp_db` | `tests/operations/fixtures/erp_db/` | `mariadb-dump --all-databases` inside `erpnext-pilot-db` |
| `erp_private_files` | `tests/operations/fixtures/erp_private_files/` | `erpnext-pilot_sites` volume, `*/private/` subtree |
| `app_config` | `tests/operations/fixtures/app_config/` | synthetic snapshot (operator-maintained) |
| `audit_state` | `tests/operations/fixtures/audit_state/` | synthetic snapshot (operator-maintained) |

Each backup produces `manifest.json` (canonical JSON, content-bound
`manifest_hash`), `SHA256SUMS`, and one `artifacts/<store>.tar.gz` per store.

## Fixture drill (no pilot required, safe anywhere)

```bash
# 1. Backup
python3 -m scripts.backup.backup_run --mode fixture --out /tmp/ops-drill

# 2. Restore + verify (checksums, extraction, cross-store reconciliation)
python3 -m scripts.backup.restore_verify \
  --manifest /tmp/ops-drill/manifest.json --target /tmp/ops-drill-restored
# Expect final line: RESTORE_OK stores=4 manifest=BKUP-...
```

Reconciliation checks performed on restore:
- `record_counts` — `audit_state/record_counts.json` parses; `erp_db_rows`
  matches the `fixture-record-count` marker in the restored DB dump.
- `audit_head` — `audit_state/audit_head.txt` carries a well-formed
  `sha256:<hex64>` chain head.
- `config_version` — `app_config/config_version.txt` matches
  `site_config.json`.

## Pilot drill (isolated local pilot only)

Preconditions: pilot started via `environments/erpnext-pilot/start.sh`
(containers `erpnext-pilot-db` and `erpnext-pilot-backend` running).

```bash
python3 -m scripts.backup.backup_run \
  --mode pilot --i-understand-local-only --out /tmp/ops-pilot-backup
python3 -m scripts.backup.restore_verify \
  --manifest /tmp/ops-pilot-backup/manifest.json --target /tmp/ops-pilot-restored
```

Guardrails (fail-closed, exit code 2):
- Without `--i-understand-local-only` the runner refuses.
- If either pilot container is down, the runner refuses and writes no
  partial manifest.
- The DB root password is read from the pilot's local `.env` (git-ignored)
  and piped to the container shell via stdin (`docker exec -i sh -s`); it
  never appears in any host argv element (`ps`/procfs safe) and must never
  be printed or committed.
- `erp_private_files` may legitimately be empty pre-production; the
  manifest records `allow_empty`/`empty` explicitly and restore accepts
  the empty archive only under that marker (fail-closed otherwise).
- `app_config` is a REAL capture of the pilot `site_config.json` /
  `common_site_config.json` / `apps.json` with secret-valued keys redacted
  to `[REDACTED]`; `audit_state` is a real per-table `COUNT(*)` capture
  (no row data leaves the DB) whose `audit_head.txt` pins the exact bytes
  of `record_counts.json`. Manifest per-store `source: pilot` distinguishes
  these from fixture-drill artifacts. Note: live site configs carry no
  `config_version` key; restore records this as `pilot-captured`.
- `RPO/RTO = 0` is formally valid in the manifest schema but operationally
  meaningless; always set the chosen targets above.

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| Corrupt backup artifact | `checksum:<store>` FAIL on restore | Restore from previous backup; investigate storage medium. |
| Truncated archive | `extract:<store>` FAIL | Same as above; verify transfer integrity. |
| Manifest/artifact mismatch | `checksum:<store>` FAIL (sha256 mismatch) | Treat as tamper or incomplete upload; quarantine the backup set. |
| Missing reconciliation data | `check:record_counts`/`audit_head`/`config_version` FAIL naming the check | Restore is NOT application-consistent; do not promote the restored environment. |
| Undecryptable backup | (production only — see checklist) | Key recovery procedure; drill quarterly. |
| Version incompatible backup | Restore into wrong app version | Restore into matching version, then migrate forward. |
| Storage pressure on backup host | Backup fails before manifest write; no partial manifest | Free space; re-run; alert if consecutive failures exceed RPO. |
| Pilot containers down | Backup exit 2, refusal message | Start pilot via `start.sh` or accept fixture-only drill. |

## Observability (ARCHITECTURE.md §8)

Ops events are built by `ops/observability.py`: `backup_started`,
`backup_succeeded`, `backup_failed`, `restore_drill`. Each carries
correlation ID, actor alias, unit, action class, record alias, result,
latency, and a redacted error descriptor (sensitive keys such as
`password`/`token` are replaced with `[REDACTED]`).

## Production requirements checklist — NOT-YET-DONE

These are mandatory before production use (R-009) and are **not**
implemented at this stage:

- [ ] **Encryption at rest** — manifests currently record
  `encryption: none`; artifacts are plaintext tarballs.
- [ ] **Off-host immutable copy** — at least one copy outside the backup
  host (object-lock/WORM storage) per ARCHITECTURE.md §9.
- [ ] **Encryption-key recovery procedure** — documented key escrow and a
  rehearsed undecryptable-backup drill.
- [ ] **Isolated identity/network restore environment** — restore target
  with separate credentials and network segment.
- [ ] **Measured RPO/RTO evidence** — timed drills recorded in
  `docs/evidence/`.
- [ ] **Host-loss drill** — restore onto a fresh host from off-host copy.
