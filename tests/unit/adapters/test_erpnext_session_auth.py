"""Unit tests for ERPNext adapter HTTP transport (ADP-002).

RED first: verifies the adapter authenticates via session login
(POST /api/method/login → cookie) instead of the invalid
`Authorization: token administrator:<password>` header.

All tests are offline: HTTP layer is stubbed at urllib opener level.
"""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from http.cookiejar import CookieJar
from unittest.mock import patch

from src.adapters.erpnext import ErpNextAdapter, ErpNextConfig
from src.contracts.erp_port import DocumentRejected, UncertainOutcome


def _config() -> ErpNextConfig:
    return ErpNextConfig(
        base_url="http://127.0.0.1:18080",
        site_name="erpnext-pilot.localhost",
        admin_password="synthetic-password",
        timeout_seconds=5,
    )


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200, set_cookie: str | None = None):
        self._payload = json.dumps(payload).encode()
        self.status = status
        self.headers = {}
        if set_cookie is not None:
            self.headers["Set-Cookie"] = set_cookie

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    # cookiejar expects info()
    def info(self):
        import email.message
        m = email.message.Message()
        for k, v in self.headers.items():
            m[k] = v
        return m


class TestSessionAuthTransport(unittest.TestCase):
    """Adapter must login once and reuse session cookie for API calls."""

    def test_ping_performs_login_then_uses_session_cookie(self) -> None:
        """Adapter must POST /api/method/login once and reuse session cookie."""
        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))

        calls: list[dict] = []

        class _FakeOpener:
            """Stand-in for the adapter's opener; simulates cookie handling."""

            def __init__(self, real_adapter: ErpNextAdapter) -> None:
                self._adapter = real_adapter
                self._cookie: str | None = None

            def open(self, req, timeout=None):
                # Inject stored cookie like HTTPCookieProcessor would.
                if self._cookie and "/api/method/login" not in req.full_url:
                    req.add_header("Cookie", self._cookie)
                calls.append(
                    {
                        "url": req.full_url,
                        "authz": req.headers.get("Authorization"),
                        "cookie": req.headers.get("Cookie"),
                        "data": req.data,
                    }
                )
                if "/api/method/login" in req.full_url:
                    self._cookie = "sid=abc123"
                    return _FakeResponse(
                        {"message": "Logged In", "full_name": "Administrator"},
                        set_cookie="sid=abc123; HttpOnly; Path=/",
                    )
                if "/api/method/ping" in req.full_url:
                    return _FakeResponse({"message": "pong"})
                raise AssertionError(f"unexpected URL {req.full_url}")

        adapter._opener = _FakeOpener(adapter)  # type: ignore[assignment]
        result = adapter.ping()

        self.assertTrue(result, "ping should succeed with session auth")

        login_calls = [c for c in calls if "/api/method/login" in c["url"]]
        self.assertTrue(login_calls, "adapter must POST /api/method/login once")
        self.assertIsNone(
            login_calls[0]["authz"],
            "login call must not carry token Authorization header",
        )

        ping_calls = [c for c in calls if "/api/method/ping" in c["url"]]
        self.assertTrue(ping_calls, "adapter must call /api/method/ping after login")
        self.assertIn(
            "sid=abc123",
            ping_calls[0]["cookie"] or "",
            "ping must reuse session cookie from login",
        )
        self.assertIsNone(
            ping_calls[0]["authz"],
            "no token Authorization header may be sent after login",
        )

    def test_login_failure_raises_uncertain_outcome(self) -> None:
        """A 401/403 login response must surface as UncertainOutcome."""
        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))

        class _FailOpener:
            def open(self, req, timeout=None):
                import email.message
                raise urllib.error.HTTPError(
                    url=req.full_url,
                    code=401,
                    msg="Unauthorized",
                    hdrs=email.message.Message(),
                    fp=io.BytesIO(b'{"exc_type":"AuthenticationError"}'),
                )

        adapter._opener = _FailOpener()  # type: ignore[assignment]
        with self.assertRaises(UncertainOutcome):
            adapter.ping()

    def test_login_connection_failure_raises_uncertain_outcome(self) -> None:
        """Network failure on login must surface as UncertainOutcome."""
        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))

        class _ConnFailOpener:
            def open(self, req, timeout=None):
                raise urllib.error.URLError("connection refused")

        adapter._opener = _ConnFailOpener()  # type: ignore[assignment]
        with self.assertRaises(UncertainOutcome):
            adapter.ping()

    def test_password_never_in_request_url_or_body_logged(self) -> None:
        """The password must not leak into subsequent API request URLs/bodies."""
        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))
        calls: list[dict] = []

        class _RecOpener:
            def __init__(self) -> None:
                self._cookie: str | None = None

            def open(self, req, timeout=None):
                if self._cookie and "/api/method/login" not in req.full_url:
                    req.add_header("Cookie", self._cookie)
                body = req.data.decode() if isinstance(req.data, bytes) else ""
                calls.append({"url": req.full_url, "body": body})
                if "/api/method/login" in req.full_url:
                    self._cookie = "sid=xyz"
                    return _FakeResponse(
                        {"message": "Logged In"}, set_cookie="sid=xyz; Path=/"
                    )
                return _FakeResponse({"message": "pong"})

        adapter._opener = _RecOpener()  # type: ignore[assignment]
        adapter.ping()

        post_login = [c for c in calls if "/api/method/login" not in c["url"]]
        for c in post_login:
            self.assertNotIn("synthetic-password", c["url"])
            self.assertNotIn("synthetic-password", c["body"])


if __name__ == "__main__":
    unittest.main()
