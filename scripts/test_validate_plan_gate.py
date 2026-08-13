#!/usr/bin/env python3
"""Behavioral mutation tests for validate_plan_gate.py."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
POLICY_FILE = "project-policy.json"
APPROVAL_FILE = "full-auto-standing-approval.json"


def run(root: Path) -> int:
    return subprocess.run(["python3", "scripts/validate_plan_gate.py"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).returncode


def fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    temp = tempfile.TemporaryDirectory(prefix="erp-plan-validator-")
    root = Path(temp.name) / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copytree(SOURCE / "project-control", root / "project-control")
    shutil.copy2(SOURCE / "scripts" / "validate_plan_gate.py", root / "scripts" / "validate_plan_gate.py")
    shutil.copy2(SOURCE / "scripts" / "test_validate_plan_gate.py", root / "scripts" / "test_validate_plan_gate.py")
    shutil.copy2(SOURCE / "README.md", root / "README.md")
    if (SOURCE / ".hermes" / "plans").is_dir():
        shutil.copytree(SOURCE / ".hermes" / "plans", root / ".hermes" / "plans")
    for name in (POLICY_FILE, APPROVAL_FILE):
        path = root / "project-control" / name
        data = json.loads(path.read_text())
        data["repository_path"] = str(root)
        data["worktree_path"] = str(root)
        if name == APPROVAL_FILE:
            data["repository_boundary"] = [str(root)]
        path.write_text(json.dumps(data, indent=2) + "\n")
    return temp, root


def expect_mutant_failure(label: str, mutate) -> None:
    temp, root = fixture()
    try:
        if run(root) != 0:
            raise AssertionError(f"control fixture failed: {label}")
        mutate(root)
        if run(root) == 0:
            raise AssertionError(f"mutant survived: {label}")
    finally:
        temp.cleanup()


def mutate_json(root: Path, filename: str, callback) -> None:
    path = root / "project-control" / filename
    data = json.loads(path.read_text())
    callback(data, root)
    path.write_text(json.dumps(data, indent=2) + "\n")


def replace_plan(root: Path, old: str, new: str) -> None:
    path = root / "project-control" / "EXECUTION_PLAN.md"
    text = path.read_text()
    if old not in text:
        raise AssertionError(f"mutation anchor missing: {old}")
    path.write_text(text.replace(old, new, 1))


def replace_text(root: Path, relative_path: str, old: str, new: str) -> None:
    path = root / relative_path
    text = path.read_text()
    if old not in text:
        raise AssertionError(f"mutation anchor missing: {relative_path}:{old}")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    policy = json.loads((SOURCE / "project-control" / POLICY_FILE).read_text())
    tests = 0
    for key in ("protected_actions", "prohibited_actions"):
        for action in policy[key]:
            expect_mutant_failure(f"remove {key}:{action}", lambda root, k=key, a=action: mutate_json(root, POLICY_FILE, lambda data, _: data[k].remove(a)))
            tests += 1
        mutations = {
            "empty": lambda data, _, k=key: data.__setitem__(k, []),
            "duplicate": lambda data, _, k=key: data[k].append(data[k][0]),
            "unknown": lambda data, _, k=key: data[k].append("UNKNOWN_ACTION"),
            "wrong type": lambda data, _, k=key: data.__setitem__(k, "wrong"),
        }
        for label, mutation in mutations.items():
            expect_mutant_failure(f"{label} {key}", lambda root, m=mutation: mutate_json(root, POLICY_FILE, m))
            tests += 1

    policy_bindings = {
        "schema_version": 2, "project_id": "wrong", "profile_id": "wrong",
        "repository_path": "/wrong", "worktree_path": "/wrong", "telegram_bot": "@WrongBot",
        "telegram_chat": "999", "authorized_bos_id": "999", "approval_policy": "APPROVAL_GATED",
        "status": "INACTIVE",
    }
    approval_bindings = {
        "schema_version": 2, "policy": "APPROVAL_GATED", "project_id": "wrong", "profile_id": "wrong",
        "repository_path": "/wrong", "worktree_path": "/wrong", "repository_boundary": ["/wrong"],
        "telegram_bot": "@WrongBot", "telegram_chat": "999", "telegram_identity_ref": "telegram-user:999",
        "authorized_bos_id": "999", "activated_at": "not-a-time", "activation_source": "",
        "status": "INACTIVE", "revoked_at": "2026-08-13T00:00:00Z",
    }
    for key, value in policy_bindings.items():
        expect_mutant_failure(f"policy binding {key}", lambda root, k=key, v=value: mutate_json(root, POLICY_FILE, lambda data, _: data.__setitem__(k, v)))
        tests += 1
    for key, value in approval_bindings.items():
        expect_mutant_failure(f"approval binding {key}", lambda root, k=key, v=value: mutate_json(root, APPROVAL_FILE, lambda data, _: data.__setitem__(k, v)))
        tests += 1
    expect_mutant_failure("both telegram bots wrong", lambda root: [mutate_json(root, filename, lambda data, _: data.__setitem__("telegram_bot", "@WrongBot")) for filename in (POLICY_FILE, APPROVAL_FILE)])
    tests += 1

    def remove_sec(root: Path) -> None:
        path = root / "project-control" / "EXECUTION_PLAN.md"
        text = path.read_text()
        path.write_text(text[:text.index("### SEC-001")] + text[text.index("### PLAN-001"):])

    expect_mutant_failure("plan/queue parity", remove_sec)
    tests += 1

    def remove_optional_from_both(root: Path) -> None:
        plan_path = root / "project-control" / "EXECUTION_PLAN.md"
        text = plan_path.read_text()
        start = text.index("### EVAL-003")
        end = text.index("### FND-001")
        plan_path.write_text(text[:start] + text[end:])
        queue_path = root / "project-control" / "TASK_QUEUE.md"
        queue_path.write_text("\n".join(line for line in queue_path.read_text().splitlines() if not line.startswith("| EVAL-003 |")) + "\n")

    expect_mutant_failure("canonical task removed from plan and queue", remove_optional_from_both)
    tests += 1

    expect_mutant_failure(
        "exact plan byte contract",
        lambda root: replace_plan(root, "# Execution Plan — ERP Kreasi Hebat", "# Execution Plan — ERP Kreasi Hebat extra"),
    )
    expect_mutant_failure(
        "exact queue byte contract",
        lambda root: replace_text(root, "project-control/TASK_QUEUE.md", "# Task Queue", "# Task Queue extra"),
    )
    tests += 2

    def duplicate_owned_label(root: Path) -> None:
        replace_plan(root, "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`", "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`  \n**Owned paths:** ../../escape")

    def malformed_owned_field(root: Path) -> None:
        replace_plan(root, "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`", "**Owned paths:** `evaluation/erpclaw/**`, ../../escape")

    expect_mutant_failure("duplicate owned label", duplicate_owned_label)
    expect_mutant_failure("malformed owned field", malformed_owned_field)
    tests += 2

    expect_mutant_failure("impossible activation timestamp", lambda root: mutate_json(root, APPROVAL_FILE, lambda data, _: data.__setitem__("activated_at", "2026-99-99T99:99:99Z")))
    tests += 1

    def remove_edge(root: Path, parent: str, child: str) -> None:
        plan_path = root / "project-control" / "EXECUTION_PLAN.md"
        text = plan_path.read_text()
        match = re.search(rf"(?ms)^### {re.escape(child)}\b.*?^\*\*Dependencies:\*\*\s*(.*?)$", text)
        if not match:
            raise AssertionError(f"plan edge anchor missing {parent}->{child}")
        replacement = re.sub(rf"(?:,\s*)?`{re.escape(parent)}`(?:,\s*)?", lambda m: ", " if m.group(0).startswith(",") and m.group(0).endswith(",") else "", match.group(1)).strip(" ,")
        text = text[:match.start(1)] + replacement + text[match.end(1):]
        plan_path.write_text(text)
        queue_path = root / "project-control" / "TASK_QUEUE.md"
        lines = []
        for line in queue_path.read_text().splitlines():
            if line.startswith(f"| {child} |"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                deps = [dep.strip() for dep in cells[2].split(",") if dep.strip() != parent]
                cells[2] = ", ".join(deps) if deps else "none"
                line = "| " + " | ".join(cells) + " |"
            lines.append(line)
        queue_path.write_text("\n".join(lines) + "\n")

    for parent, child in [("ISO-001", "ISOFIX-001"), ("ISOFIX-001", "PILOT-001"), ("PILOT-001", "PROD-001"), ("MIGDEC-001", "PROD-001"), ("EXP-001", "PROD-001")]:
        expect_mutant_failure(f"required edge {parent}->{child}", lambda root, p=parent, c=child: remove_edge(root, p, c))
        tests += 1

    structured_mutants = [
        ("hidden dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencies:** garbage"),
        ("hidden owned label", "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`", "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`  \n**Owned paths:** malformed-without-two-spaces"),
        ("hidden status label", "**Status:** `BACKLOG_OPTIONAL`", "**Status:** `BACKLOG_OPTIONAL`\n**Status:** garbage"),
        ("dependency trailing junk", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001 trailing-junk"),
        ("duplicate dependency", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001, PLAN-001"),
        ("dependency NBSP", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001\u00a0"),
        ("indented dependency label", "**Dependencies:** PLAN-001", " **Dependencies:** garbage\n**Dependencies:** PLAN-001"),
        ("plan duplicate heading spacing", "### EVAL-003 — Optional ERPClaw comparator", "###  EVAL-003 — Hidden duplicate\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("plan unknown ASCII hyphen heading", "### EVAL-003 — Optional ERPClaw comparator", "### EVIL-999 - Hidden unknown\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("lowercase dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**dependencies:** junk"),
        ("fullwidth colon dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencies：** junk"),
        ("ratio colon dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencies∶** junk"),
        ("triple emphasis dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n***Dependencies:*** junk"),
        ("fullwidth colon owned label", "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`", "**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`  \n**Owned paths：** junk"),
        ("fullwidth colon status label", "**Status:** `BACKLOG_OPTIONAL`", "**Status:** `BACKLOG_OPTIONAL`\n**Status：** junk"),
        ("hidden level2 task", "### EVAL-003 — Optional ERPClaw comparator", "## EVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("hidden list task", "### EVAL-003 — Optional ERPClaw comparator", "- EVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("Cyrillic dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencіes:** junk"),
        ("zero width dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependen\u200bcies:** junk"),
        ("underscore dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n__Dependencies:__ junk"),
        ("wrapped dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n_**Dependencies:**_ junk"),
        ("modifier colon dependency label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencies꞉** junk"),
        ("blockquote hidden task", "### EVAL-003 — Optional ERPClaw comparator", "> ### EVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("ordered hidden task", "### EVAL-003 — Optional ERPClaw comparator", "1. EVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("blockquote list hidden task", "### EVAL-003 — Optional ERPClaw comparator", "> - EVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("nested blockquote ordered hidden task", "### EVAL-003 — Optional ERPClaw comparator", "> > 1) EVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("line separator task", "### EVAL-003 — Optional ERPClaw comparator", "`EVIL-\u2028999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("paragraph separator task", "### EVAL-003 — Optional ERPClaw comparator", "`EVIL-\u2029999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("NBSP task", "### EVAL-003 — Optional ERPClaw comparator", "`EVIL-\u00a0999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("narrow NBSP task", "### EVAL-003 — Optional ERPClaw comparator", "`EVIL-\u202f999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("Cyrillic task confusable", "### EVAL-003 — Optional ERPClaw comparator", "`ЕVIL-999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("Greek task confusable", "### EVAL-003 — Optional ERPClaw comparator", "`ΕVIL-999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("inline code task", "### EVAL-003 — Optional ERPClaw comparator", "`EVIL-999` Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("link label task", "### EVAL-003 — Optional ERPClaw comparator", "[EVIL-999](#hidden)\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("HTML task", "### EVAL-003 — Optional ERPClaw comparator", "<strong>EVIL-999</strong> Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("unordered tab task", "### EVAL-003 — Optional ERPClaw comparator", "-\tEVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("ordered tab task", "### EVAL-003 — Optional ERPClaw comparator", "1.\tEVIL-999 — Hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("HTML strong label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n<strong>Dependencies:</strong> junk"),
        ("HTML b label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n<b>Dependencies:</b> junk"),
        ("inline code label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n`Dependencies:` junk"),
        ("link label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n[Dependencies:](#x) junk"),
        ("escaped emphasis label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n\\*\\*Dependencies:\\*\\* junk"),
        ("strikethrough label", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n~~Dependencies:~~ junk"),
        ("allowed arrow hidden task", "### EVAL-003 — Optional ERPClaw comparator", "EVIL↔999 hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("entity hyphen task", "### EVAL-003 — Optional ERPClaw comparator", "EVIL&#45;999 hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("entity colon dependency", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencies&#58;** junk"),
        ("numeric entity colon dependency", "**Dependencies:** PLAN-001", "**Dependencies:** PLAN-001  \n**Dependencies&#x3A;** junk"),
        ("escaped task ID", "### EVAL-003 — Optional ERPClaw comparator", "EVIL\\-999 hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("boundary task ID", "### EVAL-003 — Optional ERPClaw comparator", "prefix_EVIL-999_suffix hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("NUL plan", "### EVAL-003 — Optional ERPClaw comparator", "NUL\x00hidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("vertical tab plan", "### EVAL-003 — Optional ERPClaw comparator", "VT\x0bhidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("form feed plan", "### EVAL-003 — Optional ERPClaw comparator", "FF\x0chidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("CR plan", "### EVAL-003 — Optional ERPClaw comparator", "CR\rhidden\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("extra em dash in heading", "### EVAL-003 — Optional ERPClaw comparator", "### EVAL-003 — Optional ERPClaw comparator — extra"),
        ("hidden canonical task ID", "### EVAL-003 — Optional ERPClaw comparator", "`EVAL-003` hidden duplicate\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("extra title", "# Execution Plan — ERP Kreasi Hebat", "# Execution Plan — ERP Kreasi Hebat\n# Extra title"),
        ("auxiliary heading", "### EVAL-003 — Optional ERPClaw comparator", "#### Auxiliary heading\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("duplicate Steps label", "Steps:\n1. Pin/audit source", "Steps:\nSteps:\n1. Pin/audit source"),
        ("duplicate Tests label", "Tests: source/security/invariant/restore evidence.", "Tests: duplicate\nTests: source/security/invariant/restore evidence."),
        ("duplicate Done label", "Done when: comparator decision", "Done when: duplicate\nDone when: comparator decision"),
        ("fused unknown requirement", "### EVAL-003 — Optional ERPClaw comparator", "xR-999y\n\n### EVAL-003 — Optional ERPClaw comparator"),
        ("concatenated requirement", "### EVAL-003 — Optional ERPClaw comparator", "R-999R-001\n\n### EVAL-003 — Optional ERPClaw comparator"),
    ]
    for label, old, new in structured_mutants:
        expect_mutant_failure(label, lambda root, o=old, n=new: replace_plan(root, o, n))
        tests += 1

    def mutate_both_dependencies(root: Path, old: str, new: str) -> None:
        replace_plan(root, f"**Dependencies:** {old}", f"**Dependencies:** {new}")
        queue_path = root / "project-control" / "TASK_QUEUE.md"
        queue_path.write_text(queue_path.read_text().replace(f"| SEC-001 | Project/profile/bot/FULL_AUTO boundary | {old} |", f"| SEC-001 | Project/profile/bot/FULL_AUTO boundary | {new} |", 1))

    for label, mutant in [("arbitrary dependency instead of none", "arbitrary-junk"), ("fullwidth dependency token", "ＥＶＩＬ-999")]:
        expect_mutant_failure(label, lambda root, m=mutant: mutate_both_dependencies(root, "none", m))
        tests += 1

    def queue_hidden_row(root: Path, row: str) -> None:
        path = root / "project-control" / "TASK_QUEUE.md"
        text = path.read_text()
        anchor = next((line for line in text.splitlines() if line.startswith("| EVAL-003 |")), None)
        if anchor is None:
            raise AssertionError("EVAL-003 queue anchor missing")
        mutated = text.replace(anchor, anchor + "\n" + row, 1)
        if mutated == text:
            raise AssertionError("queue hidden-row mutation did not apply")
        path.write_text(mutated)

    queue_rows = [
        " | EVAL-003 | hidden | PLAN-001 | hidden | BACKLOG_OPTIONAL | hidden |",
        "| ＥＶＩＬ-９９９ | hidden | none | hidden | BACKLOG | hidden |",
        "| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
    ]
    for index, row in enumerate(queue_rows, 1):
        expect_mutant_failure(f"malformed hidden queue row {index}", lambda root, r=row: queue_hidden_row(root, r))
        tests += 1

    def queue_outside_row(root: Path, row: str) -> None:
        path = root / "project-control" / "TASK_QUEUE.md"
        path.write_text(path.read_text() + "\n" + row + "\n")

    outside_rows = [
        "| EVAL-003 | Optional ERPClaw comparator | PLAN-001 | isolated comparator/evidence | BACKLOG_OPTIONAL | identical synthetic rubric |",
        " | EVAL-003 | hidden | PLAN-001 | hidden | BACKLOG_OPTIONAL | hidden |",
        "| ＥＶＩＬ-９９９ | hidden | none | hidden | BACKLOG | hidden |",
        "| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "> | EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "| EVIL-\u200b999 | hidden | none | hidden | BACKLOG | hidden |",
        "> > | EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "-\t| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "1.\t| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "`| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |`",
        "<div>| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |</div>",
        "[| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |](#x)",
        "> 1.\t| EVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "| EVIL-\u2028999 | hidden | none | hidden | BACKLOG | hidden |",
        "| ЕVIL-999 | hidden | none | hidden | BACKLOG | hidden |",
        "EVIL-999 hidden plain queue text",
        "`EVIL-999` hidden queue code",
        "EVIL&#45;999 hidden entity task",
        "&#124; EVIL-999 &#124; hidden &#124; none &#124; hidden &#124; BACKLOG &#124; hidden &#124;",
        "&#x7C; EVIL-999 &#x7C; hidden &#x7C; none &#x7C; hidden &#x7C; BACKLOG &#x7C; hidden &#x7C;",
        "&VerticalLine; EVIL-999 &VerticalLine; hidden &VerticalLine; none &VerticalLine; hidden &VerticalLine; BACKLOG &VerticalLine; hidden &VerticalLine;",
        "NUL\x00hidden queue",
        "TAB\thidden queue",
        "VT\x0bhidden queue",
        "FF\x0chidden queue",
        "CR\rhidden queue",
        "`EVAL-003` hidden canonical queue task",
        "R-000 hidden requirement",
        "R-023 hidden requirement",
        "xR-999y fused requirement",
        "| Task ID | Requirement scope | Dependencies | Owned path/worktree | Status | Evidence required |",
        "|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(outside_rows, 1):
        expect_mutant_failure(f"queue row outside table {index}", lambda root, r=row: queue_outside_row(root, r))
        tests += 1

    for requirement in ("R-020", "R-021", "R-022"):
        expect_mutant_failure(
            f"remove new requirement {requirement}",
            lambda root, req=requirement: replace_text(root, "project-control/REQUIREMENTS.md", f"- {req} —", f"- REMOVED-{req} —"),
        )
        tests += 1

    expect_mutant_failure(
        "queue requirement scope divergence",
        lambda root: replace_text(root, "project-control/TASK_QUEUE.md", "| PLAN-001 | R-001..R-022 |", "| PLAN-001 | R-001 only bogus scope |"),
    )
    tests += 1

    expect_mutant_failure(
        "valid but noncanonical owned path",
        lambda root: replace_plan(root, "evaluation/erpclaw/**", "evaluation/erpclawx/**"),
    )
    expect_mutant_failure(
        "arbitrary queue owned summary",
        lambda root: replace_text(root, "project-control/TASK_QUEUE.md", "| EVAL-003 | R-005, R-006, R-009 | PLAN-001 | isolated comparator/evidence |", "| EVAL-003 | R-005, R-006, R-009 | PLAN-001 | arbitrary ASCII summary |"),
    )
    tests += 2

    def hacked_status(root: Path) -> None:
        replace_plan(root, "**Status:** `BACKLOG_OPTIONAL`", "**Status:** `HACKED`")
        path = root / "project-control" / "TASK_QUEUE.md"
        path.write_text(path.read_text().replace("| EVAL-003 | Optional ERPClaw comparator | PLAN-001 | isolated comparator/evidence | BACKLOG_OPTIONAL |", "| EVAL-003 | Optional ERPClaw comparator | PLAN-001 | isolated comparator/evidence | HACKED |", 1))

    expect_mutant_failure("unknown status in plan and queue", hacked_status)
    tests += 1

    base = "evaluation/erpclaw/**"
    invalid_paths = [
        "evaluation/erpclaw/..", "evaluation/./erpclaw/**", "evaluation//erpclaw/**",
        r"evaluation\erpclaw\**", "evaluation/erp*", "evaluation/../erpclaw/**",
        "/evaluation/erpclaw/**", "./evaluation/erpclaw/**", "evaluation/?rpclaw/**",
        "evaluation/[e]rpclaw/**", "evaluation/{erpclaw}/**", "**",
    ]
    for mutant in invalid_paths:
        expect_mutant_failure(f"invalid owned path {mutant}", lambda root, m=mutant: replace_plan(root, base, m))
        tests += 1

    overlap_mutants = ["evaluation/erpnext/**", "evaluation/**", "evaluation/erpnext", "evaluation/erpnext/subdir/**"]
    for mutant in overlap_mutants:
        expect_mutant_failure(f"unserialized overlap {mutant}", lambda root, m=mutant: replace_plan(root, base, m))
        tests += 1

    print(f"MUTATION_TESTS=PASS\nMUTANTS_KILLED={tests}")


if __name__ == "__main__":
    main()
