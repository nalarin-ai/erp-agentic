# Plan Review Ledger

- Baseline writer: Hermes executor
- Pass 1 reviewer: isolated read-only subagent, traceability/completeness
- Pass 2 reviewer: isolated read-only subagent, adversarial engineering/security/recovery
- Model diversity: reviewers inherited available parent chain; self-reported role isolation, not model-identity proof
- Pass 1 verdict: `REVISE` (7 HIGH, 5 MEDIUM)
- Pass 2 verdict: `REVISE` (8 HIGH, 4 MEDIUM)
- Revision status: all findings addressed in baseline; fresh verification pending

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P1-001 | HIGH | `TRACEABILITY_MATRIX.md` maps R/FR/J/MVP to owner/assertion/test/failure/evidence | RESOLVED_PENDING_FRESH_REVIEW |
| P1-002 | HIGH | Requirement tags audited; R-010 owned only by INT-001; range no longer sole coverage | RESOLVED_PENDING_FRESH_REVIEW |
| P1-003 | HIGH | UNIT-001 and CRM-001 own unit/domain/onboarding; Balonesia acceptance explicit | RESOLVED_PENDING_FRESH_REVIEW |
| P1-004 | HIGH | `receivable_ledger` master/policy/document snapshot added; FND/adapter/tests own it | RESOLVED_PENDING_FRESH_REVIEW |
| P1-005 | HIGH | Queue/plan dependencies rewritten to task IDs only and machine validator passes DAG/parity | RESOLVED_PENDING_FRESH_REVIEW |
| P1-006 | HIGH | `STATE_MACHINES.md` defines orthogonal posting/delivery/AR/recovery states and guards | RESOLVED_PENDING_FRESH_REVIEW |
| P1-007 | HIGH | `MVP-AC-01..12` added; qualified sign-off clarified as production gate | RESOLVED_PENDING_FRESH_REVIEW |
| P1-008 | MEDIUM | CRM-001 owns lead/opportunity/customer/quotation/query/export/conflict persistence/contracts | RESOLVED_PENDING_FRESH_REVIEW |
| P1-009 | MEDIUM | REM-001 defines triggers/auth/dedupe/outbox/retry/suppression/events | RESOLVED_PENDING_FRESH_REVIEW |
| P1-010 | MEDIUM | `DUPLICATE_PAYMENT_POLICY.md` defines namespace/normalization/checksum/auth-safe outcomes/races | RESOLVED_PENDING_FRESH_REVIEW |
| P1-011 | MEDIUM | UX_SPEC journey table covers reminders/conflict/onboarding/reversal/offline/empty/evidence rejection | RESOLVED_PENDING_FRESH_REVIEW |
| P1-012 | MEDIUM | Traceability event contract covers payment/reminder/reversal/config/conflict/evidence/import/recovery; paths bounded | RESOLVED_PENDING_FRESH_REVIEW |
| P2-001 | HIGH | `project-policy.json` now machine-prohibits production/live import/official posting/banking/tax/unsafe credential/spend/destructive/public actions | RESOLVED_PENDING_FRESH_REVIEW |
| P2-002 | HIGH | ISO-001 + `NATIVE_ERP_ISOLATION.md` require native UI/API/search/report/export/file/job evidence and architecture rejection | RESOLVED_PENDING_FRESH_REVIEW |
| P2-003 | HIGH | Ledger model/policy/compatibility/qualified review and tests added | RESOLVED_PENDING_FRESH_REVIEW |
| P2-004 | HIGH | `IDEMPOTENCY_AUDIT_RECOVERY.md` defines namespace/hash/CAS/fencing/lease/external ref/crash tests | RESOLVED_PENDING_FRESH_REVIEW |
| P2-005 | HIGH | Audit fail-closed/atomic precondition/integrity/export/storage alerts/orphan reconciliation defined | RESOLVED_PENDING_FRESH_REVIEW |
| P2-006 | HIGH | REC-001 owns durable worker/operator queue/SLA/alerts/restart and is prerequisite to live adapter/post/ops | RESOLVED_PENDING_FRESH_REVIEW |
| P2-007 | HIGH | OPERATIONS/OPS-001 now define consistency manifest/PITR/key recovery/immutable off-host/isolated restore/cross-store verification | RESOLVED_PENDING_FRESH_REVIEW |
| P2-008 | HIGH | MIG-001 generic build split from owner-gated MIGSRC-001; MIGDEC-001 explicit production branch | RESOLVED_PENDING_FRESH_REVIEW |
| P2-009 | MEDIUM | External inputs are lifecycle nodes; validator exists/passes; diagram made non-normative | RESOLVED_PENDING_FRESH_REVIEW |
| P2-010 | MEDIUM | Task owned paths are bounded; overlap/one-writer rule explicit; queue aligned | RESOLVED_PENDING_FRESH_REVIEW |
| P2-011 | MEDIUM | FND-001 now depends PLAN-001, not vendor evaluation; fixture policy remains buildable | RESOLVED_PENDING_FRESH_REVIEW |
| P2-012 | MEDIUM | MIG-001 hostile pipeline + duplicate authorization/privacy policy and UX added | RESOLVED_PENDING_FRESH_REVIEW |

