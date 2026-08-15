"""ISO-001 native ERP isolation test harness.

Per-user session login, synthetic user/user-permission seeding, marker
record seeding, and a probe runner that records raw JSONL evidence.

Owned paths only: tests/security/native_erp/** and
docs/evidence/native-isolation/**.

Synthetic opaque refs only. The admin password below is the same
synthetic pilot credential already used by tests/integration/erpnext_crm.
"""
from __future__ import annotations

import json
import os
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence" / "native-isolation"
RAW_DIR = EVIDENCE_DIR / "raw"

BASE_URL = os.environ.get("ERPNEXT_URL", "http://127.0.0.1:18080")
SITE_NAME = os.environ.get("ERPNEXT_SITE", "erpnext-pilot.localhost")
ADMIN_USER = "Administrator"
ADMIN_PASSWORD = os.environ.get(
    "ERPNEXT_ADMIN_PASSWORD",
    "2be0d0946a2e3d841301c45fb19dde011d179fdcc044b3a74893071eac314090",
)
TIMEOUT = 30

# Pinned pilot version under test (asserted by probes for ADR evidence).
PINNED_ERPNEXT_VERSION = "16.32.1"

# Units under test
UNIT_BM = "UNIT-BM"
UNIT_P1 = "UNIT-PR1ME"

# Synthetic users (never real personal data)
USER_SALES_BM = "iso-sales-bm@example.test"
USER_SALES_P1 = "iso-sales-p1@example.test"
USER_OWNER = "iso-owner@example.test"
USER_DEACTIVATED = "iso-deactivated@example.test"
USER_UNKNOWN = "iso-unknown@example.test"  # never created

# Synthetic per-user passwords (opaque, synthetic)
USER_PASSWORDS = {
    USER_SALES_BM: "iso-bm-9f2c7a1d4e8b",
    USER_SALES_P1: "iso-p1-3d6a9c2f5b7e",
    USER_OWNER: "iso-own-7b1e4a8c3d6f",
    USER_DEACTIVATED: "iso-deact-2c5f8a1b4e7d",
}

# Synthetic marker records (opaque refs; no real personal data)
LEAD_BM = "ISO-LEAD-BM-001"
LEAD_P1 = "ISO-LEAD-P1-001"
CUSTOMER_BM = "ISO-CUST-BM-001"
CUSTOMER_P1 = "ISO-CUST-P1-001"
QUOTATION_BM = "ISO-QTN-BM-001"
QUOTATION_P1 = "ISO-QTN-P1-001"
ITEM_ISO = "ISO-ITEM-001"

# Opaque marker strings seeded into the OTHER unit's records; probes scan
# responses for these strings to detect cross-unit leaks.
MARKER_BM = "ISOMARKER-BM-7f3a9c2e"
MARKER_P1 = "ISOMARKER-P1-4b8d1e6a"

ATTACHMENT_NAME = "iso-private-bm-001.txt"
ATTACHMENT_CONTENT = "ISO-001 private attachment marker ISOMARKER-BM-7f3a9c2e\n"

# Leak tokens: cross-unit record names / attachment filenames are themselves
# leak evidence (a unit user enumerating the other unit's record NAMES is a
# leak even when the opaque marker string is absent). Scanned in addition to
# the opaque markers. `LEAD_*`/`QUOTATION_*` are autoname aliases resolved at
# runtime; their static prefixes are covered by the marker strings.
LEAK_TOKENS: tuple[str, ...] = (
    MARKER_BM,
    MARKER_P1,
    CUSTOMER_BM,
    CUSTOMER_P1,
    ATTACHMENT_NAME,
)


class ProbeResult:
    """One probe observation for JSONL evidence."""

    def __init__(
        self,
        surface: str,
        actor: str,
        action: str,
        expected: str,
        status: int | None,
        leaked_markers: list[str],
        timing_bucket: str,
        detail: str = "",
    ) -> None:
        self.surface = surface
        self.actor = actor
        self.action = action
        self.expected = expected
        self.status = status
        self.leaked_markers = leaked_markers
        self.timing_bucket = timing_bucket
        self.detail = detail
        self.ts = datetime.now(timezone.utc).isoformat()

    @property
    def leaked(self) -> bool:
        return bool(self.leaked_markers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "surface": self.surface,
            "actor": self.actor,
            "action": self.action,
            "expected": self.expected,
            "status": self.status,
            "leaked": self.leaked,
            "leaked_markers": self.leaked_markers,
            "timing_bucket": self.timing_bucket,
            "detail": self.detail,
        }


