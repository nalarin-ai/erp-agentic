#!/usr/bin/env python3
"""Fail-closed structural plan-gate validator for ERP Kreasi Hebat."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parent.parent
PC = ROOT / "project-control"
REQUIRED = {
    "PROJECT.md", "PRD.md", "REQUIREMENTS.md", "ARCHITECTURE.md", "DATA_MODEL.md",
    "RBAC_AND_POLICY.md", "UX_DISCOVERY.md", "UX_SPEC.md", "ROADMAP.md",
    "EXECUTION_PLAN.md", "TEST_STRATEGY.md", "RISK_REGISTER.md", "DECISIONS.md",
    "OPEN_QUESTIONS.md", "TASK_QUEUE.md", "PLAN_REVIEW.md", "PLAN_GATE.md", "STATUS.md",
    "LOCK.md", "TRACEABILITY_MATRIX.md", "STATE_MACHINES.md",
    "IDEMPOTENCY_AUDIT_RECOVERY.md", "NATIVE_ERP_ISOLATION.md",
    "DUPLICATE_PAYMENT_POLICY.md", "project-policy.json", "full-auto-standing-approval.json",
}
POLICY_KEYS = {
    "schema_version", "project_id", "profile_id", "repository_path", "worktree_path",
    "telegram_bot", "telegram_chat", "authorized_bos_id", "approval_policy",
    "protected_actions", "prohibited_actions", "status",
}
APPROVAL_KEYS = {
    "schema_version", "policy", "project_id", "profile_id", "repository_path",
    "worktree_path", "repository_boundary", "telegram_bot", "telegram_chat",
    "telegram_identity_ref", "authorized_bos_id", "activated_at", "activation_source",
    "status", "revoked_at",
}
REQUIRED_PROTECTED = {
    "CHANGESET", "COMMIT", "PUSH", "PR_CREATE", "MERGE", "DEPLOY", "RESTART",
    "MIGRATION", "DESTRUCTIVE_DATA", "CREDENTIAL", "SPENDING",
}
REQUIRED_PROHIBITED = {
    "PRODUCTION_DEPLOY_BEFORE_PROD_001_APPROVED",
    "LIVE_DATA_IMPORT_BEFORE_MIGRATION_GATE_PASS",
    "OFFICIAL_FINANCIAL_POSTING_BEFORE_PROD_001_APPROVED",
    "BANKING_PAYMENT_EXECUTION", "AUTOMATED_TAX_FILING_OR_SUBMISSION",
    "CREDENTIAL_VALUE_IN_CHAT_SOURCE_LOG_OR_PROJECT_CONTROL",
    "CREDENTIAL_CREATE_OR_ROTATE_WITHOUT_TESTED_RUNBOOK",
    "SPENDING_WITHOUT_RECORDED_NONZERO_CLASS_LIMIT",
    "DESTRUCTIVE_FINANCIAL_DATA_HARD_DELETE",
    "DESTRUCTIVE_DATA_ACTION_WITHOUT_VERIFIED_BACKUP_AND_RESTORE_RUNBOOK",
    "PUBLIC_EXPOSURE_BEFORE_SECURITY_READINESS_PASS",
}
CANONICAL_TASKS = {
    "SEC-001", "PLAN-001", "EVAL-001", "EVAL-002", "EVAL-003",
    "FND-001", "FND-002", "FND-003", "FND-004", "UNIT-001",
    "ADP-001", "REC-001", "ADP-002", "CRM-001", "ISO-001", "ISOFIX-001",
    "FLOW-001", "FLOW-002", "FLOW-003", "REM-001", "RPT-001", "UX-001",
    "MIG-001", "MIGSRC-001", "OPS-001", "PILOT-001", "INT-001",
    "MIGDEC-001", "EXP-001", "PROD-001",
}
REQUIRED_EDGES = {
    ("ISO-001", "ISOFIX-001"),
    ("ISOFIX-001", "PILOT-001"),
    ("PILOT-001", "PROD-001"),
    ("MIGDEC-001", "PROD-001"),
    ("EXP-001", "PROD-001"),
}
EXPECTED_STATUS = {
    "SEC-001": "DONE", "PLAN-001": "DONE",
    "EVAL-001": "DONE", "EVAL-002": "DONE", "EVAL-003": "BACKLOG_OPTIONAL",
    "FND-001": "DONE", "FND-002": "DONE", "FND-003": "DONE", "FND-004": "DONE",
    "UNIT-001": "DONE", "ADP-001": "DONE", "REC-001": "DONE", "ADP-002": "DONE",
    "CRM-001": "DONE", "ISO-001": "BACKLOG", "ISOFIX-001": "BACKLOG",
    "FLOW-001": "DONE", "FLOW-002": "DONE", "FLOW-003": "DONE",
    "REM-001": "BACKLOG_POST_MVP", "RPT-001": "READY", "UX-001": "BACKLOG",
    "MIG-001": "DONE", "MIGSRC-001": "BLOCKED_OWNER_INPUT", "OPS-001": "BACKLOG",
    "PILOT-001": "BACKLOG", "INT-001": "BACKLOG_POST_MVP",
    "MIGDEC-001": "BLOCKED_OWNER_INPUT", "EXP-001": "BLOCKED_OWNER_EXPERT",
    "PROD-001": "BLOCKED_OWNER_EXPERT",
}

EXPECTED_OWNED_PATHS = {'ADP-001': ['src/adapters/fixture/**', 'tests/contracts/erp_port/**'],
 'ADP-002': ['src/adapters/erpnext/**', 'tests/integration/erpnext/**'],
 'CRM-001': ['src/crm/**', 'src/adapters/erpnext_crm/**', 'tests/crm/**'],
 'EVAL-001': ['evaluation/erpnext/**', 'docs/evidence/erpnext-audit/**'],
 'EVAL-002': ['environments/erpnext-pilot/**', 'docs/evidence/erpnext-runtime/**'],
 'EVAL-003': ['evaluation/erpclaw/**', 'environments/erpclaw-pilot/**', 'docs/evidence/erpclaw/**'],
 'EXP-001': ['docs/evidence/qualified-review/**', 'project-control/PRODUCTION_READINESS.md'],
 'FLOW-001': ['src/workflows/invoice_draft/**', 'src/channels/**', 'tests/workflows/invoice_draft/**'],
 'FLOW-002': ['src/workflows/invoice_post/**', 'tests/workflows/invoice_post/**'],
 'FLOW-003': ['src/workflows/payments/**', 'src/reports/receivables/**', 'tests/workflows/payments/**'],
 'FND-001': ['src/domain/**', 'src/contracts/**', 'tests/unit/domain/**'],
 'FND-002': ['src/authz/**', 'tests/unit/authz/**'],
 'FND-003': ['src/policy/**', 'tests/unit/policy/**'],
 'FND-004': ['src/mutations/**', 'src/audit/**', 'db/migrations/mutation_audit/**', 'tests/mutation_audit/**'],
 'INT-001': ['src/integrations/specialist/**', 'tests/integrations/specialist/**', 'docs/evidence/integrations/**'],
 'ISO-001': ['tests/security/native_erp/**', 'docs/evidence/native-isolation/**'],
 'ISOFIX-001': ['src/isolation_architecture/**',
                'environments/isolation-final/**',
                'tests/security/isolation_final/**',
                'docs/evidence/isolation-final/**'],
 'MIG-001': ['src/imports/**', 'tests/imports/**'],
 'MIGDEC-001': ['project-control/MIGRATION_DECISION.md'],
 'MIGSRC-001': ['docs/evidence/migration-source/**', 'config/migration-maps/**', 'tests/fixtures/migration-sanitized/**'],
 'OPS-001': ['ops/**', 'scripts/backup/**', 'docs/runbooks/operations/**', 'tests/operations/**'],
 'PILOT-001': ['tests/e2e/pilot/**', 'docs/evidence/pilot/**'],
 'PLAN-001': ['project-control/**', '.hermes/plans/**', 'scripts/validate_plan_gate.py'],
 'PROD-001': ['project-control/PRODUCTION_READINESS.md', 'docs/evidence/production-readiness/**'],
 'REC-001': ['src/reconciliation/**', 'ui/reconciliation/**', 'tests/reconciliation/**', 'docs/runbooks/reconciliation.md'],
 'REM-001': ['src/workflows/reminders/**', 'tests/reminders/**'],
 'RPT-001': ['src/reports/owner/**', 'ui/reports/owner/**', 'tests/reports/owner/**'],
 'SEC-001': ['project-control/project-policy.json', 'project-control/full-auto-standing-approval.json'],
 'UNIT-001': ['src/units/**', 'config/fixtures/units/**', 'tests/units/**'],
 'UX-001': ['ui/invoice_review/**', 'ui/receivables/**', 'tests/ui/**', 'docs/evidence/ux/**']}
EXPECTED_QUEUE_OWNED = {'ADP-001': 'fixture adapter/contracts',
 'ADP-002': 'ERPNext adapter/tests',
 'CRM-001': 'CRM/adapter/tests',
 'EVAL-001': 'ERPNext evaluation/evidence',
 'EVAL-002': 'ERPNext environment/scripts/evidence',
 'EVAL-003': 'isolated comparator/evidence',
 'EXP-001': 'qualified-review/readiness docs',
 'FLOW-001': 'invoice draft/channel/tests',
 'FLOW-002': 'invoice post/tests',
 'FLOW-003': 'payment/receivable/tests',
 'FND-001': 'domain/contracts/unit tests',
 'FND-002': 'authz paths',
 'FND-003': 'policy paths',
 'FND-004': 'mutation/audit/migration/test paths',
 'INT-001': 'specialist integration/test/evidence',
 'ISO-001': 'native security tests/evidence',
 'ISOFIX-001': 'final isolation runtime/source/tests/evidence',
 'MIG-001': 'import/test paths',
 'MIGDEC-001': 'migration decision',
 'MIGSRC-001': 'migration profile/maps/sanitized fixtures',
 'OPS-001': 'ops/backup/runbook/tests',
 'PILOT-001': 'pilot E2E/evidence',
 'PLAN-001': 'control/plans/validator only',
 'PROD-001': 'readiness/evidence only',
 'REC-001': 'reconciliation UI/worker/tests/runbook',
 'REM-001': 'reminders/tests',
 'RPT-001': 'owner report UI/service/tests',
 'SEC-001': 'executor gateway',
 'UNIT-001': 'unit fixture/config paths',
 'UX-001': 'bounded UI/test/evidence paths'}

EXPECTED_REQUIREMENTS = {
    "SEC-001": "R-005, R-007, R-008", "PLAN-001": "R-001..R-022",
    "EVAL-001": "R-005, R-006, R-009, R-016, R-017, R-019", "EVAL-002": "R-005, R-006, R-009, R-016", "EVAL-003": "R-005, R-006, R-009",
    "FND-001": "R-004, R-005, R-006, R-007, R-008, R-017, R-019", "FND-002": "R-003, R-004, R-007, R-011, R-021",
    "FND-003": "R-016, R-017, R-019", "FND-004": "R-007, R-008",
    "UNIT-001": "R-001, R-002, R-012, R-013, R-014, R-015, R-018, R-020, R-021, R-022", "ADP-001": "R-005, R-006, R-007, R-008, R-017",
    "REC-001": "R-007, R-008", "ADP-002": "R-005, R-006, R-007, R-008, R-016, R-017, R-019, R-021",
    "CRM-001": "R-002, R-003, R-011, R-015, R-021", "ISO-001": "R-003, R-011, R-021", "ISOFIX-001": "R-003, R-011, R-021",
    "FLOW-001": "R-003, R-004, R-006, R-007, R-011, R-016, R-017, R-019, R-020, R-021, R-022", "FLOW-002": "R-004, R-005, R-006, R-007, R-008, R-016, R-017, R-019, R-020, R-021, R-022",
    "FLOW-003": "R-006, R-007, R-008, R-013, R-017, R-019", "REM-001": "R-006, R-007, R-011, R-021", "RPT-001": "R-001, R-011, R-021",
    "UX-001": "R-004, R-006, R-007, R-011, R-020, R-021, R-022", "MIG-001": "R-005, R-008", "MIGSRC-001": "R-005, R-008",
    "OPS-001": "R-008, R-009, R-016", "PILOT-001": "R-001..R-022 except R-010 post-MVP delivery", "INT-001": "R-010",
    "MIGDEC-001": "R-005", "EXP-001": "R-016, R-017, R-019", "PROD-001": "R-001..R-022",
}
SECRET_PATTERNS = (
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(?:password|api[_-]?key|token|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_-]{20,}"),
)


def add(failures: list[str], code: str, detail: str) -> None:
    failures.append(f"{code}: {detail}")


def strict_json(path: Path, exact_keys: set[str], failures: list[str]) -> dict:
    raw = path.read_bytes()
    if len(raw) > 65_536:
        add(failures, "JSON_TOO_LARGE", path.name)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        add(failures, "JSON_NOT_UTF8", path.name)
        return {}

    def hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key}")
            result[key] = value
        return result

    try:
        data = json.loads(text, object_pairs_hook=hook)
    except Exception as exc:
        add(failures, "JSON_INVALID", f"{path.name}: {exc}")
        return {}
    missing, unknown = exact_keys - set(data), set(data) - exact_keys
    if missing:
        add(failures, "JSON_MISSING_KEYS", f"{path.name}: {sorted(missing)}")
    if unknown:
        add(failures, "JSON_UNKNOWN_KEYS", f"{path.name}: {sorted(unknown)}")

    def depth(value, current=1):
        children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
        return max([current] + [depth(child, current + 1) for child in children])

    if depth(data) > 10:
        add(failures, "JSON_TOO_DEEP", path.name)
    return data


def validate_types(data: dict, types: dict[str, type], prefix: str, failures: list[str]) -> None:
    for key, expected in types.items():
        value = data.get(key)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            add(failures, f"{prefix}_TYPE", key)


TASK_ID = r"[A-Z]+-[0-9]{3}"
DEP_VALUE = re.compile(rf"^(?:none|{TASK_ID}(?:, {TASK_ID})*)$")
EXPECTED_MACHINE_FILE_SHA256 = {
    "EXECUTION_PLAN.md": "d5816479fe8ae0898e4f40a0f5ce0e63582a59799704992ff18c36e1de9d96a4",
    "TASK_QUEUE.md": "2069ae61780cdd1083824d56bcbd3aed241e3af077927b2c6a979e1812e0039d",
}


def parse_dependencies(value: str) -> tuple[list[str], str | None]:
    if not DEP_VALUE.fullmatch(value):
        return [], "dependency field malformed"
    dependencies = [] if value == "none" else value.split(", ")
    if len(dependencies) != len(set(dependencies)):
        return [], "duplicate dependency token"
    return dependencies, None


def visual_fold(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return folded.translate(str.maketrans({"：": ":", "∶": ":", "—": "-", "–": "-"}))


def forbidden_characters(value: str, allowed_non_ascii: set[str]) -> list[str]:
    return sorted({f"U+{ord(char):04X}" for char in value if ord(char) > 127 and char not in allowed_non_ascii})


def forbidden_machine_syntax(value: str) -> list[str]:
    findings: set[str] = set()
    for char in value:
        code = ord(char)
        if (code < 32 and char != "\n") or code == 127:
            findings.add(f"control U+{code:04X}")
    for char, name in {"&": "entity opener", "\\": "escape opener", "<": "HTML opener", ">": "HTML closer"}.items():
        if char in value:
            findings.add(name)
    return sorted(findings)


def strip_markdown_containers(line: str) -> str:
    value = line.lstrip()
    while True:
        previous = value
        value = re.sub(r"^>\s*", "", value)
        value = re.sub(r"^(?:[-*+] |[0-9]+[.)] )", "", value)
        value = value.lstrip()
        if value == previous:
            return value


def resembles_structured_label(line: str) -> bool:
    candidate = strip_markdown_containers(line)
    # Emphasis-style labels are reserved for canonical machine fields.
    return candidate.startswith(("*", "_")) and any(mark in candidate for mark in (":", "：", "∶", "꞉"))


def resembles_task_record(line: str) -> bool:
    folded = visual_fold(strip_markdown_containers(line))
    return bool(re.match(r"^(?:#{1,6}\s+)?[a-z]+-[0-9]{3}(?:\s|$)", folded))


def parse_plan(text: str) -> tuple[dict[str, dict], list[str]]:
    exact_heading = re.compile(rf"^### ({TASK_ID}) — (\S(?:.*\S)?)$")
    heading_lines: list[tuple[int, re.Match[str]]] = []
    errors: list[str] = []
    invalid_characters = forbidden_characters(text, {"—"})
    if invalid_characters:
        errors.append(f"forbidden non-ASCII characters {invalid_characters}")
    invalid_syntax = forbidden_machine_syntax(text)
    if invalid_syntax:
        errors.append(f"forbidden machine syntax {invalid_syntax}")
    em_dash_lines = [line for line in text.splitlines() if "—" in line]
    invalid_em_dash = [line for line in em_dash_lines if not (line == "# Execution Plan — ERP Kreasi Hebat" or re.fullmatch(rf"### {TASK_ID} — \S(?:.*\S)?", line))]
    if invalid_em_dash:
        errors.append(f"em dash outside canonical title/task heading {invalid_em_dash!r}")
    candidate_tokens = set(re.findall(r"[A-Z]+-[0-9]{3}", text))
    unknown_tokens = sorted(token for token in candidate_tokens if not token.startswith("R-") and token not in CANONICAL_TASKS)
    if unknown_tokens:
        errors.append(f"unknown task-like tokens {unknown_tokens}")
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        if re.match(r"^\s*###\s+", line) or resembles_task_record(line):
            match = exact_heading.fullmatch(line)
            if match is None:
                errors.append(f"malformed task heading line {index + 1}: {line!r}")
            else:
                heading_lines.append((offsets[index], match))

    tasks: dict[str, dict] = {}
    for index, (start, match) in enumerate(heading_lines):
        task_id = match.group(1)
        if task_id in tasks:
            errors.append(f"duplicate task {task_id}")
            continue
        end = heading_lines[index + 1][0] if index + 1 < len(heading_lines) else len(text)
        block = text[start:end]
        block_lines = block.splitlines()
        parse_errors: list[str] = []
        structured: dict[str, list[str]] = {name: [] for name in ("Requirements", "Dependencies", "Owned paths", "Status")}
        for block_line in block_lines:
            label_like = re.match(r"^\s*\*\*([^*]+):\*\*", block_line)
            if label_like and label_like.group(1) in structured:
                if not block_line.startswith("**"):
                    parse_errors.append(f"indented structured label {label_like.group(1)}")
                structured[label_like.group(1)].append(block_line)
            elif resembles_structured_label(block_line):
                parse_errors.append(f"confusable structured label {block_line!r}")
            label_tokens = re.findall(r"(?i)(requirements|dependencies|owned\s+paths|status)\s*:", block_line)
            if label_tokens and not label_like:
                parse_errors.append(f"wrapped/noncanonical structured label {block_line!r}")
        for name, values in structured.items():
            if len(values) != 1:
                parse_errors.append(f"{name} label count {len(values)}")

        deps: list[str] = []
        if len(structured["Dependencies"]) == 1:
            dep_match = re.fullmatch(r"\*\*Dependencies:\*\* (.+)", structured["Dependencies"][0])
            if dep_match is None:
                parse_errors.append("dependency line malformed")
            else:
                deps, dep_error = parse_dependencies(dep_match.group(1))
                if dep_error:
                    parse_errors.append(dep_error)

        owned: list[str] = []
        if len(structured["Owned paths"]) == 1:
            owned_match = re.fullmatch(r"\*\*Owned paths:\*\* (`[^`]+`(?:, `[^`]+`)*)", structured["Owned paths"][0])
            if owned_match is None:
                parse_errors.append("owned field malformed")
            else:
                owned = re.findall(r"`([^`]+)`", owned_match.group(1))
                if len(owned) != len(set(owned)):
                    parse_errors.append("duplicate owned path token")
                if owned != EXPECTED_OWNED_PATHS.get(task_id):
                    parse_errors.append(f"canonical owned paths mismatch {owned!r}")

        status = None
        if len(structured["Status"]) == 1:
            status_match = re.fullmatch(r"\*\*Status:\*\* `([A-Z_]+)`", structured["Status"][0])
            if status_match is None:
                parse_errors.append("status field malformed")
            else:
                status = status_match.group(1)

        requirement_value = None
        if len(structured["Requirements"]) == 1:
            requirement_match = re.fullmatch(r"\*\*Requirements:\*\* ([A-Za-z0-9., -]+)", structured["Requirements"][0])
            if requirement_match is None:
                parse_errors.append("requirements field malformed")
            else:
                requirement_value = requirement_match.group(1)
                if requirement_value != EXPECTED_REQUIREMENTS.get(task_id):
                    parse_errors.append(f"canonical requirements mismatch {requirement_value!r}")

        tasks[task_id] = {"deps": deps, "owned": owned, "status": status, "requirements": requirement_value, "parse_errors": parse_errors, "block": block}
    return tasks, errors


def parse_queue(text: str) -> tuple[dict[str, dict], list[str]]:
    tasks: dict[str, dict] = {}
    errors: list[str] = []
    invalid_characters = forbidden_characters(text, set())
    if invalid_characters:
        errors.append(f"forbidden non-ASCII characters {invalid_characters}")
    invalid_syntax = forbidden_machine_syntax(text)
    if invalid_syntax:
        errors.append(f"forbidden machine syntax {invalid_syntax}")
    candidate_tokens = set(re.findall(r"[A-Z]+-[0-9]{3}", text))
    unknown_tokens = sorted(token for token in candidate_tokens if not token.startswith("R-") and token not in CANONICAL_TASKS)
    if unknown_tokens:
        errors.append(f"unknown task-like tokens {unknown_tokens}")
    exact_row = re.compile(rf"^\| ({TASK_ID}) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([A-Z_]+) \| ([^|]+) \|$")
    in_table = False
    separator_seen = False
    for line_number, line in enumerate(text.splitlines(), 1):
        folded_line = visual_fold(strip_markdown_containers(line))
        pipe_task_like = bool(re.match(r"^\|\s*[a-z]+-[0-9]{3}\s*\|", folded_line))
        if "|" in line and not (
            line == "| Task ID | Requirement scope | Dependencies | Owned path/worktree | Status | Evidence required |"
            or line == "|---|---|---|---|---|---|"
            or exact_row.fullmatch(line)
        ):
            errors.append(f"noncanonical pipe/table construct line {line_number}: {line!r}")
        if line == "| Task ID | Requirement scope | Dependencies | Owned path/worktree | Status | Evidence required |":
            if in_table:
                errors.append("duplicate queue table header")
            in_table = True
            continue
        if not in_table:
            if pipe_task_like:
                errors.append(f"task row outside canonical queue table line {line_number}: {line!r}")
            continue
        if not separator_seen:
            if line != "|---|---|---|---|---|---|":
                errors.append(f"malformed queue separator line {line_number}: {line!r}")
            separator_seen = True
            continue
        if line == "":
            in_table = False
            continue
        match = exact_row.fullmatch(line)
        if match is None:
            errors.append(f"malformed task row line {line_number}: {line!r}")
            continue
        task_id, scope, dependency_value, owned, status, evidence = match.groups()
        if task_id in tasks:
            errors.append(f"duplicate queue task {task_id}")
            continue
        dependencies, dep_error = parse_dependencies(dependency_value)
        if dep_error:
            errors.append(f"{task_id}:{dep_error}")
        if scope != EXPECTED_REQUIREMENTS.get(task_id):
            errors.append(f"{task_id}:canonical requirement scope mismatch {scope!r}")
        if owned != EXPECTED_QUEUE_OWNED.get(task_id):
            errors.append(f"{task_id}:canonical queue owned summary mismatch {owned!r}")
        tasks[task_id] = {"deps": dependencies, "scope": scope, "owned_summary": owned, "status": status, "evidence": evidence}
    return tasks, errors


SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def parse_owned_path(pattern: str) -> tuple[str, str] | None:
    """Return (kind, canonical path), accepting only exact paths or terminal /** trees."""
    if not pattern or pattern.startswith("/") or "\\" in pattern or "//" in pattern:
        return None
    tree = pattern.endswith("/**")
    base = pattern[:-3] if tree else pattern
    if "*" in base or "?" in base or "[" in base or "]" in base or "{" in base or "}" in base:
        return None
    segments = base.split("/")
    if not segments or any(segment in {"", ".", ".."} or not SEGMENT.fullmatch(segment) for segment in segments):
        return None
    return ("tree" if tree else "exact", "/".join(segments))


def overlap(left: tuple[str, str], right: tuple[str, str]) -> bool:
    left_kind, left_path = left
    right_kind, right_path = right
    if left_kind == "exact" and right_kind == "exact":
        return left_path == right_path
    if left_kind == "tree" and right_kind == "tree":
        return left_path == right_path or left_path.startswith(right_path + "/") or right_path.startswith(left_path + "/")
    tree_path, exact_path = (left_path, right_path) if left_kind == "tree" else (right_path, left_path)
    return exact_path == tree_path or exact_path.startswith(tree_path + "/")


def main() -> int:
    failures: list[str] = []
    for name in sorted(REQUIRED):
        path = PC / name
        if not path.is_file() or path.stat().st_size == 0:
            add(failures, "MISSING", name)
    if failures:
        print("PLAN_VALIDATION=FAIL\n" + "\n".join(failures))
        return 1

    policy = strict_json(PC / "project-policy.json", POLICY_KEYS, failures)
    approval = strict_json(PC / "full-auto-standing-approval.json", APPROVAL_KEYS, failures)
    validate_types(policy, {
        "schema_version": int, "project_id": str, "profile_id": str,
        "repository_path": str, "worktree_path": str, "telegram_bot": str,
        "telegram_chat": str, "authorized_bos_id": str, "approval_policy": str,
        "protected_actions": list, "prohibited_actions": list, "status": str,
    }, "POLICY", failures)
    validate_types(approval, {
        "schema_version": int, "policy": str, "project_id": str, "profile_id": str,
        "repository_path": str, "worktree_path": str, "repository_boundary": list,
        "telegram_bot": str, "telegram_chat": str, "telegram_identity_ref": str,
        "authorized_bos_id": str, "activated_at": str, "activation_source": str,
        "status": str,
    }, "APPROVAL", failures)
    if approval.get("revoked_at") is not None and not isinstance(approval.get("revoked_at"), str):
        add(failures, "APPROVAL_TYPE", "revoked_at")
    boundary = approval.get("repository_boundary")
    if not isinstance(boundary, list) or not boundary or any(not isinstance(item, str) for item in boundary) or len(boundary) != len(set(boundary)):
        add(failures, "APPROVAL_BOUNDARY_TYPE", "repository_boundary")

    for key, exact in (("protected_actions", REQUIRED_PROTECTED), ("prohibited_actions", REQUIRED_PROHIBITED)):
        value = policy.get(key)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
            add(failures, "POLICY_ACTION_TYPE", key)
        elif len(value) != len(set(value)):
            add(failures, "POLICY_ACTION_DUPLICATE", key)
        elif set(value) != exact:
            add(failures, "POLICY_ACTION_SET", f"{key}: missing={sorted(exact-set(value))} unknown={sorted(set(value)-exact)}")

    root = str(ROOT.resolve())
    common_expected = {
        "schema_version": 1, "project_id": "erp-kreasi-hebat", "profile_id": "executor",
        "repository_path": root, "worktree_path": root,
        "telegram_bot": "@NalarinLinuxKreasiHebatBot", "telegram_chat": "233301028",
        "authorized_bos_id": "233301028", "status": "ACTIVE",
    }
    for key, value in common_expected.items():
        if policy.get(key) != value or approval.get(key) != value:
            add(failures, "BINDING_MISMATCH", key)
    policy_expected = {"approval_policy": "FULL_AUTO"}
    approval_expected = {
        "policy": "FULL_AUTO", "telegram_identity_ref": "telegram-user:233301028",
        "repository_boundary": [root], "revoked_at": None,
    }
    for key, value in policy_expected.items():
        if policy.get(key) != value:
            add(failures, "BINDING_MISMATCH", f"policy.{key}")
    for key, value in approval_expected.items():
        if approval.get(key) != value:
            add(failures, "BINDING_MISMATCH", f"approval.{key}")
    try:
        datetime.strptime(approval.get("activated_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        add(failures, "APPROVAL_VALUE", "activated_at")
    if not approval.get("activation_source", "").strip():
        add(failures, "APPROVAL_VALUE", "activation_source")
    if approval.get("repository_boundary") != [root]:
        add(failures, "BINDING_MISMATCH", "repository_boundary")
    if policy.get("approval_policy") != "FULL_AUTO" or policy.get("status") != "ACTIVE":
        add(failures, "POLICY_INACTIVE", "project-policy")
    if approval.get("policy") != "FULL_AUTO" or approval.get("status") != "ACTIVE" or approval.get("revoked_at") is not None:
        add(failures, "APPROVAL_INACTIVE", "standing approval")

    req_text = (PC / "REQUIREMENTS.md").read_text(encoding="utf-8")
    requirements = set(re.findall(r"(?m)^- (R-\d{3})\s+—", req_text))
    wanted = {f"R-{number:03d}" for number in range(1, 23)}
    if requirements != wanted:
        add(failures, "REQUIREMENT_SET", f"expected={sorted(wanted)} actual={sorted(requirements)}")

    with (PC / "EXECUTION_PLAN.md").open("r", encoding="utf-8", newline="") as handle:
        plan_text = handle.read()
    with (PC / "TASK_QUEUE.md").open("r", encoding="utf-8", newline="") as handle:
        queue_text = handle.read()
    for filename, expected_hash in EXPECTED_MACHINE_FILE_SHA256.items():
        actual_hash = hashlib.sha256((PC / filename).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            add(failures, "MACHINE_FILE_CONTRACT", f"{filename}: expected={expected_hash} actual={actual_hash}")
    plan, plan_errors = parse_plan(plan_text)
    queue, queue_errors = parse_queue(queue_text)
    for error in plan_errors:
        add(failures, "TASK_PARSE_ERROR", f"plan:{error}")
    for error in queue_errors:
        add(failures, "TASK_PARSE_ERROR", f"queue:{error}")
    if set(plan) != set(queue):
        add(failures, "TASK_PARITY", f"plan={sorted(plan)} queue={sorted(queue)}")
    if set(plan) != CANONICAL_TASKS or set(queue) != CANONICAL_TASKS:
        add(failures, "CANONICAL_TASK_SET", f"missing_plan={sorted(CANONICAL_TASKS-set(plan))} extra_plan={sorted(set(plan)-CANONICAL_TASKS)} missing_queue={sorted(CANONICAL_TASKS-set(queue))} extra_queue={sorted(set(queue)-CANONICAL_TASKS)}")
    if requirements - set(re.findall(r"\bR-\d{3}\b", plan_text)):
        add(failures, "UNMAPPED_REQUIREMENTS", str(sorted(requirements - set(re.findall(r"\bR-\d{3}\b", plan_text)))))

    labels = ("**Requirements:**", "**Dependencies:**", "**Owned paths:**", "**Status:**", "Steps:", "Tests:", "Done when:")
    for task_id, task in plan.items():
        for parse_error in task.get("parse_errors", []):
            add(failures, "TASK_PARSE_ERROR", f"{task_id}:{parse_error}")
        for label in labels:
            if label not in task["block"]:
                add(failures, "TASK_INCOMPLETE", f"{task_id} missing {label}")
        if len(re.findall(r"(?m)^\d+\. ", task["block"])) < 3:
            add(failures, "TASK_TOO_COARSE", task_id)
        if task_id in queue and set(task["deps"]) != set(queue[task_id]["deps"]):
            add(failures, "DEPENDENCY_MISMATCH", task_id)
        if task_id in queue and task["status"] != queue[task_id]["status"]:
            add(failures, "STATUS_MISMATCH", task_id)
        if task.get("status") != EXPECTED_STATUS.get(task_id):
            add(failures, "CANONICAL_STATUS", f"{task_id}:{task.get('status')}")
        if not task["owned"]:
            add(failures, "OWNED_PATH_MISSING", task_id)
        parsed_owned = []
        for owned in task["owned"]:
            parsed = parse_owned_path(owned)
            if parsed is None:
                add(failures, "OWNED_PATH_BOUNDARY", f"{task_id}:{owned}")
            else:
                parsed_owned.append(parsed)
        task["parsed_owned"] = parsed_owned

    all_ids = set(queue)
    for task_id, task in queue.items():
        for dependency in task["deps"]:
            if dependency not in all_ids:
                add(failures, "UNKNOWN_DEPENDENCY", f"{task_id}->{dependency}")
    actual_edges = {(dependency, task_id) for task_id, task in queue.items() for dependency in task["deps"]}
    missing_edges = REQUIRED_EDGES - actual_edges
    if missing_edges:
        add(failures, "REQUIRED_EDGE_MISSING", str(sorted(missing_edges)))

    indegree = {task_id: 0 for task_id in queue}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for task_id, task in queue.items():
        for dependency in task["deps"]:
            indegree[task_id] += 1
            outgoing[dependency].append(task_id)
    work = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
    visited = []
    while work:
        node = work.popleft()
        visited.append(node)
        for child in outgoing[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                work.append(child)
    if len(visited) != len(queue):
        add(failures, "DEPENDENCY_CYCLE", str(sorted(set(queue) - set(visited))))

    ancestors: dict[str, set[str]] = {task_id: set() for task_id in queue}
    changed = True
    while changed:
        changed = False
        for task_id, task in queue.items():
            expanded = set(task["deps"])
            for dependency in task["deps"]:
                expanded.update(ancestors[dependency])
            if not expanded.issubset(ancestors[task_id]):
                ancestors[task_id].update(expanded)
                changed = True

    ids = sorted(plan)
    for index, left in enumerate(ids):
        for right in ids[index + 1:]:
            intersections = [(a, b) for a in plan[left].get("parsed_owned", []) for b in plan[right].get("parsed_owned", []) if overlap(a, b)]
            serialized = left in ancestors[right] or right in ancestors[left]
            if intersections and not serialized:
                add(failures, "OWNED_PATH_OVERLAP", f"{left}<->{right}:{intersections}")

    done = {task_id for task_id, task in queue.items() if task["status"] == "DONE"}
    for task_id, task in queue.items():
        if task["status"] == "READY" and not set(task["deps"]).issubset(done):
            add(failures, "FALSE_READY", task_id)

    broken = []
    for markdown in ROOT.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8", errors="replace")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            local = target.split("#", 1)[0]
            if local and not (markdown.parent / local).resolve().exists():
                broken.append(f"{markdown.relative_to(ROOT)}->{target}")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            add(failures, "SECRET_PATTERN", str(markdown.relative_to(ROOT)))
    if broken:
        add(failures, "BROKEN_LINKS", str(sorted(broken)))

    excluded = {"PLAN_GATE.md", "PLAN_REVIEW.md", "STATUS.md", "LOCK.md"}
    baseline_files = [path for path in sorted(PC.iterdir()) if path.is_file() and path.name not in excluded]
    baseline_files.extend([ROOT / "README.md", ROOT / "scripts" / "validate_plan_gate.py", ROOT / "scripts" / "test_validate_plan_gate.py"])
    plans = ROOT / ".hermes" / "plans"
    if plans.is_dir():
        baseline_files.extend(sorted(path for path in plans.rglob("*") if path.is_file()))
    entries = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT)}" for path in baseline_files]
    baseline = hashlib.sha256(("\n".join(entries) + "\n").encode()).hexdigest()

    if failures:
        print("PLAN_VALIDATION=FAIL")
        print("\n".join(sorted(set(failures))))
        print(f"DRAFT_BASELINE_SHA256={baseline}")
        return 1
    print("PLAN_VALIDATION=PASS")
    print(f"REQUIREMENTS={len(requirements)}")
    print(f"PLAN_TASKS={len(plan)}")
    print(f"QUEUE_TASKS={len(queue)}")
    print("TASK_PARITY=PASS")
    print("GRAPH=ACYCLIC")
    print("OWNED_PATHS=PASS")
    print("APPROVAL_BOUNDARY=PASS")
    print("SECRETS=NONE_DETECTED")
    print(f"DRAFT_BASELINE_SHA256={baseline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
