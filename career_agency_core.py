"""Career Agency core API: auth, wallet, Paystack and cache-first AI billing.

This module is registered additively by the existing app.py. It deliberately uses
a separate SQLite database during the migration so legacy tables are not altered.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app, jsonify, redirect, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

ACTION_BASE_COSTS = {
    "chat": 5,
    "cv": 25,
    "mock_interview": 50,
    "workspace": 72,
}
# Only the CV cache-hit discount was specified. Other discounts remain disabled.
ACTION_CACHE_COSTS = {"cv": 10}
CONFIRMED_PACKAGE_ENDPOINTS = [
    {"price_kobo": 50_000, "credits": 100, "active": 0},
    {"price_kobo": 20_000_000, "credits": 120_000, "active": 0},
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> str:
    return os.environ.get("CAREER_AGENCY_CORE_DB", "career_agency_core.db")


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=20, isolation_level=None, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _init_db() -> None:
    with _connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('job_seeker','employer','recruiter','admin')),
            account_status TEXT NOT NULL DEFAULT 'active',
            email_verified_at TEXT,
            session_version INTEGER NOT NULL DEFAULT 1,
            onboarding_completed_at TEXT,
            credits INTEGER NOT NULL DEFAULT 0 CHECK(credits >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobile_refresh_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            family_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            revoked_at TEXT,
            replaced_by_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_refresh_family
            ON mobile_refresh_tokens(family_id,user_id);
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            purpose TEXT NOT NULL CHECK(purpose IN ('email_verification','password_reset')),
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_purpose
            ON auth_tokens(user_id,purpose,created_at DESC);
        CREATE TABLE IF NOT EXISTS auth_rate_limits (
            bucket_key TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            window_started_at INTEGER NOT NULL,
            blocked_until INTEGER
        );
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            phone TEXT,
            country TEXT,
            city TEXT,
            headline TEXT,
            professional_summary TEXT,
            years_experience INTEGER NOT NULL DEFAULT 0,
            avatar_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS career_preferences (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            desired_roles_json TEXT NOT NULL DEFAULT '[]',
            work_modes_json TEXT NOT NULL DEFAULT '[]',
            employment_types_json TEXT NOT NULL DEFAULT '[]',
            preferred_locations_json TEXT NOT NULL DEFAULT '[]',
            salary_min_ngn INTEGER,
            salary_max_ngn INTEGER,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            website TEXT,
            country TEXT,
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS employer_profiles (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            organization_id TEXT REFERENCES organizations(id),
            job_title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recruiter_profiles (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            agency_name TEXT NOT NULL,
            client_focus TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS onboarding_progress (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            step_key TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            PRIMARY KEY(user_id,step_key)
        );
        CREATE TABLE IF NOT EXISTS credit_packages (
            id TEXT PRIMARY KEY,
            price_kobo INTEGER NOT NULL UNIQUE CHECK(price_kobo > 0),
            credits INTEGER NOT NULL CHECK(credits > 0),
            bonus_credits INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 0,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS credit_action_prices (
            action_key TEXT PRIMARY KEY,
            base_cost INTEGER NOT NULL CHECK(base_cost >= 0),
            cache_hit_cost INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS credit_ledger (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
            entry_type TEXT NOT NULL,
            reference_type TEXT,
            reference_id TEXT,
            idempotency_key TEXT UNIQUE,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_user_created
            ON credit_ledger(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            package_id TEXT NOT NULL REFERENCES credit_packages(id),
            provider TEXT NOT NULL DEFAULT 'paystack',
            reference TEXT NOT NULL UNIQUE,
            amount_kobo INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'NGN',
            status TEXT NOT NULL DEFAULT 'initialized',
            provider_transaction_id TEXT UNIQUE,
            verified_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS webhook_events (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            event_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            signature_valid INTEGER NOT NULL,
            processing_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            processed_at TEXT,
            UNIQUE(provider, event_key)
        );
        CREATE TABLE IF NOT EXISTS llm_cache (
            cache_key TEXT PRIMARY KEY,
            action_key TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            hit_count INTEGER NOT NULL DEFAULT 0,
            last_hit_at TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_requests (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            action_key TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            cache_hit INTEGER NOT NULL,
            credits_charged INTEGER NOT NULL,
            status TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            error_code TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            user_id TEXT NOT NULL REFERENCES users(id),
            idem_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, idem_key)
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            actor_id TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            outcome TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "onboarding_completed_at" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN onboarding_completed_at TEXT")
        if "session_version" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1")
        for package in CONFIRMED_PACKAGE_ENDPOINTS:
            db.execute(
                """INSERT OR IGNORE INTO credit_packages
                   (id,price_kobo,credits,bonus_credits,active,display_order,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), package["price_kobo"], package["credits"],
                 0, package["active"], package["price_kobo"], utc_now()),
            )
        for action, cost in ACTION_BASE_COSTS.items():
            db.execute(
                """INSERT OR IGNORE INTO credit_action_prices
                   (action_key,base_cost,cache_hit_cost,active,updated_at)
                   VALUES(?,?,?,?,?)""",
                (action, cost, ACTION_CACHE_COSTS.get(action), 1, utc_now()),
            )