class ProbeRecorder:
    """Collects probe results and writes raw JSONL evidence.

    Each recorder instance stamps every row with a unique `run_id`
    (utc timestamp + uuid suffix) so matrix generation groups by an
    explicit run boundary instead of inferring runs from timing gaps
    (QA F-5 closure).
    """

    _instance: "ProbeRecorder | None" = None

    def __init__(self) -> None:
        import uuid
        self.results: list[ProbeResult] = []
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.jsonl_path = RAW_DIR / f"probes-{day}.jsonl"
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "-" + uuid.uuid4().hex[:8]
        )

    @classmethod
    def instance(cls) -> "ProbeRecorder":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record(self, result: ProbeResult) -> None:
        self.results.append(result)
        row = result.to_dict()
        row["run_id"] = self.run_id
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _timing_bucket(elapsed_s: float) -> str:
    if elapsed_s < 0.25:
        return "fast"
    if elapsed_s < 1.0:
        return "medium"
    return "slow"


def scan_markers(body: bytes | str,
                 tokens: tuple[str, ...] | list[str] | None = None) -> list[str]:
    """Return which protected leak tokens appear in a response body.

    Default scans ALL leak tokens (both units). Callers that know the
    probing actor should pass `tokens=cross_unit_tokens(actor)` so that
    legitimate own-unit content is not misrecorded as a leak.
    """
    text = body.decode(errors="replace") if isinstance(body, bytes) else body
    found = []
    for marker in (tokens if tokens is not None else LEAK_TOKENS):
        if marker in text:
            found.append(marker)
    return found


def cross_unit_tokens(actor: str) -> tuple[str, ...]:
    """Leak tokens belonging to the unit(s) the actor must NOT see.

    - UNIT-BM-scoped actors: P1 tokens.
    - UNIT-PR1ME-scoped actors: BM tokens.
    - Owner (explicit roll-up by design) and unknown/deactivated actors:
      no tokens — owner visibility is accepted scope; unknown/deactivated
      actors should be denied outright (status assertion), so any token
      would be a secondary signal.
    """
    if actor == USER_SALES_BM:
        return (MARKER_P1, CUSTOMER_P1)
    if actor == USER_SALES_P1:
        return (MARKER_BM, CUSTOMER_BM, ATTACHMENT_NAME)
    return ()