## Mechanical revision evidence

```text
PLAN_VALIDATION=PASS
REQUIREMENTS=19
PLAN_TASKS=28
QUEUE_TASKS=29
GRAPH=ACYCLIC
APPROVAL_BOUNDARY=PASS
SECRETS=NONE_DETECTED
DRAFT_BASELINE_SHA256=c28bd39a48c74839b6278bb40c93b67057b3f48aa1b866db5a03a73335b1c87a
```

## Fresh Pass 3

Verdict: `REVISE` — 3 HIGH, 2 MEDIUM.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P3-001 | HIGH | ISOFIX-001 now implements/pins final architecture, migrates fixtures if needed, reruns full matrix, and PILOT depends on fresh `ISOLATION_FINAL=PASS` | RESOLVED_PENDING_FRESH_REVIEW |
| P3-002 | HIGH | strict exact policy schema/types/action sets plus 32-mutant behavioral regression; empty/removal/duplicate/unknown/wrong-type policies fail | RESOLVED_PENDING_FRESH_REVIEW |
| P3-003 | HIGH | SEC-001 now has full plan scope/steps/tests/done-when; validator requires exact 30=30 task parity without exception | RESOLVED_PENDING_FRESH_REVIEW |
| P3-004 | MEDIUM | gate/status/ledger updated to current baseline counts/hash and Pass 3 findings; final values remain pending fresh review | RESOLVED_PENDING_FRESH_REVIEW |
| P3-005 | MEDIUM | validator parses bounded canonical owned paths, rejects escape/global wildcard, detects overlap, and requires dependency serialization; overlap mutant fails | RESOLVED_PENDING_FRESH_REVIEW |

Current evidence:

```text
MUTATION_TESTS=PASS
MUTANTS_KILLED=32
PLAN_VALIDATION=PASS
REQUIREMENTS=19
PLAN_TASKS=30
QUEUE_TASKS=30
TASK_PARITY=PASS
GRAPH=ACYCLIC
OWNED_PATHS=PASS
APPROVAL_BOUNDARY=PASS
SECRETS=NONE_DETECTED
DRAFT_BASELINE_SHA256=e109ffb6dfb0ed2ebfd4c4df31a2e5abf5097d01d81434289e71630453fe8029
```

## Fresh closure re-review (Pass 4)

Verdict: `REVISE` — 2 HIGH.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P4-001 | HIGH | Owned-path grammar now permits only canonical relative POSIX exact paths or terminal `/**`; rejects `.`, `..`, backslash, empty separator, absolute/global/mid-segment globs; semantic exact/tree overlap requires dependency serialization. All reported evasions plus overlap glob are permanent mutants. | RESOLVED_PENDING_FRESH_REVIEW |
| P4-002 | HIGH | Validator now requires exact schema v1, bot, project/profile/repo/worktree/chat/Bos, identity ref, FULL_AUTO/status/revocation/boundary, valid activation timestamp/nonempty source. Mutation matrix covers every normative field, including both bots changed together. | RESOLVED_PENDING_FRESH_REVIEW |

Current evidence:

