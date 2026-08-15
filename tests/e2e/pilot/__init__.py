"""PILOT-001 synthetic E2E acceptance suite.

Owned paths: tests/e2e/pilot/** and docs/evidence/pilot/** only.

All scenarios run against the synthetic harness (`_harness.py`) which wires
the real production components (UNIT-001 registry/settings, FND-002 authz,
FND-003 financial policy, FLOW-001/002 workflows, CRM-001 port, ISOFIX-001
final isolation policy) over the network-disabled fixture adapters with
synthetic opaque references only. No live pilot mutation, no credentials,
no native ERPNext unit users (gateway-only final architecture).
"""