class UserSession:
    """Per-user ERPNext session via POST /api/method/login + CookieJar."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self._password = password
        self._cookies = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )
        self.logged_in = False

    def login(self) -> tuple[int, bytes]:
        body = urllib.parse.urlencode(
            {"usr": self.username, "pwd": self._password}
        ).encode()
        req = urllib.request.Request(
            f"{BASE_URL}/api/method/login",
            data=body,
            headers={"Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=TIMEOUT) as resp:
                payload = resp.read()
                self.logged_in = resp.status == 200 and b"Logged In" in payload
                return resp.status, payload
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        form: dict[str, str] | None = None,
    ) -> tuple[int, bytes, float]:
        """Raw request. Returns (status, body_bytes, elapsed_seconds).

        Never raises on HTTP error status — probes need to observe 4xx bodies.
        """
        url = f"{BASE_URL}{urllib.parse.quote(path, safe='/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        body: bytes | None = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        start = time.monotonic()
        try:
            with self._opener.open(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read(), time.monotonic() - start
        except urllib.error.HTTPError as e:
            return e.code, e.read(), time.monotonic() - start

    def get(self, path: str, params: dict[str, str] | None = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, data: dict[str, Any] | None = None,
             form: dict[str, str] | None = None):
        return self.request("POST", path, data=data, form=form)

    def put(self, path: str, data: dict[str, Any]):
        return self.request("PUT", path, data=data)


_admin_session: UserSession | None = None


def admin_session() -> UserSession:
    """Admin session — used ONLY for seeding and read-back assertions."""
    global _admin_session
    if _admin_session is None:
        sess = UserSession(ADMIN_USER, ADMIN_PASSWORD)
        status, _ = sess.login()
        if status != 200:
            raise RuntimeError(f"admin login failed: HTTP {status}")
        _admin_session = sess
    return _admin_session


def user_session(username: str) -> UserSession:
    """Fresh per-user session (never shares cookies with admin)."""
    sess = UserSession(username, USER_PASSWORDS[username])
    status, _ = sess.login()
    if status != 200 or not sess.logged_in:
        raise RuntimeError(f"login failed for {username}: HTTP {status}")
    return sess


def unknown_user_login() -> tuple[int, bytes]:
    """Attempt login with a never-created synthetic user."""
    sess = UserSession(USER_UNKNOWN, "iso-unknown-0000000000")
    return sess.login()


def deactivated_user_login() -> tuple[int, bytes]:
    """Attempt login with the deactivated synthetic user."""
    sess = UserSession(USER_DEACTIVATED, USER_PASSWORDS[USER_DEACTIVATED])
    return sess.login()


# ---------------------------------------------------------------------------
# Admin-side helpers (seeding / read-back only)
# ---------------------------------------------------------------------------


def admin_get(path: str, params: dict[str, str] | None = None) -> tuple[int, bytes]:
    status, body, _ = admin_session().get(path, params=params)
    return status, body


def admin_exists(doctype: str, name: str) -> bool:
    status, _ = admin_get(f"/api/resource/{doctype}/{name}")
    return status == 200


def admin_create(doctype: str, data: dict[str, Any]) -> tuple[int, bytes]:
    status, body, _ = admin_session().post(f"/api/resource/{doctype}", data=data)
    return status, body


def admin_put(doctype: str, name: str, data: dict[str, Any]) -> tuple[int, bytes]:
    status, body, _ = admin_session().put(f"/api/resource/{doctype}/{name}", data)
    return status, body


def seed_users() -> dict[str, bool]:
    """Idempotently create synthetic users with roles + unit User Permissions.

    Never deletes; repairs drift: existing users are re-enabled (except the
    deactivated fixture) so the ISO-001 rollback path
    (ISO001_ENABLE_UNIT_USERS=1) actually restores probe capability.
    Returns created-flags.
    """
    created: dict[str, bool] = {}
    specs = [
        (USER_SALES_BM, UNIT_BM, ["Sales User"]),
        (USER_SALES_P1, UNIT_P1, ["Sales User"]),
        (USER_OWNER, None, ["Sales Manager", "Sales Master Manager"]),
        (USER_DEACTIVATED, UNIT_BM, ["Sales User"]),
    ]
    for email, unit, roles in specs:
        key = f"user:{email}"
        if admin_exists("User", email):
            created[key] = False
            # Repair enabled-drift for all but the deactivated fixture
            # (re-enabled separately below as a no-op guard).
            if email != USER_DEACTIVATED:
                status, body = admin_get(f"/api/resource/User/{email}")
                if status == 200:
                    try:
                        enabled = int(json.loads(body)["data"].get("enabled", 0))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        enabled = 0
                    if enabled != 1:
                        admin_put("User", email, {"enabled": 1})
        else:
            payload: dict[str, Any] = {
                "email": email,
                "first_name": email.split("@")[0],
                "send_welcome_email": 0,
                "new_password": USER_PASSWORDS[email],
                "roles": [{"role": r} for r in roles],
            }
            status, body = admin_create("User", payload)
            if status not in (200, 201):
                raise RuntimeError(f"create user {email} failed: {status} {body[:300]}")
            created[key] = True
        # ensure password is the known synthetic one (idempotent reset)
        admin_session().post(
            "/api/method/frappe.core.doctype.user.user.update_password",
            form={"user": email, "new_password": USER_PASSWORDS[email]},
        )
        # unit scoping via User Permission
        if unit is not None:
            up_key = f"user_permission:{email}:{unit}"
            flt = json.dumps([["user", "=", email], ["allow", "=", "Company"],
                              ["for_value", "=", unit]])
            status, body = admin_get("/api/resource/User Permission",
                                     params={"filters": flt, "limit_page_length": "1"})
            exists = status == 200 and json.loads(body).get("data")
            if exists:
                created[up_key] = False
            else:
                status, body = admin_create("User Permission", {
                    "user": email,
                    "allow": "Company",
                    "for_value": unit,
                    "apply_to_all_doctypes": 1,
                })
                if status not in (200, 201):
                    raise RuntimeError(
                        f"user permission {email}->{unit} failed: {status} {body[:300]}")
                created[up_key] = True
    # deactivate the deactivated fixture user
    if admin_exists("User", USER_DEACTIVATED):
        admin_put("User", USER_DEACTIVATED, {"enabled": 0})
        created["user_deactivated_flag"] = True
    return created


def seed_markers() -> dict[str, bool]:
    """Idempotently seed per-unit marker Leads/Customers/Quotations + a
    private attachment on the BM lead. All refs synthetic opaque."""
    created: dict[str, bool] = {}
    created["fiscal_year_p1"] = _ensure_fiscal_year_company("2026", UNIT_P1)

    def ensure(doctype: str, name_field_value: str, payload: dict[str, Any]) -> bool:
        if admin_exists(doctype, name_field_value):
            return False
        status, body = admin_create(doctype, payload)
        if status not in (200, 201):
            raise RuntimeError(
                f"seed {doctype} {name_field_value} failed: {status} {body[:300]}")
        return True

    def ensure_by_marker(doctype: str, marker: str, payload: dict[str, Any]) -> bool:
        """For autonamed doctypes (Lead/Quotation): locate via marker field."""
        field = ("custom_contact_handle" if doctype == "Lead"
                 else "custom_crm_customer_ref")
        flt = json.dumps([[field, "=", marker]])
        status, body = admin_get(f"/api/resource/{doctype}",
                                 params={"filters": flt, "limit_page_length": "1"})
        if status == 200 and json.loads(body).get("data"):
            return False
        status, body = admin_create(doctype, payload)
        if status not in (200, 201):
            raise RuntimeError(
                f"seed {doctype} marker {marker} failed: {status} {body[:300]}")
        return True

    created["lead_bm"] = ensure_by_marker("Lead", MARKER_BM, {
        "lead_name": "ISO Synth BM",
        "company": UNIT_BM,
        "custom_owner_actor_ref": "USR-ISO-BM",
        "custom_contact_channel": "SYNTH",
        "custom_contact_handle": MARKER_BM,
        "status": "Lead",
        "naming_series": "CRM-LEAD-.YYYY.-",
        # Force name via naming: we set lead_name; name is autogenerated, so we
        # instead locate via custom handle below if autogen differs.
    })
    created["lead_p1"] = ensure_by_marker("Lead", MARKER_P1, {
        "lead_name": "ISO Synth P1",
        "company": UNIT_P1,
        "custom_owner_actor_ref": "USR-ISO-P1",
        "custom_contact_channel": "SYNTH",
        "custom_contact_handle": MARKER_P1,
        "status": "Lead",
        "naming_series": "CRM-LEAD-.YYYY.-",
    })
    created["customer_bm"] = ensure("Customer", CUSTOMER_BM, {
        "customer_name": CUSTOMER_BM,
        "customer_type": "Company",
        "customer_group": "Commercial",
        "territory": "All Territories",
    })
    created["customer_p1"] = ensure("Customer", CUSTOMER_P1, {
        "customer_name": CUSTOMER_P1,
        "customer_type": "Company",
        "customer_group": "Commercial",
        "territory": "All Territories",
    })
    created["item"] = ensure("Item", ITEM_ISO, {
        "item_code": ITEM_ISO,
        "item_name": ITEM_ISO,
        "item_group": "All Item Groups",
        "stock_uom": "Nos",
        "is_stock_item": 0,
    })
    created["quotation_bm"] = ensure_by_marker("Quotation", MARKER_BM, {
        "name": QUOTATION_BM,
        "quotation_to": "Customer",
        "party_name": CUSTOMER_BM,
        "company": UNIT_BM,
        "custom_crm_total_amount": "1000",
        "custom_crm_customer_ref": MARKER_BM,
        "currency": "IDR",
        "conversion_rate": 1,
        "items": [{"item_code": ITEM_ISO, "qty": 1, "rate": 1000}],
    })
    created["quotation_p1"] = ensure_by_marker("Quotation", MARKER_P1, {
        "name": QUOTATION_P1,
        "quotation_to": "Customer",
        "party_name": CUSTOMER_P1,
        "company": UNIT_P1,
        "custom_crm_total_amount": "2000",
        "custom_crm_customer_ref": MARKER_P1,
        "currency": "IDR",
        "conversion_rate": 1,
        "items": [{"item_code": ITEM_ISO, "qty": 1, "rate": 2000}],
    })
    created["attachment_bm"] = _seed_private_attachment()
    return created


def _ensure_fiscal_year_company(year: str, company: str) -> bool:
    """Ensure fiscal year covers the given company (idempotent)."""
    status, body = admin_get(f"/api/resource/Fiscal Year/{year}")
    if status != 200:
        raise RuntimeError(f"fiscal year {year} missing")
    doc = json.loads(body)["data"]
    companies = [c.get("company") for c in doc.get("companies", [])]
    if company in companies:
        return False
    companies_docs = doc.get("companies", []) + [{"company": company}]
    status, body = admin_put("Fiscal Year", year, {"companies": companies_docs})
    if status not in (200, 202):
        raise RuntimeError(f"fiscal year update failed: {status} {body[:300]}")
    return True


def _seed_private_attachment() -> bool:
    """Attach a private file to the BM marker lead (idempotent)."""
    flt = json.dumps([["file_name", "=", ATTACHMENT_NAME],
                      ["attached_to_doctype", "=", "Lead"]])
    status, body = admin_get("/api/resource/File",
                             params={"filters": flt, "limit_page_length": "1"})
    if status == 200 and json.loads(body).get("data"):
        return False
    lead_name = find_lead_name_by_marker(MARKER_BM)
    if not lead_name:
        raise RuntimeError("BM marker lead missing; cannot attach file")
    import base64
    status, body = admin_create("File", {
        "file_name": ATTACHMENT_NAME,
        "attached_to_doctype": "Lead",
        "attached_to_name": lead_name,
        "is_private": 1,
        "content": base64.b64encode(ATTACHMENT_CONTENT.encode()).decode(),
    })
    if status not in (200, 201):
        raise RuntimeError(f"seed attachment failed: {status} {body[:300]}")
    return True


def find_quotation_name_by_marker(marker: str) -> str | None:
    """Admin-side lookup of a seeded Quotation's autogenerated name."""
    flt = json.dumps([["custom_crm_customer_ref", "=", marker]])
    status, body = admin_get("/api/resource/Quotation", params={
        "filters": flt, "fields": json.dumps(["name", "company"])})
    if status != 200:
        return None
    data = json.loads(body).get("data") or []
    return data[0]["name"] if data else None