```text
MUTATION_TESTS=PASS
MUTANTS_KILLED=73
PLAN_VALIDATION=PASS
REQUIREMENTS=19
PLAN_TASKS=30
QUEUE_TASKS=30
TASK_PARITY=PASS
GRAPH=ACYCLIC
OWNED_PATHS=PASS
APPROVAL_BOUNDARY=PASS
SECRETS=NONE_DETECTED
DRAFT_BASELINE_SHA256=b565f0587473328b4f7d843542c215ceffe0b5695fe2fbcec7d7c5feec198cbe
```

The baseline manifest now binds project-control artifacts plus README, `.hermes/plans/**`, validator source, and mutation-test source; gate/review/status/lock remain excluded to permit recording the verdict without self-invalidating the reviewed plan.

## Pass 5 adversarial closure

Verdict: `REVISE` — 3 HIGH, 1 MEDIUM.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P5-001 | HIGH | Validator now requires the exact canonical 30-task ID set in both plan and queue; removing EVAL-003 from both is a permanent killed mutant. | RESOLVED_PENDING_FRESH_REVIEW |
| P5-002 | HIGH | Parser requires exactly one dependencies/owned/status field; owned value must be entirely a comma-separated backtick-token list. Duplicate and malformed owned labels are killed mutants. | RESOLVED_PENDING_FRESH_REVIEW |
| P5-003 | MEDIUM | `activated_at` uses semantic `datetime.strptime` calendar validation; impossible date/time mutant is killed. | RESOLVED_PENDING_FRESH_REVIEW |
| P5-004 | HIGH | Canonical required edges are asserted: ISO→ISOFIX→PILOT and PILOT/MIGDEC/EXP→PROD. Removing each edge from both plan and queue is a killed mutant. | RESOLVED_PENDING_FRESH_REVIEW |

Current evidence:

```text
MUTATION_TESTS=PASS
MUTANTS_KILLED=82
PLAN_VALIDATION=PASS
REQUIREMENTS=19
PLAN_TASKS=30
QUEUE_TASKS=30
TASK_PARITY=PASS
GRAPH=ACYCLIC
OWNED_PATHS=PASS
APPROVAL_BOUNDARY=PASS
SECRETS=NONE_DETECTED
DRAFT_BASELINE_SHA256=6ab4c6a91d3104ec82466b35c7e4d1a150e0d77cdb6d0f59f844245c07f33f9e
```

## Pass 7 fresh closure

Verdict: `REVISE` — 2 HIGH, 1 MEDIUM; official baseline was structurally green but 26/73 additional adversarial mutants survived.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P7-001 | HIGH | Structured-label detection now applies NFKC/casefold/confusable-colon detection and rejects any requirements/dependencies/owned-paths/status lookalike not matching the one canonical byte grammar. Official suite includes lowercase, fullwidth/ratio colon, triple emphasis, indentation, duplicate, and malformed variants. | REVISED_PENDING_FRESH_REVIEW |
| P7-002 | HIGH | Plan accepts only canonical `### ID — Title` tasks; task-like headings/lists are rejected. Queue parser consumes one canonical table and rejects task-like pipe rows inside or outside it, including indentation/fullwidth/unknown/duplicate records. | REVISED_PENDING_FRESH_REVIEW |
| P7-003 | MEDIUM | Requirement scope is pinned per canonical task; requirement set expanded intentionally to exact R-001..R-022. Status remains pinned per task. | REVISED_PENDING_FRESH_REVIEW |

Material product revision after Pass 7:

- `R/FR-020`: versioned per-unit logo/template with immutable posted branding snapshot and no legal/financial identity override.
- `R/FR-021`: explicit many-to-many user/sales unit assignments with exactly one active unit context per action, switching/revocation/stale-preview protections.
- `R/FR-022`: typed versioned unit settings with draft/validate/preview/activate/rollback, unknown/script values denied, and no unit-name hardcoding/upstream-core patches.
- Added J-006 and MVP-AC-13..15; updated architecture, data model, RBAC, UX, task ownership, queue, traceability, and test strategy.
- Local evidence: validator PASS, 22 requirements, 30 plan/queue tasks, DAG/path/policy PASS, 112/112 official mutants killed, py_compile and diff check PASS.

## Pass 8 fresh closure

