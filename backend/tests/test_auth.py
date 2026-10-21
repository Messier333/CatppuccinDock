import os
import time
import unittest

os.environ["ADMIN_SETUP_CODE"] = "test-first-run-code"
os.environ.setdefault("AUTH_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/catppuccindock-tests.db")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.services.auth import COOKIE_NAME
from app.db.models import LoginSession
from app.core.security import hash_password, verify_password
from app.db.models import User as Owner
from app.db.session import Base, SessionLocal, engine
from app.main import app

HEADERS = {"X-CatppuccinDock": "1"}
CREDENTIALS = {"username": "test-owner", "password": "a-long-test-password"}


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        assert engine.dialect.name == "sqlite", "Tests require an isolated SQLite database"
        Base.metadata.drop_all(engine)
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def setup_owner(self):
        response = self.client.post("/api/auth/setup", json={**CREDENTIALS, "setup_code": "test-first-run-code"}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_portal_and_admin_require_server_session(self):
        self.assertEqual(self.client.get("/api/portal").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/me").status_code, 401)
        status = self.client.get("/api/auth/status")
        self.assertTrue(status.json()["setup_required"])
        self.assertFalse(status.json()["authenticated"])
        self.assertEqual(status.headers["cache-control"], "no-store")

    def test_setup_requires_one_time_code_and_only_allows_one_owner(self):
        response = self.client.post("/api/auth/setup", json={**CREDENTIALS, "setup_code": "wrong"}, headers=HEADERS)
        self.assertEqual(response.status_code, 403)
        self.setup_owner()
        response = self.client.post("/api/auth/setup", json={**CREDENTIALS, "setup_code": "test-first-run-code"}, headers=HEADERS)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.client.get("/api/auth/status").json()["setup_required"])
        self.assertEqual(self.client.get("/api/portal").status_code, 200)
        with SessionLocal() as db:
            self.assertNotIn(CREDENTIALS["password"], db.get(Owner, 1).password_hash)

    def test_setup_validates_password_and_username(self):
        for change in ({"password": "short"}, {"username": "  "}):
            response = self.client.post("/api/auth/setup", json={**CREDENTIALS, "setup_code": "test-first-run-code", **change}, headers=HEADERS)
            self.assertEqual(response.status_code, 422)

    def test_cookie_is_httponly_and_tokens_are_hashed(self):
        response = self.setup_owner()
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("path=/", cookie)
        token = self.client.cookies.get(COOKIE_NAME)
        with SessionLocal() as db:
            stored = db.scalar(select(LoginSession)).token_hash
        self.assertNotEqual(token, stored)
        self.assertEqual(len(stored), 64)

    def test_wrong_credentials_and_tampered_cookie_are_rejected(self):
        self.setup_owner()
        self.client.cookies.clear()
        for payload in ({**CREDENTIALS, "password": "wrong"}, {**CREDENTIALS, "username": "unknown"}):
            self.assertEqual(self.client.post("/api/auth/login", json=payload, headers=HEADERS).status_code, 401)
        self.client.cookies.set(COOKIE_NAME, "forged-session")
        self.assertEqual(self.client.get("/api/portal").status_code, 401)

    def test_logout_revokes_session_even_with_replayed_cookie(self):
        self.setup_owner()
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout", headers=HEADERS).status_code, 200)
        replay = TestClient(app)
        replay.cookies.set(COOKIE_NAME, token)
        self.assertEqual(replay.get("/api/portal").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json=CREDENTIALS, headers=HEADERS).status_code, 200)
        self.assertTrue(self.client.get("/api/auth/status").json()["authenticated"])

    def test_new_login_rotates_the_existing_cookie(self):
        self.setup_owner()
        previous = self.client.cookies.get(COOKIE_NAME)
        self.client.post("/api/auth/login", json=CREDENTIALS, headers=HEADERS)
        self.assertNotEqual(previous, self.client.cookies.get(COOKIE_NAME))
        other = TestClient(app)
        other.cookies.set(COOKIE_NAME, previous)
        self.assertEqual(other.get("/api/portal").status_code, 401)

    def test_expired_session_is_rejected(self):
        self.setup_owner()
        with SessionLocal.begin() as db:
            db.scalar(select(LoginSession)).expires_at = time.time() - 1
        self.assertEqual(self.client.get("/api/portal").status_code, 401)
        self.assertFalse(self.client.get("/api/auth/status").json()["authenticated"])

    def test_mutations_reject_requests_without_csrf_header(self):
        for path in ("setup", "login", "logout"):
            self.assertEqual(self.client.post(f"/api/auth/{path}", json=CREDENTIALS).status_code, 403)

    def test_repeated_attempts_are_throttled(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/auth/login", json=CREDENTIALS, headers=HEADERS).status_code, 401)
        response = self.client.post("/api/auth/login", json=CREDENTIALS, headers=HEADERS)
        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)

    def test_hashes_use_unique_salts(self):
        first = hash_password("password")
        second = hash_password("password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("password", first))
        self.assertFalse(verify_password("different", first))

    def test_cookie_secure_option(self):
        os.environ["COOKIE_SECURE"] = "true"
        try:
            self.assertIn("Secure", self.setup_owner().headers["set-cookie"])
        finally:
            os.environ.pop("COOKIE_SECURE")