def find_lead_name_by_marker(marker: str) -> str | None:
    """Admin-side lookup of a seeded Lead's autogenerated name by marker."""
    flt = json.dumps([["custom_contact_handle", "=", marker]])
    status, body = admin_get("/api/resource/Lead", params={
        "filters": flt, "fields": json.dumps(["name", "company"])})
    if status != 200:
        return None
    data = json.loads(body).get("data") or []
    return data[0]["name"] if data else None


def ensure_all_seeded() -> None:
    """Seed everything; raise if pilot unreachable."""
    seed_users()
    seed_markers()


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


def record_probe(
    surface: str,
    actor: str,
    action: str,
    expected: str,
    status: int | None,
    body: bytes,
    elapsed: float,
    detail: str = "",
) -> ProbeResult:
    """Record one probe observation into the raw JSONL evidence log."""
    result = ProbeResult(
        surface=surface,
        actor=actor,
        action=action,
        expected=expected,
        status=status,
        leaked_markers=scan_markers(body, tokens=cross_unit_tokens(actor)),
        timing_bucket=_timing_bucket(elapsed),
        detail=detail[:400],
    )
    ProbeRecorder.instance().record(result)
    return result


class IsolationProbeTestCase(unittest.TestCase):
    """Base for ISO-001 probe suites: seeds fixtures, opens per-user sessions.

    Post-ISOFIX-001 the pilot's steady state is gateway-only: unit-scoped
    users are DISABLED. These historical qualification suites therefore
    require ISO001_ENABLE_UNIT_USERS=1 (they re-enable the users via the
    idempotent seeder, probe the native architecture, and their leak
    failures remain the ISO-001 evidence). Default runs skip them so the
    final-architecture full suite is green; the recorded JSONL/matrix
    evidence under docs/evidence/native-isolation/ remains the frozen
    ISO-001 proof.
    """

    recorder: ProbeRecorder
    sess_bm: UserSession
    sess_p1: UserSession
    sess_owner: UserSession

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("ISO001_ENABLE_UNIT_USERS") != "1":
            raise unittest.SkipTest(
                "ISO-001 native suites require ISO001_ENABLE_UNIT_USERS=1 "
                "(post-ISOFIX-001 pilot steady state disables unit users)"
            )
        ensure_all_seeded()
        cls.recorder = ProbeRecorder.instance()
        cls.sess_bm = user_session(USER_SALES_BM)
        cls.sess_p1 = user_session(USER_SALES_P1)
        cls.sess_owner = user_session(USER_OWNER)
        cls.lead_bm_name = find_lead_name_by_marker(MARKER_BM)
        cls.lead_p1_name = find_lead_name_by_marker(MARKER_P1)
        cls.qtn_bm_name = find_quotation_name_by_marker(MARKER_BM)
        cls.qtn_p1_name = find_quotation_name_by_marker(MARKER_P1)
        if not all([cls.lead_bm_name, cls.lead_p1_name,
                    cls.qtn_bm_name, cls.qtn_p1_name]):
            raise RuntimeError("marker records missing — seeder broken")

    # -- convenience ----------------------------------------------------------

    def assert_no_leak(self, result: ProbeResult, msg: str = "") -> None:
        """A leak is a test FAILURE — that failure is qualification evidence."""
        self.assertFalse(
            result.leaked,
            f"LEAK on {result.surface} as {result.actor}: markers "
            f"{result.leaked_markers} visible. {msg}",
        )