Verdict: `REVISE` — 4 HIGH + 2 MEDIUM.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P8-001 | HIGH | Plan/queue reject Unicode control, format, and surrogate characters; emphasis-style label candidates must be one canonical structured field. Cyrillic, zero-width, underscore emphasis, wrapper emphasis, and modifier-colon reproducers are permanent mutants. | REVISED_PENDING_FRESH_REVIEW |
| P8-002 | HIGH | Bounded Markdown container stripping detects nested blockquotes plus ordered/unordered list task records and queue rows globally. Blockquote/list/zero-width variants are permanent mutants. | REVISED_PENDING_FRESH_REVIEW |
| P8-003 | HIGH | `EXPECTED_REQUIREMENTS` is the sole exact contract for both plan fields and all 30 queue scope cells; divergence fails. Queue was mechanically synchronized. | REVISED_PENDING_FRESH_REVIEW |
| P8-004 | HIGH | R-021 ownership now includes ADP-002, CRM-001, ISO-001, ISOFIX-001, FLOW-002, REM-001, and RPT-001, with zero/one/multi, switch, expiry/revocation, stale cache/preview across UI/API/direct URL/search/report/export/PDF/attachment/notification/jobs. Traceability and MVP-AC-14 aligned. | REVISED_PENDING_FRESH_REVIEW |
| P8-005 | MEDIUM | Unit config uses monotonic `expected_version` CAS, non-overlapping effective-interval constraint, and atomic validate/retire/activate/snapshot/audit transaction; deterministic conflict/zero-partial-state and activate/rollback race tests are normative. | REVISED_PENDING_FRESH_REVIEW |
| P8-006 | MEDIUM | STATUS/queue/review/gate/counts synchronized. Explicit untracked whitespace scan added because repository has no HEAD and `git diff --check` alone is insufficient. | REVISED_PENDING_FRESH_REVIEW |

Local evidence: validator PASS; 22 requirements; 30 plan/queue tasks; parity/DAG/paths/policy/secrets PASS; 125/125 mutants killed; py_compile/diff check/untracked whitespace check PASS. Baseline `cc5ac65b7564b1c40977a06650d3140e0078c13a97b7d0bf4c4dee93847ca2ff`.

## Pass 9 fresh closure

Verdict: `REVISE` — 2 HIGH.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P9-001 | HIGH | EXECUTION_PLAN now has a closed character grammar: ASCII plus only canonical em dash and the documented bidirectional arrow. Unknown non-R task tokens anywhere fail; wrapped HTML/code/link/escaped/strikethrough structured-label tokens fail unless the whole line is one canonical field. Unicode separator/space and Greek/Cyrillic reproducers are permanent mutants. | REVISED_PENDING_FRESH_REVIEW |
| P9-002 | HIGH | TASK_QUEUE is ASCII-only; every line containing a pipe must be exactly the one header, separator, or canonical six-cell row. Thus inline-code/link/HTML/list/blockquote wrappers, extra tables, Unicode separators/confusables, and rows outside the canonical table fail globally. | REVISED_PENDING_FRESH_REVIEW |

Local evidence: validator PASS; 22 requirements; 30 plan/queue tasks; parity/DAG/paths/policy/secrets PASS; 150/150 mutants killed; py_compile/diff check PASS; 37 untracked files scanned with whitespace PASS. Baseline `d55df85c8a9a8ac5cf893826357d9092ec09eb78e0cb5cee837b90157c2d8ba2`.

## Pass 10 fresh closure

Verdict: `REVISE` — 3 HIGH.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P10-001 | HIGH | Plan byte grammar now rejects all ASCII controls except LF, every non-ASCII character except em dash, and entity/escape/HTML openers. Em dash is legal only in the exact title and 30 canonical headings. Arrow prose was removed. Global task scan has no word-boundary bypass. Raw files are opened with `newline=""` so CR cannot normalize away. Entity, escape, boundary-ID, arrow, NUL/tab/VT/FF/CR reproducers are permanent mutants. | REVISED_PENDING_FRESH_REVIEW |
| P10-002 | HIGH | Queue is printable ASCII + LF only, rejects entity/escape/HTML syntax, globally rejects unknown task IDs even without pipes, and requires every literal pipe line to be exact header/separator/row. Entity-pipe, plain/code task, and control-byte reproducers are permanent mutants. | REVISED_PENDING_FRESH_REVIEW |
| P10-003 | HIGH | Exact literal `EXPECTED_OWNED_PATHS` and `EXPECTED_QUEUE_OWNED` contracts bind every one of 30 tasks. Syntactically valid substitution, addition/removal/reordering, and arbitrary queue summary fail rather than merely passing overlap grammar. | REVISED_PENDING_FRESH_REVIEW |