def _json_error(code: str, message: str, status: int, **details):
    payload = {"error": {"code": code, "message": message, **details},
               "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4()))}
    return jsonify(payload), status


def _current_user(db=None):
    user_id = session.get("core_user_id")
    expected_version = session.get("core_session_version")
    bearer = False
    if not user_id:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            try:
                payload = URLSafeTimedSerializer(current_app.secret_key, salt="career-agency-mobile-access").loads(
                    authorization[7:].strip(), max_age=900
                )
                user_id = payload.get("sub")
                expected_version = payload.get("sv")
                bearer = True
            except (BadSignature, SignatureExpired, TypeError, ValueError):
                return None
    if not user_id:
        return None
    own = db or _connect()
    try:
        row = own.execute(
            "SELECT id,email,full_name,role,account_status,credits,session_version,onboarding_completed_at FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if row is None or expected_version is None or int(row["session_version"]) != int(expected_version):
            if not bearer:
                session.clear()
            return None
        return row
    finally:
        if db is None:
            own.close()


def _require_user(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if not user:
            return _json_error("UNAUTHENTICATED", "Please sign in to continue.", 401)
        if user["account_status"] != "active":
            return _json_error("ACCOUNT_UNAVAILABLE", "This account cannot access the service.", 403)
        return fn(*args, **kwargs)
    return wrapped


def _audit(actor_id, action, resource_type, resource_id, outcome, metadata=None):
    with _connect() as db:
        db.execute(
            """INSERT INTO audit_events
               (id,actor_id,action,resource_type,resource_id,outcome,metadata_json,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), actor_id, action, resource_type, resource_id,
             outcome, json.dumps(metadata or {}, separators=(",", ":")), utc_now()),
        )


def _debit(user_id: str, amount: int, action: str, reference_id: str,
           idem_key: str) -> int | None:
    """Atomic debit. Returns new balance, or None when funds are insufficient."""
    if amount < 0:
        raise ValueError("Credit debit cannot be negative")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT balance_after FROM credit_ledger WHERE idempotency_key=?",
            (idem_key,),
        ).fetchone()
        if prior:
            db.commit()
            return int(prior["balance_after"])
        user = db.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            db.rollback()
            raise LookupError("User not found")
        balance = int(user["credits"])
        if balance < amount:
            db.rollback()
            return None
        new_balance = balance - amount
        db.execute("UPDATE users SET credits=?,updated_at=? WHERE id=?",
                   (new_balance, utc_now(), user_id))
        db.execute(
            """INSERT INTO credit_ledger
               (id,user_id,delta,balance_after,entry_type,reference_type,reference_id,
                idempotency_key,description,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), user_id, -amount, new_balance, "usage",
             "ai_request", reference_id, idem_key, f"{action} AI action", utc_now()),
        )
        db.commit()
        return new_balance


def _refund(user_id: str, amount: int, reference_id: str, reason: str) -> None:
    if amount <= 0:
        return
    idem = f"refund:{reference_id}"
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM credit_ledger WHERE idempotency_key=?", (idem,)).fetchone():
            db.commit()
            return
        row = db.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            db.rollback()
            return
        balance = int(row["credits"]) + amount
        db.execute("UPDATE users SET credits=?,updated_at=? WHERE id=?",
                   (balance, utc_now(), user_id))
        db.execute(
            """INSERT INTO credit_ledger
               (id,user_id,delta,balance_after,entry_type,reference_type,reference_id,
                idempotency_key,description,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), user_id, amount, balance, "refund",
             "ai_request", reference_id, idem, reason, utc_now()),
        )
        db.commit()


def _cache_key(action: str, user_id: str, payload: dict, model: str, prompt_version: str) -> str:
    canonical = {
        "action": action, "scope": user_id, "payload": payload,
        "model": model, "prompt_version": prompt_version,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _llm_generate(action: str, payload: dict, model: str):
    endpoint = os.environ.get("CAREER_AGENCY_LLM_ENDPOINT", "")
    api_key = os.environ.get("CAREER_AGENCY_LLM_API_KEY", "")
    if not endpoint:
        raise RuntimeError("AI provider adapter is not configured")
    body = json.dumps({"action": action, "model": model, "input": payload}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = Request(endpoint, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("AI provider returned an invalid response")
    return result

def _paystack_request(path: str, payload=None):
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not configured")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        "https://api.paystack.co" + path,
        data=body,
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("Paystack request failed") from exc


def _rate_limit(bucket_key: str, limit: int, window_seconds: int) -> bool:
    now = int(time.time())
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT attempts,window_started_at,blocked_until FROM auth_rate_limits WHERE bucket_key=?",
                         (bucket_key,)).fetchone()
        if row and row["blocked_until"] and int(row["blocked_until"]) > now:
            db.rollback()
            return False
        if not row or now - int(row["window_started_at"]) >= window_seconds:
            db.execute("INSERT OR REPLACE INTO auth_rate_limits(bucket_key,attempts,window_started_at,blocked_until) VALUES(?,?,?,NULL)",
                       (bucket_key, 1, now))
            db.commit()
            return True
        attempts = int(row["attempts"]) + 1
        blocked = now + window_seconds if attempts > limit else None
        db.execute("UPDATE auth_rate_limits SET attempts=?,blocked_until=? WHERE bucket_key=?",
                   (attempts, blocked, bucket_key))
        db.commit()
        return blocked is None


def _issue_auth_token(user_id: str, purpose: str, ttl_seconds: int) -> str:
    raw = secrets.token_urlsafe(40)
    expires = datetime.fromtimestamp(time.time() + ttl_seconds, timezone.utc).isoformat()
    with _connect() as db:
        db.execute("UPDATE auth_tokens SET consumed_at=? WHERE user_id=? AND purpose=? AND consumed_at IS NULL",
                   (utc_now(), user_id, purpose))
        db.execute("INSERT INTO auth_tokens(id,user_id,token_hash,purpose,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                   (str(uuid.uuid4()), user_id, hashlib.sha256(raw.encode()).hexdigest(), purpose, expires, utc_now()))
    return raw


def _send_auth_email(email: str, subject: str, text_body: str) -> None:
    endpoint = os.environ.get("CAREER_AGENCY_AUTH_EMAIL_ENDPOINT", "")
    api_key = os.environ.get("CAREER_AGENCY_AUTH_EMAIL_API_KEY", "")
    if not endpoint:
        raise RuntimeError("Authentication email provider is not configured")
    payload = json.dumps({"to": email, "subject": subject, "text": text_body}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = Request(endpoint, data=payload, headers=headers, method="POST")
    with urlopen(req, timeout=20) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError("Authentication email delivery failed")


def _auth_email_link(path: str, token: str) -> str:
    base = os.environ.get("CAREER_AGENCY_PUBLIC_URL", "http://127.0.0.1:5000").rstrip("/")
    return base + path + "?token=" + token

def _auth_page(title: str, subtitle: str, content: str, script: str = "") -> str:
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_subtitle = subtitle.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#080d19"><title>""" + safe_title + """ · Career Agency</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{color-scheme:dark;--bg:#080d19;--panel:#101a2d;--line:#263650;--text:#f4f7fc;--muted:#9aabc3;--accent:#78a9ff;--accent2:#3979e8}
*{box-sizing:border-box}body{margin:0;min-height:100svh;background:radial-gradient(ellipse at 50% -15%,#1c3157 0,transparent 48%),linear-gradient(145deg,#0a1222,#050811 70%);color:var(--text);font-family:"DM Sans",system-ui,sans-serif;display:grid;place-items:center;padding:24px}
.panel{width:min(100%,470px);padding:clamp(24px,5vw,40px);border:1px solid var(--line);border-radius:24px;background:linear-gradient(160deg,#121f35f5,#0d1729f7);box-shadow:0 30px 90px #0009}
.brand-row{display:flex;align-items:center;gap:13px;margin-bottom:30px}.brand-mark{width:48px;height:48px;flex:none}.brand-name{font:800 13px Manrope,sans-serif;letter-spacing:.16em;color:#dce9ff}.brand-caption{font-size:11px;letter-spacing:.08em;color:#7186a6;margin-top:3px}
h1{font:800 clamp(25px,5vw,31px) Manrope,sans-serif;letter-spacing:-.04em;margin:0 0 9px}.subtitle{color:var(--muted);line-height:1.65;margin:0 0 26px;font-size:14px}
label{display:block;font-size:13px;font-weight:600;color:#d1dced;margin:17px 0 8px}
input,select{width:100%;min-height:49px;padding:13px 14px;border-radius:12px;border:1px solid #344560;background:#091222;color:#f7faff;font:500 15px "DM Sans",sans-serif;outline:none}
input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px #78a9ff24}
button{width:100%;min-height:50px;margin-top:22px;border:0;border-radius:12px;background:linear-gradient(110deg,#4b8cf2,#2865d4);color:white;font-weight:800;font-size:15px;cursor:pointer}
button:disabled{opacity:.55;cursor:wait}.links{display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-top:21px;font-size:13px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.error{min-height:20px;color:#ffaaa8;font-size:13px;line-height:1.5;margin-top:12px}
.consent{display:flex;align-items:flex-start;gap:10px;font-weight:400;line-height:1.5}.consent input{width:17px;min-height:17px;margin:2px 0 0;flex:none}
.footer{color:#647793;text-align:center;font-size:11px;margin-top:25px}.footer a{color:#93baff}
@media(max-width:480px){body{padding:14px;place-items:center}.panel{border-radius:19px;padding:25px 21px}.brand-row{margin-bottom:25px}}
</style></head><body><main class="panel">
<div class="brand-row"><svg class="brand-mark" viewBox="0 0 48 48" role="img" aria-label="Career Agency logo"><defs><linearGradient id="ca" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#9bc4ff"/><stop offset="1" stop-color="#3675e6"/></linearGradient></defs><rect x="1" y="1" width="46" height="46" rx="14" fill="#142b4d" stroke="#496b9c"/><path d="M30.5 15.5a13 13 0 1 0 0 17" fill="none" stroke="url(#ca)" stroke-width="5" stroke-linecap="round"/><path d="M25 24h13m-6.5-6.5L38 24l-6.5 6.5" fill="none" stroke="#eaf3ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>
<div><div class="brand-name">CAREER AGENCY</div><div class="brand-caption">CAREER GROWTH, WITH DIRECTION</div></div></div>
<h1>""" + safe_title + """</h1><p class="subtitle">""" + safe_subtitle + """</p>""" + content + """
<div class="footer">Secure account access · <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a></div>
</main><script>""" + script + """</script></body></html>"""


def register_core_api(app):
    """Register core routes and auth-first guard on the existing Flask app."""
    app.secret_key = os.environ.get("CAREER_AGENCY_SECRET_KEY", app.secret_key or secrets.token_hex(32))
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", os.environ.get("CAREER_AGENCY_COOKIE_SECURE", "0") == "1")
    _init_db()

    @app.after_request
    def career_agency_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.path.startswith("/auth/") or request.path in {"/register", "/verify-email", "/forgot-password", "/reset-password"} or request.path.startswith("/api/v1/auth/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.before_request
    def career_agency_auth_first():
        # Legacy routes are isolated until their ownership checks are migrated.
        if request.endpoint == "static" or request.path.startswith("/static/"):
            return None
        if request.path == "/login":
            return redirect("/auth/login")
        if request.path == "/":
            return redirect("/workspace" if session.get("core_user_id") else "/auth/login")
        if request.path == "/workspace":
            if not session.get("core_user_id"):
                return redirect("/auth/login")
            return None
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path != "/api/v1/payments/paystack/webhook":
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return _json_error("CSRF_VALIDATION_FAILED", "Refresh the page and try again.", 403)
        allowed = (
            request.path in {"/auth/login", "/auth/logout", "/register", "/forgot-password",
                             "/reset-password", "/verify-email", "/terms", "/privacy",
                             "/onboarding", "/api/v1/wallet", "/api/v1/wallet/ledger", "/api/v1/credit-packages"}
            or request.path.startswith("/api/v1/auth/")
            or request.path.startswith("/api/v1/onboarding/")
            or request.path.startswith("/api/v1/ai/actions/")
            or request.path.startswith("/api/v1/payments/")
            or request.path.startswith("/api/v1/admin/credit-packages/")
            or request.path.startswith("/health")
        )
        if allowed:
            return None
        if not session.get("core_user_id"):
            if request.path.startswith("/api/"):
                return _json_error("UNAUTHENTICATED", "Please sign in to continue.", 401)
            return redirect("/auth/login?next=" + request.path)
        # Do not expose the legacy shared-data workspace to new accounts until
        # its user ownership migration is complete and explicitly enabled.
        if os.environ.get("CAREER_AGENCY_ENABLE_LEGACY_ROUTES") != "1":
            if request.path.startswith("/api/"):
                return _json_error("LEGACY_API_DISABLED", "This legacy endpoint is not enabled during migration.", 410)
            if request.path != "/auth/workspace-unavailable":
                return redirect("/auth/workspace-unavailable")
        return None


    @app.get("/auth/workspace-unavailable")
    def core_workspace_unavailable():
        return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Workspace update · Career Agency</title><body style="margin:0;background:#080f1e;color:#eef4ff;font-family:system-ui;display:grid;min-height:100vh;place-items:center;padding:24px">
        <main style="max-width:560px;background:#111d33;border:1px solid #2b3c5d;border-radius:20px;padding:32px">
        <h1>Workspace migration in progress</h1><p style="color:#aab9d1;line-height:1.6">Your sign-in is active. The legacy workspace is temporarily isolated while its user-owned data and permissions are migrated safely. The new core APIs are available, but the full web and mobile workspaces are not yet complete.</p>
        <a style="color:#93c5fd" href="/auth/logout">Sign out</a></main></body></html>"""

    @app.get("/health/core")
    def core_health():
        return jsonify({"status": "ok", "service": "career-agency-core"})

    @app.get("/auth/login")
    def core_login_screen():
        content = """
        <form id="login"><label for="email">Email address</label><input id="email" type="email" autocomplete="username" required>
        <label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required>
        <button id="submit" type="submit">Sign in</button><div class="error" id="error" role="alert"></div></form>
        <div class="links"><a href="/forgot-password">Forgot password?</a><a href="/register">Create account</a></div>"""
        script = """
        const form=document.getElementById("login"),btn=document.getElementById("submit"),err=document.getElementById("error");
        form.addEventListener("submit",async ev=>{ev.preventDefault();btn.disabled=true;btn.textContent="Signing in…";err.textContent="";
        try{const t=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/auth/login",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":t.data.csrf_token},body:JSON.stringify({email:document.getElementById("email").value,password:document.getElementById("password").value})});
        const d=await r.json();if(!r.ok)throw new Error(d.error?.message||"Unable to sign in.");location.href="/";
        }catch(x){err.textContent=x.message;}finally{btn.disabled=false;btn.textContent="Sign in";}});
        """
        return _auth_page("Welcome back.", "Your next opportunity starts with one focused step. Sign in to continue.", content, script)

    @app.get("/onboarding")
    @_require_user
    def core_onboarding_screen():
        user = _current_user()
        if user["onboarding_completed_at"]:
            return redirect("/workspace")
        role = user["role"]
        role_field = ""
        if role == "employer":
            role_field = '<label>Organisation name</label><input name="organization_name" maxlength="160" required>'
            role_field += '<label>Organisation website</label><input name="website" type="url" placeholder="https://example.com">'
            role_field += '<label>Your job title</label><input name="job_title" maxlength="120">'
        elif role == "recruiter":
            role_field = '<label>Recruitment agency name</label><input name="agency_name" maxlength="160" required>'
            role_field += '<label>Recruitment focus</label><input name="client_focus" maxlength="240" placeholder="e.g. Technology, Finance">'
        else:
            role_field = '<label>Professional headline</label><input name="headline" maxlength="160" placeholder="e.g. Graduate software developer">'
            role_field += '<label>Years of experience</label><input name="years_experience" type="number" min="0" max="60" value="0">'
            role_field += '<label>Career interests</label><input name="desired_roles" placeholder="Separate roles with commas">'
            role_field += '<label>Preferred work arrangement</label><select name="work_modes"><option value="Remote">Remote</option><option value="Hybrid">Hybrid</option><option value="On-site">On-site</option><option value="Remote,Hybrid">Remote or hybrid</option><option value="Remote,Hybrid,On-site">Any arrangement</option></select>'
        content = """
        <form id="onboarding-form">
        <label>Country</label><input name="country" value="Nigeria" autocomplete="country-name" required>
        <label>City or state</label><input name="city" autocomplete="address-level1" maxlength="100" placeholder="e.g. Port Harcourt">
        <label>Phone number (optional)</label><input name="phone" type="tel" autocomplete="tel" maxlength="30">
        """ + role_field + """
        <button id="submit" type="submit">Save and continue</button>
        <div id="error" class="error" role="alert"></div></form>"""
        script = """
        const f=document.getElementById("onboarding-form"),b=document.getElementById("submit"),e=document.getElementById("error");
        f.addEventListener("submit",async ev=>{ev.preventDefault();const d=Object.fromEntries(new FormData(f));b.disabled=true;b.textContent="Saving your profile…";e.textContent="";
        const csv=v=>(v||"").split(",").map(x=>x.trim()).filter(Boolean);
        const profile={country:d.country,city:d.city,phone:d.phone,headline:d.headline||"",years_experience:Number(d.years_experience||0),organization_name:d.organization_name||"",website:d.website||"",job_title:d.job_title||"",agency_name:d.agency_name||"",client_focus:d.client_focus||""};
        const prefs={desired_roles:csv(d.desired_roles),work_modes:csv(d.work_modes),employment_types:[],preferred_locations:[]};
        try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json()),h={"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token};
        let r=await fetch("/api/v1/onboarding/profile",{method:"PUT",headers:h,body:JSON.stringify(profile)});let x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not save profile.");
        r=await fetch("/api/v1/onboarding/preferences",{method:"PUT",headers:h,body:JSON.stringify(prefs)});x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not save preferences.");
        r=await fetch("/api/v1/onboarding/complete",{method:"POST",headers:h,body:"{}"});x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Please complete the required details.");
        location.href="/workspace";
        }catch(x){e.textContent=x.message;}finally{b.disabled=false;b.textContent="Save and continue";}});
        """
        return _auth_page("Let's set up your workspace", "A few details help Career Agency prepare the right tools for your account.", content, script)

    @app.get("/api/v1/onboarding")
    @_require_user
    def core_onboarding_status():
        user = _current_user()
        with _connect() as db:
            profile = db.execute("SELECT * FROM user_profiles WHERE user_id=?", (user["id"],)).fetchone()
            preferences = db.execute("SELECT * FROM career_preferences WHERE user_id=?", (user["id"],)).fetchone()
        return jsonify({"data": {"role": user["role"], "completed": bool(user["onboarding_completed_at"]),
                                 "profile": dict(profile) if profile else None,
                                 "preferences": dict(preferences) if preferences else None},
                        "request_id": str(uuid.uuid4())})

    @app.put("/api/v1/onboarding/profile")
    @_require_user
    def core_onboarding_profile():
        user = _current_user()
        data = request.get_json(silent=True) or {}
        country = str(data.get("country", "")).strip()
        if not country or len(country) > 100:
            return _json_error("VALIDATION_ERROR", "Country is required.", 400)
        phone = str(data.get("phone", "")).strip()[:30] or None
        city = str(data.get("city", "")).strip()[:100] or None
        headline = str(data.get("headline", "")).strip()[:160] or None
        summary = str(data.get("professional_summary", "")).strip()[:3000] or None
        try:
            years = int(data.get("years_experience", 0) or 0)
        except (TypeError, ValueError):
            return _json_error("VALIDATION_ERROR", "Years of experience must be a whole number.", 400)
        if years < 0 or years > 60:
            return _json_error("VALIDATION_ERROR", "Years of experience must be between 0 and 60.", 400)
        org_name = str(data.get("organization_name", "")).strip()
        agency = str(data.get("agency_name", "")).strip()
        if user["role"] == "employer" and (not org_name or len(org_name) > 160):
            return _json_error("VALIDATION_ERROR", "Organisation name is required.", 400)
        if user["role"] == "recruiter" and (not agency or len(agency) > 160):
            return _json_error("VALIDATION_ERROR", "Recruitment agency name is required.", 400)
        now = utc_now()
        with _connect() as db:
            db.execute("""INSERT INTO user_profiles(user_id,phone,country,city,headline,professional_summary,years_experience,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone,country=excluded.country,
                          city=excluded.city,headline=excluded.headline,professional_summary=excluded.professional_summary,
                          years_experience=excluded.years_experience,updated_at=excluded.updated_at""",
                       (user["id"], phone, country, city, headline, summary, years, now, now))
            if user["role"] == "employer":
                existing = db.execute("SELECT organization_id FROM employer_profiles WHERE user_id=?", (user["id"],)).fetchone()
                if existing and existing["organization_id"]:
                    org_id = existing["organization_id"]
                    db.execute("UPDATE organizations SET name=?,website=?,country=?,updated_at=? WHERE id=? AND owner_user_id=?",
                               (org_name, str(data.get("website", "")).strip()[:240] or None, country, now, org_id, user["id"]))
                    db.execute("UPDATE employer_profiles SET job_title=?,updated_at=? WHERE user_id=?",
                               (str(data.get("job_title", "")).strip()[:120] or None, now, user["id"]))
                else:
                    org_id = str(uuid.uuid4())
                    db.execute("INSERT INTO organizations(id,owner_user_id,name,website,country,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                               (org_id, user["id"], org_name, str(data.get("website", "")).strip()[:240] or None, country, now, now))
                    db.execute("INSERT INTO employer_profiles(user_id,organization_id,job_title,created_at,updated_at) VALUES(?,?,?,?,?)",
                               (user["id"], org_id, str(data.get("job_title", "")).strip()[:120] or None, now, now))
            elif user["role"] == "recruiter":
                db.execute("INSERT INTO recruiter_profiles(user_id,agency_name,client_focus,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET agency_name=excluded.agency_name,client_focus=excluded.client_focus,updated_at=excluded.updated_at",
                           (user["id"], agency, str(data.get("client_focus", "")).strip()[:240] or None, now, now))
        return jsonify({"data": {"saved": True}, "request_id": str(uuid.uuid4())})

    @app.put("/api/v1/onboarding/preferences")
    @_require_user
    def core_onboarding_preferences():
        user = _current_user()
        data = request.get_json(silent=True) or {}
        def clean_list(key, max_items=20):
            value = data.get(key, [])
            if not isinstance(value, list) or len(value) > max_items:
                raise ValueError(key)
            result = []
            for item in value:
                if not isinstance(item, str) or len(item.strip()) > 120:
                    raise ValueError(key)
                clean = item.strip()
                if clean:
                    result.append(clean)
            return list(dict.fromkeys(result))
        try:
            desired = clean_list("desired_roles")
            modes = clean_list("work_modes", 5)
            employment = clean_list("employment_types", 10)
            locations = clean_list("preferred_locations")
        except ValueError:
            return _json_error("VALIDATION_ERROR", "One or more preference lists are invalid.", 400)
        now = utc_now()
        with _connect() as db:
            db.execute("""INSERT INTO career_preferences(user_id,desired_roles_json,work_modes_json,employment_types_json,preferred_locations_json,updated_at)
                          VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET desired_roles_json=excluded.desired_roles_json,
                          work_modes_json=excluded.work_modes_json,employment_types_json=excluded.employment_types_json,
                          preferred_locations_json=excluded.preferred_locations_json,updated_at=excluded.updated_at""",
                       (user["id"], json.dumps(desired), json.dumps(modes), json.dumps(employment), json.dumps(locations), now))
        return jsonify({"data": {"saved": True}, "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/onboarding/complete")
    @_require_user
    def core_onboarding_complete():
        user = _current_user()
        with _connect() as db:
            profile = db.execute("SELECT country FROM user_profiles WHERE user_id=?", (user["id"],)).fetchone()
            if not profile or not profile["country"]:
                return _json_error("ONBOARDING_INCOMPLETE", "Add your country before continuing.", 400)
            if user["role"] == "employer" and not db.execute("SELECT 1 FROM employer_profiles WHERE user_id=?", (user["id"],)).fetchone():
                return _json_error("ONBOARDING_INCOMPLETE", "Add your organisation details before continuing.", 400)
            if user["role"] == "recruiter" and not db.execute("SELECT 1 FROM recruiter_profiles WHERE user_id=?", (user["id"],)).fetchone():
                return _json_error("ONBOARDING_INCOMPLETE", "Add your agency details before continuing.", 400)
            now = utc_now()
            db.execute("UPDATE users SET onboarding_completed_at=?,updated_at=? WHERE id=?", (now, now, user["id"]))
            db.execute("INSERT OR REPLACE INTO onboarding_progress(user_id,step_key,completed_at) VALUES(?,?,?)",
                       (user["id"], "profile_setup", now))
        return jsonify({"data": {"completed": True, "next": "/workspace"}, "request_id": str(uuid.uuid4())})

    @app.get("/workspace")
    @_require_user
    def core_workspace_home():
        user = _current_user()
        if not user["onboarding_completed_at"]:
            return redirect("/onboarding")
        role_names = {"job_seeker": "Job Seeker", "employer": "Employer", "recruiter": "Recruiter", "admin": "Administrator"}
        role = role_names.get(user["role"], "Career Agency")
        safe_name = user["full_name"]
        content = """
        <div style="padding:18px;border:1px solid #293d5b;border-radius:15px;background:#0a1425;margin:22px 0">
        <div style="color:#83b5ff;font-size:11px;letter-spacing:.12em;font-weight:800">ACCOUNT READY</div>
        <p style="color:#dce8f8;line-height:1.7;margin:10px 0 0">Your account is verified and your sign-in is secure. The role-specific workspace is being connected to the new data services.</p>
        </div>
        <p style="color:#9aabc3;font-size:13px">Account type: """ + role + """</p>
        <p style="color:#9aabc3;font-size:13px">Wallet balance: """ + str(user["credits"]) + """ credits</p>
        <form id="logout-form"><button type="submit">Sign out</button></form>
        <div id="message" class="error" role="status"></div>"""
        script = """
        document.getElementById("logout-form").addEventListener("submit",async ev=>{ev.preventDefault();const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());await fetch("/api/v1/auth/logout",{method:"POST",headers:{"X-CSRF-Token":c.data.csrf_token}});location.href="/auth/login";});
        """
        return _auth_page("Welcome, " + safe_name, "Your " + role + " account is ready.", content, script)

    @app.get("/terms")
    def core_terms_draft():
        content = """
        <p><strong>Draft for review — not approved legal terms.</strong></p>
        <p>Career Agency provides career-management tools, job discovery, application organisation, document assistance and AI-supported features. Features may change as the service develops.</p>
        <h3>Account responsibilities</h3><p>Keep account details accurate, protect your sign-in credentials and use only accounts you are authorised to access. Do not upload another person's private information without a lawful basis and permission.</p>
        <h3>AI-assisted content</h3><p>AI outputs can be incomplete or inaccurate. Review generated CVs, applications, messages and recommendations before using them. Career Agency does not guarantee employment, interviews or ATS outcomes.</p>
        <h3>Career Credits</h3><p>Credits are prepaid service units, not cash, deposits or withdrawable funds. Prices and action costs must be shown before purchase or use. Purchased credits are intended not to expire, subject to final approved policy. Refunds, chargebacks and payment disputes are handled under the final published policy and applicable law.</p>
        <h3>Acceptable use and availability</h3><p>Do not abuse, disrupt, reverse engineer or attempt unauthorised access to the service. Availability may be affected by maintenance or third-party providers.</p>
        <h3>Contact and changes</h3><p>The final terms must state the operator's legal identity, contact address, governing law, dispute process, limitation provisions and effective date before public launch.</p>
        <div class="error">This page is a working draft and must receive Nigerian legal review before production use.</div>
        <div class="links"><a href="/register">Back to account creation</a><a href="/privacy">Privacy draft</a></div>"""
        return _auth_page("Terms of Service — Draft", "A plain-language outline of the rules for using Career Agency.", content)

    @app.get("/privacy")
    def core_privacy_draft():
        content = """
        <p><strong>Draft for review — not an approved privacy notice.</strong></p>
        <h3>Information the service may process</h3><p>Account identity and contact details; CVs and career documents; job preferences and application records; employer and recruiter workspace information; support messages; device, security and usage events; wallet and payment references.</p>
        <h3>Why information is used</h3><p>To create and secure accounts, provide career features, process credit purchases, respond to support requests, prevent abuse, maintain service reliability and improve product quality.</p>
        <h3>AI and third-party services</h3><p>When a user chooses an AI feature, relevant input may be sent to the configured AI provider to produce the requested result. Payment processing is handled by Paystack. Final provider names, data locations, retention terms and transfer safeguards must be disclosed before launch.</p>
        <h3>Security and retention</h3><p>Career Agency uses access controls and security measures appropriate to the system. The final policy must specify retention periods, deletion workflows, backups, subprocessors and incident notification procedures. Payment card details should remain with the payment provider and must not be stored in the Career Agency database.</p>
        <h3>Your privacy choices</h3><p>The final notice must explain how users can access, correct, export or request deletion of personal information, withdraw consent where applicable and contact the privacy team.</p>
        <div class="error">This draft requires review against the Nigeria Data Protection Act and applicable guidance before public launch.</div>
        <div class="links"><a href="/register">Back to account creation</a><a href="/terms">Terms draft</a></div>"""
        return _auth_page("Privacy Notice — Draft", "How account and career information is expected to be handled.", content)

    @app.get("/register")
    def core_register_screen():
        content = """
        <form id="auth-form">
        <label>Full name</label><input name="full_name" autocomplete="name" maxlength="120" required>
        <label>Email address</label><input name="email" type="email" autocomplete="email" required>
        <label>Password</label><input name="password" type="password" minlength="10" autocomplete="new-password" required>
        <label>Confirm password</label><input name="confirm_password" type="password" minlength="10" autocomplete="new-password" required>
        <label>Account type</label><select name="role"><option value="job_seeker">Job seeker</option><option value="employer">Employer</option><option value="recruiter">Recruiter</option></select>
        <label class="consent"><input type="checkbox" name="terms_accepted" required><span>I agree to the <a href="/terms">Terms of Service</a> and <a href="/privacy">Privacy Policy</a>.</span></label>
        <button id="submit" type="submit">Create account</button><div id="error" role="alert" class="error"></div></form>
        <div class="links"><a href="/auth/login">Already have an account? Sign in</a></div>"""
        script = """
        const f=document.getElementById("auth-form"),b=document.getElementById("submit"),e=document.getElementById("error");
        f.addEventListener("submit",async ev=>{ev.preventDefault();const d=Object.fromEntries(new FormData(f));
        if(d.password!==d.confirm_password){e.textContent="Your passwords do not match.";return;}
        d.terms_accepted=f.elements.terms_accepted.checked;b.disabled=true;b.textContent="Creating account…";e.textContent="";
        try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/auth/register",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify(d)});
        const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Unable to create account.");location.href="/verify-email?email="+encodeURIComponent(d.email);
        }catch(x){e.textContent=x.message;}finally{b.disabled=false;b.textContent="Create account";}});
        """
        return _auth_page("Create your account", "Build your next career move with clarity.", content, script)

    @app.get("/forgot-password")
    def core_forgot_screen():
        content = """
        <form id="auth-form"><label>Email address</label><input name="email" type="email" autocomplete="email" required>
        <button id="submit" type="submit">Send reset link</button><div id="message" role="status" class="error"></div></form>
        <div class="links"><a href="/auth/login">Back to sign in</a></div>"""
        script = """
        const f=document.getElementById("auth-form"),b=document.getElementById("submit"),m=document.getElementById("message");
        f.addEventListener("submit",async ev=>{ev.preventDefault();b.disabled=true;b.textContent="Sending…";m.textContent="";
        try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/auth/forgot-password",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify({email:f.elements.email.value})});
        const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Please try again.");m.textContent=x.data.message;
        }catch(x){m.textContent=x.message;}finally{b.disabled=false;b.textContent="Send reset link";}});
        """
        return _auth_page("Forgot your password?", "We will send a secure reset link if the account exists.", content, script)

    @app.get("/reset-password")
    def core_reset_screen():
        content = """
        <form id="auth-form"><input type="hidden" name="token" id="token">
        <label>New password</label><input name="password" type="password" minlength="10" autocomplete="new-password" required>
        <label>Confirm new password</label><input name="confirm_password" type="password" minlength="10" autocomplete="new-password" required>
        <button id="submit" type="submit">Update password</button><div id="error" role="alert" class="error"></div></form>"""
        script = """
        const f=document.getElementById("auth-form"),b=document.getElementById("submit"),e=document.getElementById("error");
        document.getElementById("token").value=new URLSearchParams(location.search).get("token")||"";
        f.addEventListener("submit",async ev=>{ev.preventDefault();const d=Object.fromEntries(new FormData(f));if(d.password!==d.confirm_password){e.textContent="Your passwords do not match.";return;}
        b.disabled=true;b.textContent="Updating…";e.textContent="";try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/auth/reset-password",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify(d)});
        const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Reset link is invalid or expired.");location.href="/auth/login?reset=success";
        }catch(x){e.textContent=x.message;}finally{b.disabled=false;b.textContent="Update password";}});
        """
        return _auth_page("Choose a new password", "Use a strong password you have not used elsewhere.", content, script)

    @app.get("/verify-email")
    def core_verify_screen():
        content = """
        <p id="status" role="status">Open the verification link sent to your email address. If you need another link, request one below.</p>
        <form id="auth-form"><label>Email address</label><input name="email" type="email" autocomplete="email" required>
        <button id="submit" type="submit">Resend verification email</button><div id="message" class="error" role="status"></div></form>
        <div class="links"><a href="/auth/login">Back to sign in</a></div>"""
        script = """
        const f=document.getElementById("auth-form"),b=document.getElementById("submit"),m=document.getElementById("message");
        f.elements.email.value=new URLSearchParams(location.search).get("email")||"";
        const token=new URLSearchParams(location.search).get("token");if(token){fetch("/api/v1/auth/csrf").then(x=>x.json()).then(c=>fetch("/api/v1/auth/verify-email",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify({token})})).then(async r=>{const x=await r.json();document.getElementById("status").textContent=r.ok?"Your email is verified. You can now sign in.":(x.error?.message||"This verification link is invalid or expired.");}).catch(()=>{});}
        f.addEventListener("submit",async ev=>{ev.preventDefault();b.disabled=true;m.textContent="";try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/auth/resend-verification",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify({email:f.elements.email.value})});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Please try again.");m.textContent=x.data.message;}catch(x){m.textContent=x.message;}finally{b.disabled=false;}});
        """
        return _auth_page("Verify your email", "One quick confirmation protects your Career Agency account.", content, script)

    @app.get("/api/v1/auth/csrf")
    def core_csrf_token():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return jsonify({"data": {"csrf_token": token}, "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/auth/verify-email")
    def core_verify_email():
        data = request.get_json(silent=True) or {}
        raw = str(data.get("token", "")).strip()
        if not raw:
            return _json_error("VALIDATION_ERROR", "Verification token is required.", 400)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND purpose=? AND consumed_at IS NULL AND expires_at>?",
                             (digest, "email_verification", utc_now())).fetchone()
            if not row:
                db.rollback()
                return _json_error("INVALID_TOKEN", "This verification link is invalid or expired.", 400)
            db.execute("UPDATE auth_tokens SET consumed_at=? WHERE id=?", (utc_now(), row["id"]))
            db.execute("UPDATE users SET email_verified_at=?,account_status=?,updated_at=? WHERE id=?",
                       (utc_now(), "active", utc_now(), row["user_id"]))
            db.commit()
        _audit(row["user_id"], "auth.email_verified", "user", row["user_id"], "success")
        return jsonify({"data": {"verified": True}, "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/auth/resend-verification")
    def core_resend_verification():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        bucket = hashlib.sha256(((request.remote_addr or "unknown") + ":" + email).encode()).hexdigest()
        if not _rate_limit("resend-verification:" + bucket, 4, 900):
            return jsonify({"data": {"message": "If the account needs verification, a new email will be sent shortly."},
                            "request_id": str(uuid.uuid4())})
        with _connect() as db:
            user = db.execute("SELECT id,email_verified_at FROM users WHERE email=?", (email,)).fetchone()
        if user and not user["email_verified_at"]:
            token = _issue_auth_token(user["id"], "email_verification", 86400)
            try:
                _send_auth_email(email, "Verify your Career Agency account",
                                 "Verify your email: " + _auth_email_link("/verify-email", token))
            except Exception:
                app.logger.exception("Verification email delivery failed")
        return jsonify({"data": {"message": "If the account needs verification, a new email will be sent shortly."},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/auth/forgot-password")
    def core_forgot_password():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        bucket = hashlib.sha256(((request.remote_addr or "unknown") + ":" + email).encode()).hexdigest()
        if not _rate_limit("forgot-password:" + bucket, 4, 900):
            return jsonify({"data": {"message": "If an account exists for that address, password reset instructions will be sent shortly."},
                            "request_id": str(uuid.uuid4())})
        with _connect() as db:
            user = db.execute("SELECT id FROM users WHERE email=? AND account_status='active'", (email,)).fetchone()
        if user:
            token = _issue_auth_token(user["id"], "password_reset", 3600)
            try:
                _send_auth_email(email, "Reset your Career Agency password",
                                 "Reset your password: " + _auth_email_link("/reset-password", token))
            except Exception:
                app.logger.exception("Password reset email delivery failed")
        return jsonify({"data": {"message": "If an account exists for that address, password reset instructions will be sent shortly."},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/auth/reset-password")
    def core_reset_password():
        data = request.get_json(silent=True) or {}
        raw = str(data.get("token", ""))
        password = str(data.get("password", ""))
        confirm = str(data.get("confirm_password", password))
        if len(password) < 10 or len(password) > 1024:
            return _json_error("VALIDATION_ERROR", "Password must contain between 10 and 1024 characters.", 400)
        if password != confirm:
            return _json_error("PASSWORD_MISMATCH", "The passwords do not match.", 400)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND purpose=? AND consumed_at IS NULL AND expires_at>?",
                             (digest, "password_reset", utc_now())).fetchone()
            if not row:
                db.rollback()
                return _json_error("INVALID_TOKEN", "This reset link is invalid or expired.", 400)
            db.execute("UPDATE auth_tokens SET consumed_at=? WHERE id=?", (utc_now(), row["id"]))
            db.execute("UPDATE users SET password_hash=?,session_version=session_version+1,updated_at=? WHERE id=?",
                       (generate_password_hash(password, method="scrypt"), utc_now(), row["user_id"]))
            db.commit()
        _audit(row["user_id"], "auth.password_reset", "user", row["user_id"], "success")
        return jsonify({"data": {"password_updated": True, "sessions_revoked": True},
                         "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/auth/register")
    def core_register():
        data = request.get_json(silent=True) or {}
        name = str(data.get("full_name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        confirm = str(data.get("confirm_password", ""))
        role = str(data.get("role", "job_seeker"))
        if not name or len(name) > 120 or len(email) > 254 or "@" not in email or len(password) < 10:
            return _json_error("VALIDATION_ERROR", "Provide a valid name and email, and a password of at least 10 characters.", 400)
        if password != confirm:
            return _json_error("PASSWORD_MISMATCH", "The passwords do not match.", 400)
        if data.get("terms_accepted") is not True:
            return _json_error("CONSENT_REQUIRED", "You must accept the Terms and Privacy Policy to create an account.", 400)
        if role not in {"job_seeker", "employer", "recruiter"}:
            return _json_error("VALIDATION_ERROR", "This account type cannot be registered here.", 400)
        if not _rate_limit("register:" + hashlib.sha256((request.remote_addr or "unknown").encode()).hexdigest(), 5, 3600):
            return _json_error("RATE_LIMITED", "Too many registration attempts. Try again later.", 429)
        user_id = str(uuid.uuid4())
        now = utc_now()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT INTO users(id,email,password_hash,full_name,role,account_status,
                       email_verified_at,credits,created_at,updated_at)
                       VALUES(?,?,?,?,?,'pending_verification',NULL,0,?,?)""",
                    (user_id, email, generate_password_hash(password, method="scrypt"), name, role, now, now),
                )
        except sqlite3.IntegrityError:
            return _json_error("CONFLICT", "An account with these details may already exist.", 409)
        token = _issue_auth_token(user_id, "email_verification", 86400)
        delivery = "queued"
        try:
            _send_auth_email(email, "Verify your Career Agency account",
                             "Welcome to Career Agency. Verify your email: " +
                             _auth_email_link("/verify-email", token))
        except Exception:
            delivery = "not_configured"
            app.logger.exception("Verification email delivery failed")
        _audit(user_id, "account.registered", "user", user_id, "success", {"role": role})
        return jsonify({"data": {"user_id": user_id, "status": "pending_verification",
                                 "verification_email": delivery},
                        "request_id": str(uuid.uuid4())}), 201

    @app.post("/api/v1/auth/login")
    def core_login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        with _connect() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not _rate_limit("login:" + hashlib.sha256(((request.remote_addr or "unknown") + ":" + email).encode()).hexdigest(), 8, 900):
            return _json_error("RATE_LIMITED", "Too many sign-in attempts. Wait before trying again.", 429)
        if not user or not check_password_hash(user["password_hash"], password):
            return _json_error("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
        if user["account_status"] == "pending_verification" or not user["email_verified_at"]:
            return _json_error("EMAIL_NOT_VERIFIED", "Verify your email address before signing in.", 403)
        if user["account_status"] != "active":
            return _json_error("ACCOUNT_UNAVAILABLE", "This account cannot access the service.", 403)
        session.clear()
        session["core_user_id"] = user["id"]
        session["core_role"] = user["role"]
        session["core_session_version"] = int(user["session_version"])
        _audit(user["id"], "auth.login", "user", user["id"], "success")
        return jsonify({"data": {"user": {"id": user["id"], "email": user["email"],
            "full_name": user["full_name"], "role": user["role"]},
            "wallet": {"credits": user["credits"]}}, "request_id": str(uuid.uuid4())})

    @app.get("/auth/logout")
    def core_logout_screen():
        content = """<p>You are about to sign out of this device.</p>
        <button id="signout" type="button">Sign out</button>
        <div id="error" class="error" role="alert"></div>
        <div class="links"><a href="/workspace">Return to workspace</a></div>"""
        script = """
        document.getElementById("signout").addEventListener("click",async()=>{const b=document.getElementById("signout"),e=document.getElementById("error");b.disabled=true;
        try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/auth/logout",{method:"POST",headers:{"X-CSRF-Token":c.data.csrf_token}});if(!r.ok)throw new Error("Could not sign out. Please retry.");location.href="/auth/login";}
        catch(x){e.textContent=x.message;b.disabled=false;}});
        """
        return _auth_page("Sign out", "End your current Career Agency session.", content, script)

    @app.post("/api/v1/auth/logout")
    def core_logout():
        session.clear()
        return jsonify({"data": {"logged_out": True}, "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/auth/me")
    @_require_user
    def core_me():
        user = _current_user()
        return jsonify({"data": {"user": dict(user), "wallet": {"credits": user["credits"]}},
                        "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/wallet")
    @_require_user
    def core_wallet():
        user = _current_user()
        return jsonify({"data": {"credits": user["credits"], "currency": "NGN"},
                        "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/wallet/ledger")
    @_require_user
    def core_ledger():
        user = _current_user()
        limit = min(max(request.args.get("limit", default=30, type=int), 1), 100)
        with _connect() as db:
            rows = db.execute(
                """SELECT delta,balance_after,entry_type,description,created_at
                   FROM credit_ledger WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
                (user["id"], limit),
            ).fetchall()
        return jsonify({"data": [dict(row) for row in rows], "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/credit-packages")
    @_require_user
    def core_packages():
        with _connect() as db:
            rows = db.execute(
                """SELECT id,price_kobo,credits,bonus_credits FROM credit_packages
                   WHERE active=1 ORDER BY display_order"""
            ).fetchall()
        return jsonify({"data": {"currency": "NGN", "packages": [dict(r) for r in rows]},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/payments/paystack/initialize")
    @_require_user
    def paystack_initialize():
        user = _current_user()
        data = request.get_json(silent=True) or {}
        package_id = str(data.get("package_id", ""))
        with _connect() as db:
            package = db.execute("SELECT * FROM credit_packages WHERE id=? AND active=1",
                                 (package_id,)).fetchone()
        if not package:
            return _json_error("PACKAGE_UNAVAILABLE", "This credit package is not available.", 404)
        reference = "ca_" + secrets.token_urlsafe(24)
        payment_id = str(uuid.uuid4())
        now = utc_now()
        with _connect() as db:
            db.execute(
                """INSERT INTO payments(id,user_id,package_id,reference,amount_kobo,currency,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,'NGN','initialized',?,?)""",
                (payment_id, user["id"], package_id, reference, package["price_kobo"], now, now),
            )
        try:
            result = _paystack_request("/transaction/initialize", {
                "email": user["email"], "amount": int(package["price_kobo"]),
                "currency": "NGN", "reference": reference,
                "metadata": {"payment_id": payment_id, "user_id": user["id"], "package_id": package_id},
            })
            if not result.get("status") or not result.get("data", {}).get("authorization_url"):
                raise RuntimeError("Paystack did not return a checkout URL")
        except Exception:
            with _connect() as db:
                db.execute("UPDATE payments SET status='failed',updated_at=? WHERE id=?",
                           (utc_now(), payment_id))
            return _json_error("PAYMENT_INITIALIZATION_FAILED", "Unable to start checkout. Please try again.", 502)
        with _connect() as db:
            db.execute("UPDATE payments SET status='pending',updated_at=? WHERE id=?",
                       (utc_now(), payment_id))
        return jsonify({"data": {"reference": reference,
            "authorization_url": result["data"]["authorization_url"],
            "access_code": result["data"].get("access_code")}, "request_id": str(uuid.uuid4())}), 201

    @app.get("/api/v1/payments/<reference>")
    @_require_user
    def paystack_payment_status(reference):
        user = _current_user()
        with _connect() as db:
            row = db.execute(
                "SELECT reference,amount_kobo,currency,status,verified_at FROM payments WHERE reference=? AND user_id=?",
                (reference, user["id"]),
            ).fetchone()
        if not row:
            return _json_error("NOT_FOUND", "Payment not found.", 404)
        return jsonify({"data": dict(row), "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/payments/paystack/webhook")
    def paystack_webhook():
        raw = request.get_data(cache=True)
        secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
        supplied = request.headers.get("x-paystack-signature", "")
        if not secret or not supplied:
            return _json_error("INVALID_WEBHOOK_SIGNATURE", "Webhook signature is invalid.", 401)
        expected = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            return _json_error("INVALID_WEBHOOK_SIGNATURE", "Webhook signature is invalid.", 401)
        payload_hash = hashlib.sha256(raw).hexdigest()
        event = request.get_json(silent=True) or {}
        if event.get("event") != "charge.success":
            return jsonify({"received": True, "ignored": True}), 200
        reference = str((event.get("data") or {}).get("reference", ""))
        if not reference:
            return _json_error("INVALID_WEBHOOK", "Payment reference is missing.", 400)
        try:
            verified = _paystack_request("/transaction/verify/" + reference)
        except Exception:
            return _json_error("PAYMENT_VERIFICATION_UNAVAILABLE", "Payment verification will be retried.", 503)
        tx = verified.get("data") or {}
        if not verified.get("status") or tx.get("status") != "success" or tx.get("currency") != "NGN":
            return _json_error("PAYMENT_NOT_VERIFIED", "Payment has not been verified as successful.", 400)
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            payment = db.execute("SELECT * FROM payments WHERE reference=?", (reference,)).fetchone()
            if not payment:
                db.rollback()
                return _json_error("PAYMENT_NOT_FOUND", "Payment reference is not recognised.", 404)
            if int(tx.get("amount", -1)) != int(payment["amount_kobo"]):
                db.rollback()
                return _json_error("PAYMENT_AMOUNT_MISMATCH", "Verified amount does not match the order.", 400)
            metadata = tx.get("metadata") or {}
            if not isinstance(metadata, dict) or (
                metadata.get("payment_id") != payment["id"]
                or metadata.get("user_id") != payment["user_id"]
                or metadata.get("package_id") != payment["package_id"]
            ):
                db.rollback()
                return _json_error("PAYMENT_METADATA_MISMATCH", "Verified transaction metadata does not match the order.", 400)
            if not tx.get("id") or tx.get("reference") != reference:
                db.rollback()
                return _json_error("PAYMENT_REFERENCE_MISMATCH", "Verified transaction reference is invalid.", 400)
            if payment["status"] == "success":
                db.commit()
                return jsonify({"received": True, "already_processed": True}), 200
            package = db.execute("SELECT credits FROM credit_packages WHERE id=?",
                                 (payment["package_id"],)).fetchone()
            if not package:
                db.rollback()
                return _json_error("PACKAGE_NOT_FOUND", "Credit package is unavailable.", 409)
            user = db.execute("SELECT credits FROM users WHERE id=?", (payment["user_id"],)).fetchone()
            new_balance = int(user["credits"]) + int(package["credits"])
            db.execute("UPDATE users SET credits=?,updated_at=? WHERE id=?",
                       (new_balance, utc_now(), payment["user_id"]))
            db.execute(
                """INSERT INTO credit_ledger
                   (id,user_id,delta,balance_after,entry_type,reference_type,reference_id,
                    idempotency_key,description,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), payment["user_id"], int(package["credits"]), new_balance,
                 "purchase", "payment", payment["id"], "payment:" + reference,
                 "Verified Paystack credit purchase", utc_now()),
            )
            db.execute(
                """UPDATE payments SET status='success',provider_transaction_id=?,verified_at=?,updated_at=?
                   WHERE id=?""",
                (str(tx.get("id", "")), utc_now(), utc_now(), payment["id"]),
            )
            db.execute(
                """INSERT OR IGNORE INTO webhook_events
                   (id,provider,event_key,payload_hash,signature_valid,processing_status,created_at,processed_at)
                   VALUES(?,'paystack',?,?,1,'processed',?,?)""",
                (str(uuid.uuid4()), reference, payload_hash, utc_now(), utc_now()),
            )
            db.commit()
        _audit(payment["user_id"], "wallet.payment_credited", "payment", payment["id"], "success",
               {"reference": reference, "credits": int(package["credits"])})
        return jsonify({"received": True, "credited": int(package["credits"])}), 200

    @app.post("/api/v1/ai/actions/<action_key>")
    @_require_user
    def core_ai_action(action_key):
        user = _current_user()
        if action_key not in ACTION_BASE_COSTS:
            return _json_error("UNKNOWN_ACTION", "This AI action is not supported.", 404)
        data = request.get_json(silent=True) or {}
        input_payload = data.get("input")
        if not isinstance(input_payload, dict):
            return _json_error("VALIDATION_ERROR", "The input field must be an object.", 400)
        model = "server-default"
        prompt_version = "v1"
        key = _cache_key(action_key, user["id"], input_payload, model, prompt_version)
        request_id = str(uuid.uuid4())
        # Required ordering: SQLite llm_cache is checked before any debit or LLM call.
        with _connect() as db:
            cached = db.execute(
                """SELECT response_json FROM llm_cache
                   WHERE cache_key=? AND (expires_at IS NULL OR expires_at>?)""",
                (key, utc_now()),
            ).fetchone()
            price = db.execute(
                "SELECT base_cost,cache_hit_cost,active FROM credit_action_prices WHERE action_key=?",
                (action_key,),
            ).fetchone()
        if not price or not price["active"]:
            return _json_error("ACTION_UNAVAILABLE", "This AI action is temporarily unavailable.", 503)
        cache_hit = cached is not None
        if cache_hit and price["cache_hit_cost"] is None:
            return _json_error("CACHE_PRICE_NOT_CONFIGURED",
                "A discounted price has not been approved for this cached action.", 503)
        cost = int(price["cache_hit_cost"] if cache_hit else price["base_cost"])
        idem = request.headers.get("Idempotency-Key") or data.get("client_request_id") or request_id
        try:
            balance = _debit(user["id"], cost, action_key, request_id, str(idem))
        except (LookupError, ValueError):
            return _json_error("REQUEST_FAILED", "The action could not be processed.", 500)
        if balance is None:
            return _json_error("INSUFFICIENT_CREDITS", "There are not enough credits for this action.",
                               402, required=cost, available=int(user["credits"]))
        with _connect() as db:
            db.execute(
                """INSERT INTO ai_requests
                   (id,user_id,action_key,cache_key,cache_hit,credits_charged,status,provider,model,created_at,completed_at)
                   VALUES(?,?,?,?,?,?,?, ?,?,?,?)""",
                (request_id, user["id"], action_key, key, int(cache_hit), cost,
                 "completed" if cache_hit else "pending", "sqlite-cache" if cache_hit else None,
                 model, utc_now(), utc_now() if cache_hit else None),
            )
            if cache_hit:
                db.execute("UPDATE llm_cache SET hit_count=hit_count+1,last_hit_at=? WHERE cache_key=?",
                           (utc_now(), key))
        if cache_hit:
            return jsonify({"data": {"request_id": request_id, "cache": {"hit": True},
                "credits": {"charged": cost, "balance": balance},
                "result": json.loads(cached["response_json"])}, "request_id": request_id})
        try:
            generated = _llm_generate(action_key, input_payload, model)
            response_json = json.dumps(generated, ensure_ascii=False, separators=(",", ":"))
            with _connect() as db:
                db.execute(
                    """INSERT OR REPLACE INTO llm_cache
                       (cache_key,action_key,provider,model,prompt_version,input_hash,response_json,created_at,expires_at,hit_count)
                       VALUES(?,?,?,?,?,?,?,?,?,0)""",
                    (key, action_key, "configured-adapter", model, prompt_version,
                     hashlib.sha256(json.dumps(input_payload, sort_keys=True).encode()).hexdigest(),
                     response_json, utc_now(), None),
                )
                db.execute("UPDATE ai_requests SET status=?,provider=?,completed_at=? WHERE id=?",
                           ("completed", "configured-adapter", utc_now(), request_id))
            return jsonify({"data": {"request_id": request_id, "cache": {"hit": False},
                "credits": {"charged": cost, "balance": balance}, "result": generated},
                "request_id": request_id})
        except Exception:
            _refund(user["id"], cost, request_id, "AI provider failed; automatic refund")
            with _connect() as db:
                db.execute("UPDATE ai_requests SET status=?,error_code=?,completed_at=? WHERE id=?",
                           ("refunded", "AI_PROVIDER_ERROR", utc_now(), request_id))
            return _json_error("AI_PROVIDER_ERROR",
                "The AI service is temporarily unavailable. Your credits have been refunded.", 502)

    @app.post("/api/v1/admin/credit-packages/<package_id>/activate")
    @_require_user
    def activate_credit_package(package_id):
        user = _current_user()
        if user["role"] != "admin":
            return _json_error("FORBIDDEN", "Administrator permission is required.", 403)
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason", "")).strip()
        if len(reason) < 8:
            return _json_error("VALIDATION_ERROR", "Provide an audit reason.", 400)
        with _connect() as db:
            cur = db.execute("UPDATE credit_packages SET active=1 WHERE id=?", (package_id,))
            if cur.rowcount != 1:
                return _json_error("NOT_FOUND", "Package not found.", 404)
        _audit(user["id"], "credit_package.activated", "credit_package", package_id, "success",
               {"reason": reason})
        return jsonify({"data": {"activated": True}, "request_id": str(uuid.uuid4())})
