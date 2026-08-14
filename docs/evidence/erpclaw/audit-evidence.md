# ERPClaw Audit Evidence — EVAL-003

> Generated: `2026-08-14`
> Source: GitHub API + raw file fetch (read-only, no clone, no credential)
> Repository: `avansaber/erpclaw` @ `v4.1.2`

## Repository metadata (GitHub API)

```json
{
  "full_name": "avansaber/erpclaw",
  "html_url": "https://github.com/avansaber/erpclaw",
  "default_branch": "main",
  "license": "GPL-3.0",
  "language": "Python",
  "created_at": "2026-02-27T06:39:22Z",
  "updated_at": "2026-08-12T21:21:21Z",
  "pushed_at": "2026-07-27T15:41:54Z",
  "stargazers_count": 90,
  "forks_count": 27,
  "open_issues_count": 2,
  "visibility": "public",
  "archived": false,
  "disabled": false
}
```

## Tags (GitHub API)

| Tag | Commit |
|---|---|
| v4.1.2 | 8cd0b70 |
| v4.1.1 | ce7018a |
| v4.1.0 | 98e5ebc |
| v4.0.2 | 6398826 |
| v4.0.1 | 1b83f66 |
| v4.0.0 | a00ba7e |
| v3.5.1 | 47c91a6 |
| v3.5.0 | 4ee0ba0 |
| v1.0.0 | 02197ed |

## SKILL.md (v4.1.2)

- `name: erpclaw`, `version: 4.1.2`
- `description`: AI-native ERP system. 467 actions across 14 domains, 43 optional expansion modules.
- `author: AvanSaber`
- `metadata.openclaw.requires.bins`: `python3`, `git`
- `metadata.openclaw.optionalEnv`: `ERPCLAW_DB_PATH`
- `metadata.openclaw.os`: `darwin`, `linux`
- Runtime gate: write actions require `--user-confirmed` flag; read-only actions do not.

## Repository structure (v4.1.2)

Top-level: `bin/erpclaw`, `scripts/`, `README.md`, `SKILL.md`, `LICENSE.txt`, `CHANGELOG.md`, `UI.yaml`

Scripts subdirectories:
- `erpclaw-accounting-adv`, `erpclaw-billing`, `erpclaw-buying`, `erpclaw-gl`, `erpclaw-hr`, `erpclaw-inventory`, `erpclaw-journals`, `erpclaw-meta`, `erpclaw-os`, `erpclaw-payments`, `erpclaw-payroll`, `erpclaw-reports`, `erpclaw-selling`, `erpclaw-setup`, `erpclaw-tax`

Shared library: `scripts/erpclaw-setup/lib/erpclaw_lib/`
- `__init__.py`, `args.py`, `audit.py`, `credentials.py`, `cross_skill.py`, `crypto.py`, `csv_import.py`, `custom_fields.py`, `datetime_utils.py`, `db.py`, `decimal_utils.py`, `dependencies.py`, `encrypted_columns.py`, `fx_posting.py`, `gl_invariants.py`, `gl_posting.py`, `master_key.py`, `naming.py`, `pagination.py`, `passwords.py`, `query.py`, `query_helpers.py`, `rbac.py`, `response.py`, `stock_posting.py`, `tax_calculation.py`, `validation.py`

## Key file contents

### `scripts/erpclaw-setup/lib/erpclaw_lib/audit.py`

```python
def audit(conn, skill: str, action: str, entity_type: str, entity_id: str,
          old_values=None, new_values=None, description: str = ""):
    conn.execute(
        """INSERT INTO audit_log (id, user_id, skill, action, entity_type, entity_id,
           old_values, new_values, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), os.environ.get("OPENCLAW_USER"), skill, action,
         entity_type, entity_id,
         json.dumps(old_values) if old_values else None,
         json.dumps(new_values) if new_values else None,
         description),
    )
```

**Observation:** Standard SQLite INSERT; no cryptographic chaining, no immutability enforcement, no hash linking.

### `scripts/erpclaw-setup/lib/erpclaw_lib/gl_invariants.py`

Post-test verification of GL invariants:
1. Global balance: SUM(debit) == SUM(credit) across non-cancelled entries
2. Per-voucher balance
3. No zero-zero entries
4. Valid accounts
5. Valid fiscal year

Uses `Decimal` with tolerance `0.001`. Result: `pass`/`fail`/`skip`.

**Observation:** Invariants are checked *after* the fact, not enforced as database constraints during posting.

### `scripts/erpclaw-setup/lib/erpclaw_lib/rbac.py`

- `check_permission(conn, user_id, skill, action)` → `bool`
- `require_permission(conn, user_id, skill, action)` → raises on deny
- `get_user_companies(conn, user_id)` → `list[str]`
- `get_user_roles(conn, user_id, company_id=None)` → `list[dict]`
- `resolve_telegram_user(conn, telegram_username)` → `Optional[str]`

Permission resolution order:
1. No `erp_user` record → allow (RBAC not enforced)
2. `System Manager` role → always allow
3. Check `role_permission` for `(skill, action_pattern)`
4. Wildcard patterns: `submit-*`, `list-*`, `*`
5. No match → deny

**Observation:** RBAC is opt-in and application-level only. No database-level row security.

## Limitations of this audit

- Audit is based on GitHub API + raw file fetch; no local clone or runtime execution.
- No database schema was inspected beyond what is visible in Python code.
- No test suite was run.
- The 43 optional modules were not individually audited.
- PostgreSQL support claimed in README was not verified in code.