Local evidence: validator PASS; 22 requirements; 30 plan/queue tasks; parity/DAG/paths/policy/secrets PASS; 173/173 mutants; py_compile/diff PASS; byte scan of 37 untracked files PASS. Baseline `e46cdb95430f3c56f54de50c2d7de9385e43b650d1b8f94ef60f6f3acab43020`.

## Pass 11 fresh closure

Verdict: `REVISE` — 2 HIGH + 1 MEDIUM.

| ID | Sev | Revision/closure evidence | Status |
|---|---|---|---|
| P11-001 | HIGH | `EXECUTION_PLAN.md` is now byte-exact bound by SHA-256 in the manifest-bound validator in addition to semantic parsing. Extra em dash/title/aux heading, hidden canonical task, fused requirement, duplicate Steps/Tests/Done, controls/entities/wrappers, or any other byte mutation fails. Intentional changes require validator-contract revision and therefore produce a new overall baseline identity. | REVISED_PENDING_FRESH_REVIEW |
| P11-002 | HIGH | `TASK_QUEUE.md` is likewise byte-exact bound; hidden canonical IDs, unknown/fused requirements, orphan headers/separators, extra/encoded rows/tables, controls, or any byte mutation fails. Semantic exact task/scope/dependency/status/path checks remain defense in depth. | REVISED_PENDING_FRESH_REVIEW |
| P11-003 | MEDIUM | Removed plan/invariant Markdown hard-break whitespace; structured-field grammar no longer depends on trailing spaces; queue has exactly one terminal LF. A temporary empty Git index stages all 37 candidates and `git diff --cached --check` passes, then the index is deleted. | REVISED_PENDING_FRESH_REVIEW |

Local evidence: validator PASS; 22 requirements; 30 plan/queue tasks; parity/DAG/paths/policy/secrets PASS; 190/190 mutants; py_compile, normal diff, and temporary-index full-candidate diff checks PASS. Baseline `be196bf199293bf387dece9035ad9e355894dafdac52acb0861a0fbf879d28ab`.

## Pass 12 fresh closure

Verdict: `PASS`.

- Findings: 0 CRITICAL, 0 HIGH, 0 unresolved MEDIUM.
- P11-001, P11-002, and P11-003 independently verified closed.
- Baseline `be196bf199293bf387dece9035ad9e355894dafdac52acb0861a0fbf879d28ab` independently recomputed over 32 manifest files and matched exactly.
- Exact machine-file hashes: EXECUTION_PLAN `dac7bf7a42ac0a631847f63b1f637ce136b2b6295313f6cb80dc13714d36d560`; TASK_QUEUE `c151b2eac3fac7638ef35b21d9d4cb90f4da2091052b3fd65efdc0fd0b5bd6dc`.
- Official mutations: 190/190 killed. Independent mutations: 61/61 passed, including synchronized file/hash/validator/test changes that could not preserve reviewed baseline identity.
- Exactly 22 requirements, 30 canonical tasks/queue rows, 68 acyclic edges, all mandatory edges, exact scope/status/path contracts, policy/prohibition/approval/secret checks PASS.
- R-020..R-022, R-021 native/gateway surfaces, atomic configuration CAS/rollback, ERPNext candidate-only state, and owner/expert blockers are consistent.
- Temporary empty Git index staged all 37 candidate files; `git diff --cached --check` PASS; temporary index cleaned and real index untouched.

## Writer amendment review

Baseline: `90cbb1fb1204f7dd98f56e6ad45d05e5e32af65926da35cb7de77a95a2a936ae`.

Bos designated Hermes as sole source writer. Claude Code authentication is no longer an implementation prerequisite. One-writer lease, TDD, independent read-only QA, evidence requirements, and production/legal/financial prohibitions are unchanged.

Local structural evidence: 190/190 mutants, validator PASS, 22 requirements, 30 plan/queue tasks, parity/DAG/paths/policy/secrets PASS.

Status: `REVISE` — WA-001 HIGH (stale manifest-bound Hermes plan) and WA-002 MEDIUM (candidate whitespace EOF) found by fresh review. Both revised.

Fresh closure review 2: `PASS` on baseline `6430dcfff02badc5b420c3e7714b0c10960097fcf3a24a75cb1174cde1dd2094` with 0 CRITICAL, 0 HIGH, and 0 unresolved MEDIUM. WA-001 and WA-002 are independently verified closed; 32-file manifest, 190/190 mutations, 22/30/30/68 structural counts, exact hashes, full-candidate whitespace, ignored local Claude settings, approval boundary, and prohibitions all PASS.

Control transition review: `PASS` on baseline `f247e31afee19489ca7bec75da76792f39127b8dee5d1a80c6aba0e86b200848` with 0 CRITICAL, 0 HIGH, and 0 unresolved MEDIUM. Only PLAN-001 became DONE and its dependency-ready child FND-001 became READY; no requirement, dependency, path, task, or evidence contract drifted.

## FND-001 independent code QA

Final verdict: `PASS` on source candidate `96fdb91fbb4cd3c10c610faacd0fae47d7b0a911dd963b120fefaf6caffba300` with 0 CRITICAL, 0 HIGH, and 0 unresolved MEDIUM.

- Initial review found one HIGH and two MEDIUM; first retry found one residual HIGH and one regression-coverage MEDIUM.
- All findings were closed through test-first revisions and two fresh read-only QA retries.
- Final source evidence: 14/14 unit tests PASS; compileall PASS; account-alias and Money-bound targeted mutants killed; field namespaces, exact state types, canonical money, signed zero, redaction, no-network, and secret scans PASS.
- Final reviewer: delegation `deleg_60855c93`; no reviewer writes.
- Completion transition: FND-001 DONE; direct dependency children FND-002, FND-003, and FND-004 READY; no other task promoted.

## FND-002 independent code QA

Final verdict: `PASS` on source candidate `c9971565876fa8772b5c6fd4153f218e1affe38b84818ef45f42f63599fd6088` from trusted HEAD `f5860d3c5482604cabca64b7d8d78e27ded3116c`, with 0 CRITICAL, 0 HIGH, and 0 unresolved MEDIUM.

- Five technical remediation loops closed malformed/duck-typed authority inputs, assignment lifecycle replay, action vocabulary drift, timezone comparability and exception-chain disclosure, decision invariants, exact-type boundaries, OWNER reachability, and permanent mutation coverage.
- Final source evidence: 12/12 focused authz tests; 26/26 full unit tests; 128/128 adversarial checks; 9/9 earlier security mutants, 3/3 OWNER mutants, and 2/2 permanent conversion-chain mutants killed; official validator mutations 190/190; compileall, validator, diff, secret/network/provider/subprocess/database scans PASS.
- Final reviewer: delegation `deleg_bf2be0ff`; no reviewer writes.
- Completion transition candidate changes only FND-002 READY to DONE. FND-003 and FND-004 remain READY; UNIT-001 remains BACKLOG because FND-003 is still incomplete. Writer lease is FREE.
- The transition remains non-canonical until fresh independent integrated transition review and gate promotion.

Fresh independent transition reviewer `deleg_52a426a8`: `PASS` on integrated candidate `1e4ab3f5d7fe184f657989648bdd486b6d86307664d9dcc0593ae321e2226773` and validator baseline `cb9f2583e46718d83f9fe6ae24f4e27617548d30cf9f05b0fb230f305725a846`, with 0 CRITICAL, 0 HIGH, and 0 unresolved MEDIUM. The reviewer confirmed only FND-002 changed READY to DONE; FND-003/FND-004 remain READY; UNIT-001 remains BACKLOG; 22/30/30/68 structural counts, exact plan/queue hashes, 26/26 tests, 190/190 mutations, source done-when, lease release, approval boundary, and production prohibitions all PASS.

## FND-004 independent code QA — round 1

Reviewer: delegation `deleg_abe7c340` (read-only; `git status` byte-identical before/after; 93/93 baseline green confirmed by reviewer).

Verdict: `FAIL` — 1 CRITICAL, 2 HIGH, 2 MEDIUM, 4 LOW.

| ID | Sev | Finding | Closure (revision by Hermes, TDD) | Status |
|---|---|---|---|---|
| FND004-QA-01 | CRITICAL | Retry of in-flight PENDING claim re-invoked provider (blind replay) | `MutationOutcome.created` flag; executor raises `RecoveryRequired` on existing non-terminal claim; tests `test_pending_retry_does_not_invoke_provider`, `test_uncertain_retry_does_not_invoke_provider`; mutant killed | RESOLVED |
| FND004-QA-02 | HIGH | Durable reclaim: no fencing takeover, stale owner never rejected durably, dead branch | Durable claim rewrite: CLAIM_HELD for owner re-claim, expiry-gated transactional takeover updating fencing/lease, STALE_FENCING for lower token or premature higher token, `register_fencing` no-op shim; tests `test_takeover_after_expiry_updates_fencing_and_rejects_stale`, `test_non_terminal_reclaim_returns_distinct_status`, `test_lower_token_rejected_*`, `test_higher_token_rejected_while_stored_lease_live`; mutants killed | RESOLVED |
| FND004-QA-03 | HIGH | Success-audit failure contradicted store (RESOLVED_PRESENT vs `local_write_failed` audit) | Separated try blocks; success-audit failure transitions outcome to UNCERTAIN and audits `terminal_audit_failed`; test `test_success_audit_failure_marks_uncertain_consistently`; mutant killed | RESOLVED |
| FND004-QA-04 | MEDIUM | Durable `audit_event` table unwired | Deferred to REC-001 (durable worker/operator queue owns append-only writer + export); recorded as task note in PLAN_REVIEW; DDL retained as forward-compatible schema | ACCEPTED_DEFERRED_REC_001 |
| FND004-QA-05 | MEDIUM | Executor did not bind IdempotencyKey; no canonicalization version on in-memory path | `execute(namespace=..., canonicalization_version=...)` derives key and fails closed on mismatch; tests `test_mismatched_key_fails_closed`, `test_matching_key_executes_once`; mutant killed | RESOLVED |
| FND004-QA-06 | LOW | Dead ALREADY_RESOLVED branch | Removed via rewrite; both branches now carry distinct semantics and are test-covered | RESOLVED |
| FND004-QA-07 | LOW | In-memory store claimed thread-safe without locking | `threading.Lock` on claim critical section; `test_claim_critical_section_uses_lock`, `test_concurrent_same_key_claim_single_creator` (32-thread barrier); lock-removal mutant killed | RESOLVED |
| FND004-QA-08 | LOW | Process-global fencing counter | Documented as fixture limitation; durable store binds fencing per-key transactionally | ACCEPTED_FIXTURE_LIMIT |
| FND004-QA-09 | LOW | Credential-prefix check cosmetic | Accepted: derived keys are always `sha256:`-hex; guard covers hand-constructed keys only | ACCEPTED_FIXTURE_LIMIT |

Additional defect found and fixed during survivor closure: re-claim of a freshly-created PENDING row returned `created=True` to non-creator callers (32-thread reproducer) — fixed by normalizing `created=False` on existing-row return; regression test added.

Revision evidence: 107/107 unittest PASS; compileall PASS; `git diff --check` PASS; plan-gate validator PASS (22 requirements, 30/30 tasks, DAG, owned paths, approval boundary, no secrets); official validator mutation suite 190/190 killed; FND-004 targeted adversarial mutants 15/15 killed (including both initial survivors).

QA retry: fresh independent read-only reviewer `deleg_e64fcb56` — verdict `PASS`. All RESOLVED rows verified closed; deferral/acceptance notes confirmed; no new findings; 5/5 fresh adversarial mutants killed; probe A (PENDING retry, zero provider calls) and probe B2 (stale worker after durable takeover rejected, fencing never regresses) PASS; reviewer git status byte-identical before/after; helper scripts confined to /tmp.
