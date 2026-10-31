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
        CREATE TABLE IF NOT EXISTS mobile_access_tokens (
            jti TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            family_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_access_family
            ON mobile_access_tokens(family_id,user_id);
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
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            employer_user_id TEXT NOT NULL REFERENCES users(id),
            organization_id TEXT REFERENCES organizations(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT,
            work_mode TEXT NOT NULL DEFAULT 'onsite',
            employment_type TEXT NOT NULL DEFAULT 'full_time',
            salary_min_ngn INTEGER,
            salary_max_ngn INTEGER,
            status TEXT NOT NULL DEFAULT 'draft',
            published_at TEXT,
            closes_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status_published ON jobs(status,published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_employer ON jobs(employer_user_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id),
            applicant_user_id TEXT NOT NULL REFERENCES users(id),
            cv_document_id TEXT,
            cover_letter TEXT,
            status TEXT NOT NULL DEFAULT 'submitted',
            applied_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(job_id,applicant_user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_applications_applicant ON applications(applicant_user_id,applied_at DESC);
        CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id,status);
        CREATE TABLE IF NOT EXISTS saved_jobs (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id,job_id)
        );
        CREATE TABLE IF NOT EXISTS cv_documents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            file_key TEXT,
            content_text TEXT,
            document_status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cv_user_updated ON cv_documents(user_id,updated_at DESC);
        CREATE TABLE IF NOT EXISTS interviews (
            id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL REFERENCES applications(id),
            scheduled_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 30,
            meeting_url TEXT,
            status TEXT NOT NULL DEFAULT 'scheduled',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            target_url TEXT,
            read_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(user_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS recruiter_pipeline_items (
            id TEXT PRIMARY KEY,
            recruiter_user_id TEXT NOT NULL REFERENCES users(id),
            candidate_name TEXT NOT NULL,
            candidate_email TEXT,
            role_title TEXT,
            pipeline_stage TEXT NOT NULL DEFAULT 'sourced',
            candidate_consent_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS ai_quotes (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_key TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            cache_hit INTEGER NOT NULL,
            credits_cost INTEGER NOT NULL CHECK(credits_cost >= 0),
            quote_token_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_quotes_user_created ON ai_quotes(user_id,created_at DESC);
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
        pipeline_columns = {row["name"] for row in db.execute("PRAGMA table_info(recruiter_pipeline_items)").fetchall()}
        if "candidate_consent_at" not in pipeline_columns:
            db.execute("ALTER TABLE recruiter_pipeline_items ADD COLUMN candidate_consent_at TEXT")
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
                jti = payload.get("jti")
                if not jti:
                    return None
                with _connect() as token_db:
                    active_token = token_db.execute(
                        "SELECT 1 FROM mobile_access_tokens WHERE jti=? AND revoked_at IS NULL AND expires_at>?",
                        (jti, utc_now()),
                    ).fetchone()
                if not active_token:
                    return None
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


def _create_notification(user_id: str, category: str, title: str, body: str, target_url: str | None = None):
    with _connect() as db:
        db.execute("INSERT INTO notifications(id,user_id,category,title,body,target_url,created_at) VALUES(?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()), user_id, category, title[:160], body[:1000], target_url, utc_now()))


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


def _issue_mobile_access(user, family_id: str) -> str:
    jti = str(uuid.uuid4())
    expires = datetime.fromtimestamp(time.time() + 900, timezone.utc).isoformat()
    with _connect() as db:
        db.execute("INSERT INTO mobile_access_tokens(jti,user_id,family_id,expires_at,created_at) VALUES(?,?,?,?,?)",
                   (jti, user["id"], family_id, expires, utc_now()))
    payload = {"sub": user["id"], "role": user["role"], "sv": int(user["session_version"]),
               "jti": jti, "family": family_id}
    return URLSafeTimedSerializer(current_app.secret_key, salt="career-agency-mobile-access").dumps(payload)


def _issue_mobile_refresh(user_id: str, family_id: str | None = None):
    raw = secrets.token_urlsafe(48)
    row_id = str(uuid.uuid4())
    family = family_id or str(uuid.uuid4())
    expires = datetime.fromtimestamp(time.time() + 30 * 86400, timezone.utc).isoformat()
    with _connect() as db:
        db.execute("INSERT INTO mobile_refresh_tokens(id,user_id,family_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                   (row_id, user_id, family, hashlib.sha256(raw.encode()).hexdigest(), expires, utc_now()))
    return raw, family, row_id


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
input,select,textarea{width:100%;min-height:49px;padding:13px 14px;border-radius:12px;border:1px solid #344560;background:#091222;color:#f7faff;font:500 15px "DM Sans",sans-serif;outline:none}textarea{min-height:120px;resize:vertical;line-height:1.6}
input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px #78a9ff24}
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
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path != "/api/v1/payments/paystack/webhook" and not request.path.startswith("/api/v1/mobile/auth/"):
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return _json_error("CSRF_VALIDATION_FAILED", "Refresh the page and try again.", 403)
        allowed = (
            request.path in {"/auth/login", "/auth/logout", "/register", "/forgot-password",
                             "/reset-password", "/verify-email", "/terms", "/privacy",
                             "/onboarding", "/profile", "/wallet", "/ai-assistant", "/payments/return", "/api/v1/profile", "/api/v1/wallet", "/api/v1/wallet/ledger", "/api/v1/credit-packages",
                             "/api/v1/dashboard", "/api/v1/saved-jobs", "/notifications", "/api/v1/notifications"}
            or request.path.startswith("/api/v1/notifications/")
            or request.path == "/api/v1/cvs"
            or request.path.startswith("/api/v1/cvs/")
            or request.path == "/api/v1/cvs"
            or request.path.startswith("/api/v1/cvs/")
            or request.path.startswith("/workspace/modules/")
            or request.path.startswith("/workspace/jobs")
            or request.path.startswith("/workspace/applications")
            or request.path.startswith("/workspace/employer/jobs")
            or request.path.startswith("/workspace/cv-studio")
            or request.path.startswith("/workspace/recruiter/pipeline")
            or request.path.startswith("/api/v1/auth/")
            or request.path.startswith("/api/v1/mobile/auth/")
            or request.path.startswith("/api/v1/onboarding/")
            or request.path == "/api/v1/jobs"
            or request.path.startswith("/api/v1/jobs/")
            or request.path == "/api/v1/applications"
            or request.path.startswith("/api/v1/applications/")
            or request.path.startswith("/api/v1/recruiter/pipeline")
            or request.path == "/api/v1/ai/quote"
            or request.path.startswith("/api/v1/ai/actions/")
            or request.path.startswith("/api/v1/payments/")
            or request.path.startswith("/api/v1/admin/credit-packages/")
            or request.path.startswith("/api/v1/admin/organizations/")
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

    @app.get("/workspace/jobs")
    @_require_user
    def core_job_discovery_screen():
        user = _current_user()
        if user["role"] != "job_seeker":
            return redirect("/workspace/employer/jobs" if user["role"] == "employer" else "/workspace")
        content = """
        <form id="search-form"><label>Search roles</label><input name="q" placeholder="Job title or keyword">
        <label>Location</label><input name="location" placeholder="City, state or remote">
        <label>Work arrangement</label><select name="work_mode"><option value="">Any</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select>
        <label>Employment type</label><select name="employment_type"><option value="">Any</option><option value="full_time">Full-time</option><option value="part_time">Part-time</option><option value="contract">Contract</option><option value="internship">Internship</option><option value="temporary">Temporary</option></select>
        <button type="submit" id="search">Search jobs</button></form>
        <div id="results" style="display:grid;gap:12px;margin-top:22px"><div class="empty">Loading available jobs…</div></div>
        <div id="error" class="error" role="alert"></div><div class="links"><a href="/workspace">Back to workspace</a><a href="/workspace/applications">My applications</a></div>"""
        script = """
        const f=document.getElementById("search-form"),results=document.getElementById("results"),error=document.getElementById("error");
        function card(j){const el=document.createElement("article");el.style.cssText="padding:17px;border:1px solid #263852;border-radius:14px;background:#0d182a";
        const h=document.createElement("h3");h.textContent=j.title;h.style.margin="0 0 6px";const org=document.createElement("p");org.textContent=j.organisation_name||"Employer";org.style.cssText="color:#9aabc3;font-size:12px;margin:0 0 8px";
        const meta=document.createElement("p");meta.textContent=[j.location,j.work_mode,j.employment_type].filter(Boolean).join(" · ");meta.style.cssText="color:#91a3bd;font-size:12px";
        const a=document.createElement("a");a.href="/workspace/jobs/"+encodeURIComponent(j.id);a.textContent="View job";a.style.color="#93baff";el.append(h,org,meta,a);return el;}
        async function load(){error.textContent="";results.innerHTML='<div class="empty">Searching…</div>';const p=new URLSearchParams(new FormData(f));try{const r=await fetch("/api/v1/jobs?"+p.toString());const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not load jobs.");results.innerHTML="";if(!x.data.jobs.length){results.innerHTML='<div class="empty">No published jobs match those filters yet. Try a broader search.</div>';return;}x.data.jobs.forEach(j=>results.append(card(j)));}catch(e){error.textContent=e.message;results.innerHTML='<div class="empty">Job search is temporarily unavailable.</div>';}}
        f.addEventListener("submit",e=>{e.preventDefault();load();});load();
        """
        return _auth_page("Discover jobs", "Explore published opportunities and manage your applications.", content, script)

    @app.get("/workspace/jobs/<job_id>")
    @_require_user
    def core_job_detail_screen(job_id):
        user = _current_user()
        if user["role"] != "job_seeker":
            return redirect("/workspace")
        content = """
        <div id="job"><div class="empty">Loading job details…</div></div>
        <div id="actions" style="display:none;gap:10px;margin-top:18px"><button id="save" type="button" style="margin:0;background:#253a59">Save job</button><button id="apply-toggle" type="button" style="margin:0">Apply now</button></div>
        <form id="apply-form" style="display:none;margin-top:18px"><label>Cover letter (optional)</label><textarea name="cover_letter" rows="6" maxlength="5000" placeholder="Explain why you are interested in this role…"></textarea><button id="submit" type="submit">Submit application</button></form>
        <div id="message" class="error" role="status"></div><div class="links"><a href="/workspace/jobs">Back to jobs</a><a href="/workspace/applications">My applications</a></div>"""
        script = """
        const id=decodeURIComponent(location.pathname.split("/").pop()),box=document.getElementById("job"),actions=document.getElementById("actions"),msg=document.getElementById("message"),form=document.getElementById("apply-form");
        async function csrf(){return (await fetch("/api/v1/auth/csrf").then(r=>r.json())).data.csrf_token;}
        fetch("/api/v1/jobs/"+encodeURIComponent(id)).then(async r=>{const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Job not found.");const j=x.data;
        const h=document.createElement("h2");h.textContent=j.title;const org=document.createElement("p");org.textContent=j.organisation_name||"Employer";const meta=document.createElement("p");meta.textContent=[j.location,j.work_mode,j.employment_type].filter(Boolean).join(" · ");const desc=document.createElement("p");desc.textContent=j.description;desc.style.cssText="white-space:pre-wrap;line-height:1.7;color:#c6d3e6";box.innerHTML="";box.append(h,org,meta,desc);actions.style.display="flex";
        }).catch(e=>{box.textContent=e.message;});
        document.getElementById("save").addEventListener("click",async()=>{const token=await csrf();const r=await fetch("/api/v1/jobs/"+encodeURIComponent(id)+"/save",{method:"POST",headers:{"X-CSRF-Token":token}});const x=await r.json();msg.textContent=r.ok?"Job saved to your list.":(x.error?.message||"Could not save job.");});
        document.getElementById("apply-toggle").addEventListener("click",()=>{form.style.display=form.style.display==="none"?"block":"none";});
        form.addEventListener("submit",async e=>{e.preventDefault();const b=document.getElementById("submit");b.disabled=true;const token=await csrf();try{const r=await fetch("/api/v1/jobs/"+encodeURIComponent(id)+"/apply",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify({cover_letter:form.elements.cover_letter.value})});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Application failed.");msg.textContent="Your application has been submitted.";form.style.display="none";}catch(x){msg.textContent=x.message;}finally{b.disabled=false;}});
        """
        return _auth_page("Job details", "Review the role carefully before submitting an application.", content, script)

    @app.get("/workspace/recruiter/pipeline")
    @_require_user
    def core_recruiter_pipeline_screen():
        user = _current_user()
        if user["role"] != "recruiter":
            return redirect("/workspace")
        content = """
        <form id="candidate-form"><h3>Add a candidate</h3><label>Candidate name</label><input name="candidate_name" maxlength="160" required>
        <label>Candidate email (optional)</label><input name="candidate_email" type="email" maxlength="254">
        <label>Target role</label><input name="role_title" maxlength="160" required>
        <label class="consent"><input type="checkbox" name="candidate_consent" required><span>I confirm that I have the candidate's permission or another lawful basis to store and manage these details.</span></label>
        <button id="add" type="submit">Add to pipeline</button></form>
        <div id="message" class="error" role="status"></div><h3 style="margin-top:25px">Candidate pipeline</h3>
        <div id="pipeline" style="display:grid;gap:11px"><div class="empty">Loading pipeline…</div></div>
        <div class="links"><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const form=document.getElementById("candidate-form"),root=document.getElementById("pipeline"),message=document.getElementById("message");
        async function csrf(){return (await fetch("/api/v1/auth/csrf").then(r=>r.json())).data.csrf_token;}
        async function load(){const r=await fetch("/api/v1/recruiter/pipeline");const x=await r.json();root.innerHTML="";if(!r.ok){root.textContent=x.error?.message||"Unable to load pipeline.";return;}if(!x.data.length){root.innerHTML='<div class="empty">Your candidate pipeline is empty.</div>';return;}
        x.data.forEach(c=>{const el=document.createElement("article");el.style.cssText="padding:14px;border:1px solid #263852;border-radius:13px;background:#0d182a";const h=document.createElement("strong");h.textContent=c.candidate_name;const p=document.createElement("p");p.textContent=[c.role_title,c.candidate_email,c.pipeline_stage].filter(Boolean).join(" · ");p.style.color="#9aabc3";
        const select=document.createElement("select");["sourced","contacted","screening","shortlisted","interview","offer","hired","rejected"].forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;if(v===c.pipeline_stage)o.selected=true;select.append(o);});
        const b=document.createElement("button");b.textContent="Update stage";b.style.marginTop="10px";b.addEventListener("click",async()=>{const t=await csrf();const r=await fetch("/api/v1/recruiter/pipeline/"+encodeURIComponent(c.id),{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":t},body:JSON.stringify({pipeline_stage:select.value})});const x=await r.json();message.textContent=r.ok?"Candidate stage updated.":(x.error?.message||"Could not update stage.");load();});el.append(h,p,select,b);root.append(el);});}
        form.addEventListener("submit",async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(form));d.candidate_consent=form.elements.candidate_consent.checked;const b=document.getElementById("add");b.disabled=true;try{const t=await csrf();const r=await fetch("/api/v1/recruiter/pipeline",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":t},body:JSON.stringify(d)});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not add candidate.");message.textContent="Candidate added to your pipeline.";form.reset();load();}catch(x){message.textContent=x.message;}finally{b.disabled=false;}});load();
        """
        return _auth_page("Recruitment pipeline", "Manage candidate progress while respecting candidate privacy and consent.", content, script)

    @app.get("/api/v1/recruiter/pipeline")
    @_require_user
    def core_recruiter_pipeline_list():
        user = _current_user()
        if user["role"] != "recruiter":
            return _json_error("FORBIDDEN", "Recruiter permission is required.", 403)
        with _connect() as db:
            rows = db.execute("SELECT id,candidate_name,candidate_email,role_title,pipeline_stage,created_at,updated_at FROM recruiter_pipeline_items WHERE recruiter_user_id=? ORDER BY updated_at DESC",
                              (user["id"],)).fetchall()
        return jsonify({"data": [dict(row) for row in rows], "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/recruiter/pipeline")
    @_require_user
    def core_recruiter_pipeline_add():
        user = _current_user()
        if user["role"] != "recruiter":
            return _json_error("FORBIDDEN", "Recruiter permission is required.", 403)
        data = request.get_json(silent=True) or {}
        name = str(data.get("candidate_name", "")).strip()
        email = str(data.get("candidate_email", "")).strip().lower()
        title = str(data.get("role_title", "")).strip()
        if not name or len(name) > 160 or not title or len(title) > 160 or len(email) > 254:
            return _json_error("VALIDATION_ERROR", "Provide a valid candidate name and target role.", 400)
        if data.get("candidate_consent") is not True:
            return _json_error("CANDIDATE_CONSENT_REQUIRED", "Confirm candidate permission or another lawful basis before storing candidate information.", 400)
        item_id, now = str(uuid.uuid4()), utc_now()
        with _connect() as db:
            db.execute("INSERT INTO recruiter_pipeline_items(id,recruiter_user_id,candidate_name,candidate_email,role_title,pipeline_stage,candidate_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,'sourced',?,?,?)",
                       (item_id, user["id"], name, email or None, title, now, now, now))
        _audit(user["id"], "recruiter.candidate_added", "pipeline_item", item_id, "success")
        return jsonify({"data": {"id": item_id, "pipeline_stage": "sourced"}, "request_id": str(uuid.uuid4())}), 201

    @app.patch("/api/v1/recruiter/pipeline/<item_id>")
    @_require_user
    def core_recruiter_pipeline_update(item_id):
        user = _current_user()
        if user["role"] != "recruiter":
            return _json_error("FORBIDDEN", "Recruiter permission is required.", 403)
        data = request.get_json(silent=True) or {}
        stage = str(data.get("pipeline_stage", ""))
        if stage not in {"sourced", "contacted", "screening", "shortlisted", "interview", "offer", "hired", "rejected"}:
            return _json_error("VALIDATION_ERROR", "Choose a valid pipeline stage.", 400)
        with _connect() as db:
            cur = db.execute("UPDATE recruiter_pipeline_items SET pipeline_stage=?,updated_at=? WHERE id=? AND recruiter_user_id=?",
                             (stage, utc_now(), item_id, user["id"]))
            if cur.rowcount != 1:
                return _json_error("NOT_FOUND", "Candidate not found in your pipeline.", 404)
        _audit(user["id"], "recruiter.pipeline_stage_updated", "pipeline_item", item_id, "success", {"stage": stage})
        return jsonify({"data": {"updated": True, "pipeline_stage": stage}, "request_id": str(uuid.uuid4())})

    @app.get("/workspace/saved-jobs")
    @_require_user
    def core_saved_jobs_screen():
        user = _current_user()
        if user["role"] != "job_seeker":
            return redirect("/workspace")
        content = """<div id="saved" style="display:grid;gap:12px"><div class="empty">Loading saved jobs…</div></div>
        <div id="message" class="error" role="status"></div><div class="links"><a href="/workspace/jobs">Discover more jobs</a><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const root=document.getElementById("saved"),message=document.getElementById("message");
        async function load(){const r=await fetch("/api/v1/saved-jobs");const x=await r.json();root.innerHTML="";if(!r.ok){root.textContent=x.error?.message||"Unable to load saved jobs.";return;}
        if(!x.data.length){root.innerHTML='<div class="empty">You have not saved any jobs yet.</div>';return;}
        x.data.forEach(j=>{const el=document.createElement("article");el.style.cssText="padding:15px;border:1px solid #263852;border-radius:13px;background:#0d182a";const h=document.createElement("strong");h.textContent=j.title;const p=document.createElement("p");p.textContent=[j.organisation_name,j.location,j.work_mode].filter(Boolean).join(" · ");p.style.color="#9aabc3";const a=document.createElement("a");a.href="/workspace/jobs/"+encodeURIComponent(j.id);a.textContent="View job";a.style.color="#93baff";const b=document.createElement("button");b.textContent="Remove";b.style.cssText="width:auto;margin:12px 0 0;padding:9px 13px;background:#25354e";b.addEventListener("click",async()=>{const c=await fetch("/api/v1/auth/csrf").then(r=>r.json());const r=await fetch("/api/v1/jobs/"+encodeURIComponent(j.id)+"/save",{method:"DELETE",headers:{"X-CSRF-Token":c.data.csrf_token}});if(r.ok)load();else message.textContent="Could not remove saved job.";});el.append(h,p,a,b);root.append(el);});}
        load();
        """
        return _auth_page("Saved jobs", "Keep track of opportunities you want to revisit.", content, script)

    @app.get("/workspace/applications")
    @_require_user
    def core_applications_screen():
        user = _current_user()
        if user["role"] not in {"job_seeker", "employer", "admin"}:
            return redirect("/workspace")
        content = """<div id="applications" style="display:grid;gap:12px"><div class="empty">Loading applications…</div></div>
        <div id="message" class="error" role="status"></div><div class="links"><a href="/workspace">Back to workspace</a><a href="/workspace/jobs">Discover jobs</a></div>"""
        script = """const role=""" + json.dumps(user["role"]) + """;
        const root=document.getElementById("applications"),message=document.getElementById("message");
        async function csrf(){return (await fetch("/api/v1/auth/csrf").then(r=>r.json())).data.csrf_token;}
        async function load(){try{const r=await fetch("/api/v1/applications");const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Unable to load applications.");root.innerHTML="";
        if(!x.data.length){root.innerHTML='<div class="empty">No applications yet. Your application activity will appear here.</div>';return;}
        x.data.forEach(a=>{const el=document.createElement("article");el.style.cssText="padding:15px;border:1px solid #263852;border-radius:13px;background:#0d182a";
        const h=document.createElement("strong");h.textContent=a.title||"Application";const p=document.createElement("p");p.textContent=[a.organisation_name,a.applicant_name,a.status].filter(Boolean).join(" · ");p.style.color="#9aabc3";
        const d=document.createElement("small");d.textContent=new Date(a.applied_at).toLocaleString();d.style.color="#7186a6";el.append(h,p,d);
        if(role==="job_seeker"&&a.status!=="withdrawn"&&a.status!=="rejected"&&a.status!=="offer"){const b=document.createElement("button");b.textContent="Withdraw application";b.style.cssText="width:auto;margin-top:12px;padding:9px 13px;background:#25354e";b.addEventListener("click",async()=>{const t=await csrf();const r=await fetch("/api/v1/applications/"+encodeURIComponent(a.id)+"/withdraw",{method:"POST",headers:{"X-CSRF-Token":t}});const x=await r.json();message.textContent=r.ok?"Application withdrawn.":(x.error?.message||"Unable to withdraw.");load();});el.append(b);}
        if(role==="employer"||role==="admin"){const select=document.createElement("select");["reviewing","shortlisted","interview","rejected","offer"].forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v.replace("_"," ");if(v===a.status)o.selected=true;select.append(o);});const b=document.createElement("button");b.textContent="Update status";b.style.cssText="margin-top:10px";b.addEventListener("click",async()=>{const t=await csrf();const r=await fetch("/api/v1/applications/"+encodeURIComponent(a.id)+"/status",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":t},body:JSON.stringify({status:select.value})});const x=await r.json();message.textContent=r.ok?"Application status updated.":(x.error?.message||"Unable to update status.");load();});el.append(select,b);}
        if(role==="job_seeker"&&a.job_id){const link=document.createElement("a");link.href="/workspace/jobs/"+encodeURIComponent(a.job_id);link.textContent="View job";link.style.display="block";link.style.marginTop="9px";link.style.color="#93baff";el.append(link);}root.append(el);});
        }catch(e){message.textContent=e.message;root.innerHTML='<div class="empty">Application data is temporarily unavailable.</div>';}}
        load();
        """
        return _auth_page("Applications", "Track your submitted applications and their progress.", content, script)

    @app.get("/workspace/employer/jobs")
    @_require_user
    def core_employer_jobs_screen():
        user = _current_user()
        if user["role"] != "employer":
            return redirect("/workspace")
        content = """
        <form id="job-form"><h3>Create a job draft</h3><label>Job title</label><input name="title" maxlength="160" required>
        <label>Description (minimum 40 characters)</label><textarea name="description" rows="6" minlength="40" maxlength="20000" required></textarea>
        <label>Location</label><input name="location" maxlength="120">
        <label>Work mode</label><select name="work_mode"><option value="onsite">On-site</option><option value="hybrid">Hybrid</option><option value="remote">Remote</option></select>
        <label>Employment type</label><select name="employment_type"><option value="full_time">Full-time</option><option value="part_time">Part-time</option><option value="contract">Contract</option><option value="internship">Internship</option><option value="temporary">Temporary</option></select>
        <label>Minimum monthly salary (NGN)</label><input name="salary_min_ngn" type="number" min="0">
        <label>Maximum monthly salary (NGN)</label><input name="salary_max_ngn" type="number" min="0">
        <button id="create" type="submit">Save job draft</button></form>
        <div id="message" class="error" role="status"></div><h3 style="margin-top:25px">Your jobs</h3><div id="jobs" style="display:grid;gap:12px"><div class="empty">Loading jobs…</div></div>
        <div class="links"><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const form=document.getElementById("job-form"),message=document.getElementById("message"),root=document.getElementById("jobs");
        async function csrf(){return (await fetch("/api/v1/auth/csrf").then(r=>r.json())).data.csrf_token;}
        async function load(){const r=await fetch("/api/v1/jobs");const x=await r.json();root.innerHTML="";if(!r.ok){root.textContent=x.error?.message||"Unable to load jobs.";return;}if(!x.data.jobs.length){root.innerHTML='<div class="empty">You have not created any jobs yet.</div>';return;}
        x.data.jobs.forEach(j=>{const el=document.createElement("div");el.style.cssText="padding:14px;border:1px solid #263852;border-radius:13px;background:#0d182a";const h=document.createElement("strong");h.textContent=j.title;const p=document.createElement("p");p.textContent="Status: "+j.status+" · "+(j.location||"Location not set");p.style.color="#9aabc3";el.append(h,p);if(j.status==="draft"){const b=document.createElement("button");b.textContent="Publish";b.style.marginTop="8px";b.addEventListener("click",async()=>{b.disabled=true;const t=await csrf();const r=await fetch("/api/v1/jobs/"+encodeURIComponent(j.id)+"/publish",{method:"POST",headers:{"X-CSRF-Token":t}});const x=await r.json();message.textContent=r.ok?"Job published.":(x.error?.message||"Unable to publish.");await load();});el.append(b);}root.append(el);});}
        form.addEventListener("submit",async e=>{e.preventDefault();const b=document.getElementById("create"),d=Object.fromEntries(new FormData(form));b.disabled=true;message.textContent="";try{const t=await csrf();const r=await fetch("/api/v1/jobs",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":t},body:JSON.stringify(d)});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not save job.");message.textContent="Job saved as a draft. Organisation verification is required before publication.";form.reset();await load();}catch(x){message.textContent=x.message;}finally{b.disabled=false;}});load();
        """
        return _auth_page("Manage jobs", "Create drafts, review your job posts and publish after organisation verification.", content, script)

    @app.get("/workspace/cv-studio")
    @_require_user
    def core_cv_studio_screen():
        user = _current_user()
        if user["role"] != "job_seeker":
            return redirect("/workspace")
        content = """
        <div id="cv-list" style="display:grid;gap:8px;margin-bottom:20px"><div class="empty">Loading your CV library…</div></div>
        <form id="cv-form"><label>Document title</label><input name="title" maxlength="160" required placeholder="e.g. Software Developer CV">
        <label>CV content</label><textarea name="content_text" rows="14" maxlength="50000" placeholder="Add your professional summary, experience, education, skills and projects. Use clear section headings." required></textarea>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><button id="save" type="submit">Save CV</button><button id="new" type="button" style="background:#25354e">New CV</button></div></form>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><button id="improve" type="button" style="background:#315f9f">Improve with AI</button><button id="delete" type="button" style="background:#57303a">Delete CV</button></div>
        <div id="message" class="error" role="status"></div><div id="ai-result" style="display:none;border:1px solid #294266;border-radius:13px;padding:15px;margin-top:15px"><h3>AI suggestion</h3><pre id="ai-text" style="white-space:pre-wrap;font:13px/1.6 'DM Sans',sans-serif;color:#d5e1f1"></pre><button id="apply-ai" type="button">Use this suggestion</button></div>
        <div id="confirm" style="display:none;position:fixed;inset:0;z-index:10;background:#020617d9;place-items:center;padding:18px"><div style="width:min(100%,390px);border:1px solid #344968;border-radius:18px;background:#111d33;padding:22px">
        <div style="font-size:10px;letter-spacing:.16em;color:#8db8ff;font-weight:800">USING CREDITS</div><h2 style="font:700 19px Manrope;margin:8px 0 20px">CV improvement</h2>
        <div style="font-size:10px;letter-spacing:.13em;color:#91a3bd">DEBITING CREDITS</div><div id="debit" style="font:800 30px Manrope;margin:5px 0 18px">−25 Credits</div>
        <div style="display:flex;justify-content:space-between;color:#a8b9d1;font-size:12px;margin:8px 0"><span>Total credits</span><strong id="total">—</strong></div>
        <div style="display:flex;justify-content:space-between;color:#a8b9d1;font-size:12px;margin:8px 0"><span>Remaining credits</span><strong id="remaining">—</strong></div>
        <p style="font-size:12px;color:#9aabc3;line-height:1.55">Review this charge before the AI service processes your CV. Cancelling does not deduct credits.</p>
        <div style="display:flex;gap:10px"><button id="cancel" type="button" style="margin:0;background:#25354e">Cancel</button><button id="confirm-button" type="button" style="margin:0">Confirm</button></div></div></div>
        <div class="links"><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const list=document.getElementById("cv-list"),form=document.getElementById("cv-form"),msg=document.getElementById("message"),modal=document.getElementById("confirm"),resultBox=document.getElementById("ai-result");
        let currentId=null,pendingQuote=null,aiSuggestion="";
        async function csrf(){return (await fetch("/api/v1/auth/csrf").then(r=>r.json())).data.csrf_token;}
        async function load(){const r=await fetch("/api/v1/cvs");const x=await r.json();list.innerHTML="";if(!r.ok){list.textContent=x.error?.message||"Unable to load CVs.";return;}if(!x.data.length){list.innerHTML='<div class="empty">No CV documents yet. Create your first CV below.</div>';return;}
        x.data.forEach(cv=>{const b=document.createElement("button");b.type="button";b.textContent=cv.title+" · "+cv.document_status;b.style.cssText="margin:0;text-align:left;background:#14233b;border:1px solid #263852";b.addEventListener("click",()=>openCv(cv.id));list.append(b);});}
        async function openCv(id){const r=await fetch("/api/v1/cvs/"+encodeURIComponent(id));const x=await r.json();if(!r.ok){msg.textContent=x.error?.message||"Could not open CV.";return;}currentId=id;form.elements.title.value=x.data.title;form.elements.content_text.value=x.data.content_text||"";resultBox.style.display="none";msg.textContent="CV loaded.";}
        form.addEventListener("submit",async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(form)),token=await csrf();const url=currentId?"/api/v1/cvs/"+encodeURIComponent(currentId):"/api/v1/cvs";const method=currentId?"PATCH":"POST";const r=await fetch(url,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify(d)});const x=await r.json();if(!r.ok){msg.textContent=x.error?.message||"Could not save CV.";return;}currentId=x.data.id||currentId;msg.textContent="CV saved.";load();});
        document.getElementById("new").addEventListener("click",()=>{currentId=null;form.reset();resultBox.style.display="none";msg.textContent="New CV draft ready.";});
        document.getElementById("delete").addEventListener("click",async()=>{if(!currentId){msg.textContent="Select a saved CV first.";return;}const token=await csrf();const r=await fetch("/api/v1/cvs/"+encodeURIComponent(currentId),{method:"DELETE",headers:{"X-CSRF-Token":token}});const x=await r.json();if(!r.ok){msg.textContent=x.error?.message||"Could not delete CV.";return;}currentId=null;form.reset();msg.textContent="CV deleted.";load();});
        document.getElementById("improve").addEventListener("click",async()=>{if(!currentId){msg.textContent="Save or select a CV before requesting AI improvement.";return;}const token=await csrf();msg.textContent="Checking AI improvement cost…";const input={document_id:currentId,operation:"improve",content_text:form.elements.content_text.value};const r=await fetch("/api/v1/ai/quote",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify({action:"cv",input})});const x=await r.json();if(!r.ok){msg.textContent=x.error?.message||"Unable to quote AI improvement.";return;}pendingQuote=x.data;window.pendingCvInput=input;document.getElementById("debit").textContent="−"+x.data.credits_cost+" Credits";document.getElementById("total").textContent=Number(x.data.total_credits).toLocaleString();document.getElementById("remaining").textContent=Number(x.data.remaining_credits).toLocaleString();modal.style.display="grid";msg.textContent="";});
        document.getElementById("cancel").addEventListener("click",()=>{pendingQuote=null;modal.style.display="none";});
        document.getElementById("confirm-button").addEventListener("click",async()=>{if(!pendingQuote)return;const b=document.getElementById("confirm-button");b.disabled=true;b.textContent="Processing…";try{const token=await csrf();const r=await fetch("/api/v1/ai/actions/cv",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify({input:window.pendingCvInput,quote_id:pendingQuote.quote_id,quote_token:pendingQuote.quote_token})});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"AI improvement failed.");aiSuggestion=typeof x.data.result==="string"?x.data.result:JSON.stringify(x.data.result,null,2);document.getElementById("ai-text").textContent=aiSuggestion;resultBox.style.display="block";modal.style.display="none";pendingQuote=null;msg.textContent="AI suggestion ready. Review it before applying."; }catch(e){msg.textContent=e.message;}finally{b.disabled=false;b.textContent="Confirm";}});
        document.getElementById("apply-ai").addEventListener("click",()=>{if(!aiSuggestion)return;form.elements.content_text.value=aiSuggestion;msg.textContent="Suggestion placed in the editor. Save the CV to keep this change.";});
        load();
        """
        return _auth_page("CV Studio", "Create and manage your CV. Manual editing is free; AI improvements show their cost before confirmation.", content, script)

    @app.get("/ai-assistant")
    @_require_user
    def core_ai_assistant_screen():
        user = _current_user()
        if not user["onboarding_completed_at"]:
            return redirect("/onboarding")
        content = """
        <div id="chat" style="display:grid;gap:12px;min-height:180px;max-height:42vh;overflow:auto;padding:14px;border:1px solid #263852;border-radius:14px;background:#091222">
        <div style="color:#9aabc3;font-size:13px">Welcome. Tell me what career task you would like help with. I will show the credit cost before running an AI action.</div></div>
        <form id="chat-form"><label for="message-input">Your message</label><textarea id="message-input" rows="3" maxlength="8000" placeholder="Ask about your CV, job search or interview preparation…" required></textarea>
        <button id="send" type="submit">Continue</button><div id="error" class="error" role="alert"></div></form>
        <div id="confirm" style="display:none;position:fixed;inset:0;z-index:10;background:#020617d9;place-items:center;padding:18px">
        <div style="width:min(100%,390px);border:1px solid #344968;border-radius:18px;background:#111d33;padding:22px;box-shadow:0 25px 80px #000b">
        <div style="font-size:10px;letter-spacing:.16em;color:#8db8ff;font-weight:800">USING CREDITS</div>
        <h2 style="font:700 19px Manrope;margin:8px 0 20px">AI Assistant</h2>
        <div style="font-size:10px;letter-spacing:.13em;color:#91a3bd">DEBITING CREDITS</div>
        <div id="debit" style="font:800 30px Manrope;margin:5px 0 18px">−5 Credits</div>
        <div style="display:flex;justify-content:space-between;color:#a8b9d1;font-size:12px;margin:8px 0"><span>Total credits</span><strong id="total">—</strong></div>
        <div style="display:flex;justify-content:space-between;color:#a8b9d1;font-size:12px;margin:8px 0"><span>Remaining credits</span><strong id="remaining">—</strong></div>
        <p style="font-size:12px;color:#9aabc3;line-height:1.55;margin:17px 0">Confirm to run this AI request. Cancelling will not deduct credits.</p>
        <div style="display:flex;gap:10px"><button id="cancel" type="button" style="margin:0;background:#25354e">Cancel</button><button id="confirm-button" type="button" style="margin:0">Confirm</button></div>
        </div></div>
        <div class="links"><a href="/workspace">Back to workspace</a><a href="/wallet">Buy credits</a></div>"""
        script = """
        const form=document.getElementById("chat-form"),input=document.getElementById("message-input"),send=document.getElementById("send"),error=document.getElementById("error"),chat=document.getElementById("chat"),modal=document.getElementById("confirm"),confirmBtn=document.getElementById("confirm-button");
        let pendingQuote=null,pendingInput=null;
        function csrf(){return fetch("/api/v1/auth/csrf").then(r=>r.json()).then(x=>x.data.csrf_token);}
        function addMessage(label,text){const d=document.createElement("div");d.style.cssText="padding:11px 12px;border-radius:11px;background:#14233b;color:#e4edfb;font-size:13px;line-height:1.6;white-space:pre-wrap";const b=document.createElement("b");b.textContent=label;const p=document.createElement("div");p.textContent=text;d.append(b,p);chat.append(d);chat.scrollTop=chat.scrollHeight;}
        form.addEventListener("submit",async ev=>{ev.preventDefault();const message=input.value.trim();if(!message)return;send.disabled=true;send.textContent="Checking cost…";error.textContent="";
        try{const token=await csrf();const r=await fetch("/api/v1/ai/quote",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify({action:"chat",input:{message}})});const x=await r.json();if(!r.ok){if(r.status===402)throw new Error("You need "+x.error.required+" credits but have "+x.error.available+". Visit your wallet to buy credits.");throw new Error(x.error?.message||"Could not prepare this AI request.");}
        pendingQuote=x.data;pendingInput={message};document.getElementById("debit").textContent="−"+x.data.credits_cost+" Credits";document.getElementById("total").textContent=Number(x.data.total_credits).toLocaleString();document.getElementById("remaining").textContent=Number(x.data.remaining_credits).toLocaleString();modal.style.display="grid";
        }catch(e){error.textContent=e.message;}finally{send.disabled=false;send.textContent="Continue";}});
        document.getElementById("cancel").addEventListener("click",()=>{pendingQuote=null;pendingInput=null;modal.style.display="none";});
        confirmBtn.addEventListener("click",async()=>{if(!pendingQuote)return;confirmBtn.disabled=true;confirmBtn.textContent="Processing…";error.textContent="";
        try{const token=await csrf();const r=await fetch("/api/v1/ai/actions/chat",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:JSON.stringify({input:pendingInput,quote_id:pendingQuote.quote_id,quote_token:pendingQuote.quote_token})});const x=await r.json();modal.style.display="none";if(!r.ok)throw new Error(x.error?.message||"The AI request could not be completed.");addMessage("You",pendingInput.message);addMessage("Career Agency AI",JSON.stringify(x.data.result));input.value="";pendingQuote=null;pendingInput=null;
        }catch(e){error.textContent=e.message;}finally{confirmBtn.disabled=false;confirmBtn.textContent="Confirm";}});
        """
        return _auth_page("AI assistant", "Get career support with transparent, confirmed credit usage.", content, script)

    @app.get("/wallet")
    @_require_user
    def core_wallet_screen():
        content = """
        <div style="padding:20px;border:1px solid #294266;border-radius:16px;background:#101e34;margin:18px 0">
        <div style="font-size:11px;letter-spacing:.12em;color:#93baff">AVAILABLE CAREER CREDITS</div>
        <div id="balance" style="font:800 34px Manrope;margin-top:8px">—</div>
        <div style="color:#91a3bd;font-size:12px">Prepaid credits · NGN</div></div>
        <h3>Buy Career Credits</h3><div id="packages" style="display:grid;gap:12px"><div class="error">Loading available packages…</div></div>
        <h3 style="margin-top:28px">Transaction history</h3><div id="ledger" style="display:grid;gap:9px"><div class="error">Loading transactions…</div></div>
        <div id="message" class="error" role="alert"></div>
        <div class="links"><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const balance=document.getElementById("balance"),packages=document.getElementById("packages"),ledger=document.getElementById("ledger"),message=document.getElementById("message");
        const money=kobo=>"₦"+(Number(kobo)/100).toLocaleString("en-NG",{maximumFractionDigits:0});
        Promise.all([fetch("/api/v1/wallet").then(r=>r.json()),fetch("/api/v1/credit-packages").then(r=>r.json()),fetch("/api/v1/wallet/ledger").then(r=>r.json())]).then(([w,p,l])=>{
        balance.textContent=Number(w.data.credits).toLocaleString("en-NG");
        const items=p.data.packages||[];
        packages.innerHTML=items.length?items.map(x=>'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:15px;border:1px solid #263852;border-radius:13px;background:#0d182a"><div><strong>'+Number(x.credits).toLocaleString()+' Credits</strong><div style="color:#91a3bd;font-size:12px;margin-top:4px">'+money(x.price_kobo)+'</div></div><button data-package="'+x.id+'" style="width:auto;padding:10px 16px;margin:0">Buy</button></div>').join(""):'<div class="empty">Credit packages are temporarily unavailable while the approved pricing catalogue is being finalised. No purchase can be made yet.</div>';
        ledger.innerHTML=l.data.length?l.data.map(x=>'<div style="display:flex;justify-content:space-between;gap:10px;padding:13px;border:1px solid #21324d;border-radius:12px"><div><strong style="font-size:13px">'+x.description+'</strong><div style="color:#91a3bd;font-size:11px;margin-top:4px">'+new Date(x.created_at).toLocaleString()+'</div></div><div style="text-align:right"><strong>'+((x.delta>0?"+":"")+Number(x.delta).toLocaleString())+'</strong><div style="color:#91a3bd;font-size:10px">Balance '+Number(x.balance_after).toLocaleString()+'</div></div></div>').join(""):'<div class="empty">Your wallet transactions will appear here.</div>';
        packages.querySelectorAll("[data-package]").forEach(btn=>btn.addEventListener("click",async()=>{btn.disabled=true;btn.textContent="Opening…";message.textContent="";
        try{const c=await fetch("/api/v1/auth/csrf").then(r=>r.json());const r=await fetch("/api/v1/payments/paystack/initialize",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify({package_id:btn.dataset.package})});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not start payment.");location.href=x.data.authorization_url;
        }catch(e){message.textContent=e.message;btn.disabled=false;btn.textContent="Buy";}}));
        }).catch(e=>{message.textContent=e.message||"Wallet data is temporarily unavailable.";packages.innerHTML='<div class="empty">Please refresh to try again.</div>';});
        """
        return _auth_page("Career Credits wallet", "Manage your prepaid credits and review every transaction.", content, script)

    @app.get("/payments/return")
    @_require_user
    def core_payment_return_screen():
        content = """
        <div id="payment-status" class="empty">Checking your payment status…</div>
        <button id="check" type="button">Check payment status</button>
        <div class="links"><a href="/wallet">Return to wallet</a></div>"""
        script = """
        const status=document.getElementById("payment-status"),button=document.getElementById("check"),reference=new URLSearchParams(location.search).get("reference");
        async function check(){if(!reference){status.textContent="Payment reference is missing.";return;}button.disabled=true;
        try{const r=await fetch("/api/v1/payments/"+encodeURIComponent(reference));const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Unable to check payment.");
        const p=x.data;if(p.status==="success"||p.status==="credited"){status.textContent="Payment confirmed. Your wallet will show the updated balance."; }else if(p.status==="pending"||p.status==="initialized"){status.textContent="Payment is still being confirmed. Credits are added only after Paystack's verified webhook."; }else{status.textContent="Payment status: "+p.status+". Contact support if you believe this is incorrect.";}
        }catch(e){status.textContent=e.message;}finally{button.disabled=false;}}
        button.addEventListener("click",check);check();
        """
        return _auth_page("Payment status", "Your payment is being checked securely.", content, script)

    @app.get("/notifications")
    @_require_user
    def core_notifications_screen():
        content = """<div id="notifications" style="display:grid;gap:10px"><div class="empty">Loading notifications…</div></div>
        <div id="message" class="error" role="status"></div><div class="links"><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const root=document.getElementById("notifications"),msg=document.getElementById("message");
        async function csrf(){return (await fetch("/api/v1/auth/csrf").then(r=>r.json())).data.csrf_token;}
        async function load(){const r=await fetch("/api/v1/notifications");const x=await r.json();root.innerHTML="";if(!r.ok){msg.textContent=x.error?.message||"Unable to load notifications.";return;}
        if(!x.data.length){root.innerHTML='<div class="empty">You are all caught up. New updates will appear here.</div>';return;}
        x.data.forEach(n=>{const el=document.createElement("article");el.style.cssText="padding:14px;border:1px solid #263852;border-radius:13px;background:#0d182a";const h=document.createElement("strong");h.textContent=n.title;const p=document.createElement("p");p.textContent=n.body;p.style.color="#9aabc3";const d=document.createElement("small");d.textContent=new Date(n.created_at).toLocaleString();d.style.color="#7186a6";el.append(h,p,d);
        if(!n.read_at){const b=document.createElement("button");b.textContent="Mark as read";b.style.cssText="width:auto;margin-top:10px;padding:9px 13px";b.addEventListener("click",async()=>{const t=await csrf();const r=await fetch("/api/v1/notifications/"+encodeURIComponent(n.id)+"/read",{method:"POST",headers:{"X-CSRF-Token":t}});if(r.ok)load();else msg.textContent="Could not update notification.";});el.append(b);}if(n.target_url){const a=document.createElement("a");a.href=n.target_url;a.textContent="Open";a.style.display="block";a.style.marginTop="9px";el.append(a);}root.append(el);});}
        load();
        """
        return _auth_page("Notifications", "Important updates about your career activity and account.", content, script)

    @app.get("/api/v1/notifications")
    @_require_user
    def core_notifications_list():
        user = _current_user()
        limit = min(max(request.args.get("limit", default=50, type=int), 1), 100)
        with _connect() as db:
            rows = db.execute("SELECT id,category,title,body,target_url,read_at,created_at FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                              (user["id"], limit)).fetchall()
        return jsonify({"data": [dict(row) for row in rows], "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/notifications/<notification_id>/read")
    @_require_user
    def core_notification_read(notification_id):
        user = _current_user()
        with _connect() as db:
            cur = db.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=? AND read_at IS NULL",
                             (utc_now(), notification_id, user["id"]))
            if cur.rowcount == 0 and not db.execute("SELECT 1 FROM notifications WHERE id=? AND user_id=?",
                                                    (notification_id, user["id"])).fetchone():
                return _json_error("NOT_FOUND", "Notification not found.", 404)
        return jsonify({"data": {"read": True}, "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/notifications/read-all")
    @_require_user
    def core_notifications_read_all():
        user = _current_user()
        with _connect() as db:
            cur = db.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",
                             (utc_now(), user["id"]))
        return jsonify({"data": {"updated": cur.rowcount}, "request_id": str(uuid.uuid4())})

    @app.get("/profile")
    @_require_user
    def core_profile_screen():
        content = """
        <form id="profile-form">
        <label>Full name</label><input name="full_name" autocomplete="name" maxlength="120" required>
        <label>Email address</label><input name="email" type="email" disabled>
        <label>Phone number</label><input name="phone" type="tel" maxlength="30">
        <label>Country</label><input name="country" maxlength="100" required>
        <label>City or state</label><input name="city" maxlength="100">
        <label>Professional headline</label><input name="headline" maxlength="160">
        <label>Professional summary</label><textarea name="professional_summary" maxlength="3000" rows="5"></textarea>
        <label>Years of experience</label><input name="years_experience" type="number" min="0" max="60">
        <button id="save" type="submit">Save profile</button><div id="message" class="error" role="status"></div></form>
        <div class="links"><a href="/workspace">Back to workspace</a></div>"""
        script = """
        const f=document.getElementById("profile-form"),b=document.getElementById("save"),m=document.getElementById("message");
        fetch("/api/v1/profile").then(async r=>{const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Unable to load profile.");const p=x.data;
        for(const key of ["full_name","email","phone","country","city","headline","professional_summary","years_experience"]){if(p[key]!==null&&p[key]!==undefined)f.elements[key].value=p[key];}
        }).catch(e=>m.textContent=e.message);
        f.addEventListener("submit",async ev=>{ev.preventDefault();const d=Object.fromEntries(new FormData(f));d.years_experience=Number(d.years_experience||0);b.disabled=true;b.textContent="Saving…";m.textContent="";
        try{const c=await fetch("/api/v1/auth/csrf").then(x=>x.json());const r=await fetch("/api/v1/profile",{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify(d)});const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Unable to save profile.");m.textContent="Your profile has been saved.";
        }catch(e){m.textContent=e.message;}finally{b.disabled=false;b.textContent="Save profile";}});
        """
        return _auth_page("My profile", "Keep your professional information accurate and up to date.", content, script)

    @app.get("/api/v1/profile")
    @_require_user
    def core_profile_get():
        user = _current_user()
        with _connect() as db:
            profile = db.execute("SELECT phone,country,city,headline,professional_summary,years_experience FROM user_profiles WHERE user_id=?",
                                 (user["id"],)).fetchone()
        data = {"full_name": user["full_name"], "email": user["email"], "role": user["role"]}
        if profile:
            data.update(dict(profile))
        return jsonify({"data": data, "request_id": str(uuid.uuid4())})

    @app.patch("/api/v1/profile")
    @_require_user
    def core_profile_update():
        user = _current_user()
        data = request.get_json(silent=True) or {}
        full_name = str(data.get("full_name", user["full_name"])).strip()
        if not full_name or len(full_name) > 120:
            return _json_error("VALIDATION_ERROR", "Full name must contain 1 to 120 characters.", 400)
        country = str(data.get("country", "")).strip()
        if not country or len(country) > 100:
            return _json_error("VALIDATION_ERROR", "Country is required.", 400)
        try:
            years = int(data.get("years_experience", 0) or 0)
        except (TypeError, ValueError):
            return _json_error("VALIDATION_ERROR", "Years of experience must be a whole number.", 400)
        if years < 0 or years > 60:
            return _json_error("VALIDATION_ERROR", "Years of experience must be between 0 and 60.", 400)
        now = utc_now()
        with _connect() as db:
            db.execute("UPDATE users SET full_name=?,updated_at=? WHERE id=?", (full_name, now, user["id"]))
            db.execute("""INSERT INTO user_profiles(user_id,phone,country,city,headline,professional_summary,years_experience,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone,country=excluded.country,city=excluded.city,
                          headline=excluded.headline,professional_summary=excluded.professional_summary,
                          years_experience=excluded.years_experience,updated_at=excluded.updated_at""",
                       (user["id"], str(data.get("phone", "")).strip()[:30] or None, country,
                        str(data.get("city", "")).strip()[:100] or None,
                        str(data.get("headline", "")).strip()[:160] or None,
                        str(data.get("professional_summary", "")).strip()[:3000] or None, years, now, now))
        _audit(user["id"], "profile.updated", "user", user["id"], "success")
        return jsonify({"data": {"saved": True}, "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/jobs")
    @_require_user
    def core_jobs_list():
        user = _current_user()
        q = str(request.args.get("q", "")).strip()[:120]
        location = str(request.args.get("location", "")).strip()[:120]
        work_mode = str(request.args.get("work_mode", "")).strip()
        employment_type = str(request.args.get("employment_type", "")).strip()
        limit = min(max(request.args.get("limit", default=20, type=int), 1), 50)
        offset = max(request.args.get("offset", default=0, type=int), 0)
        clauses, params = [], []
        if user["role"] == "employer":
            clauses.append("j.employer_user_id=?")
            params.append(user["id"])
        elif user["role"] != "admin":
            clauses.append("j.status='published'")
        if q:
            clauses.append("(j.title LIKE ? OR j.description LIKE ?)")
            params.extend(["%" + q + "%", "%" + q + "%"])
        if location:
            clauses.append("j.location LIKE ?")
            params.append("%" + location + "%")
        if work_mode:
            clauses.append("j.work_mode=?")
            params.append(work_mode)
        if employment_type:
            clauses.append("j.employment_type=?")
            params.append(employment_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with _connect() as db:
            rows = db.execute("""SELECT j.id,j.title,j.description,j.location,j.work_mode,j.employment_type,
                                 j.salary_min_ngn,j.salary_max_ngn,j.status,j.published_at,j.created_at,
                                 o.name AS organisation_name FROM jobs j
                                 LEFT JOIN organizations o ON o.id=j.organization_id""" + where +
                               " ORDER BY COALESCE(j.published_at,j.created_at) DESC LIMIT ? OFFSET ?",
                               tuple(params + [limit, offset])).fetchall()
        return jsonify({"data": {"jobs": [dict(row) for row in rows], "limit": limit, "offset": offset},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/jobs")
    @_require_user
    def core_job_create():
        user = _current_user()
        if user["role"] != "employer":
            return _json_error("FORBIDDEN", "Only employer accounts can create jobs.", 403)
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        location = str(data.get("location", "")).strip()
        work_mode = str(data.get("work_mode", "onsite")).lower()
        employment_type = str(data.get("employment_type", "full_time")).lower()
        if not title or len(title) > 160 or len(description) < 40 or len(description) > 20000:
            return _json_error("VALIDATION_ERROR", "Provide a job title and a description of at least 40 characters.", 400)
        if work_mode not in {"remote", "hybrid", "onsite"}:
            return _json_error("VALIDATION_ERROR", "Choose a valid work mode.", 400)
        if employment_type not in {"full_time", "part_time", "contract", "internship", "temporary"}:
            return _json_error("VALIDATION_ERROR", "Choose a valid employment type.", 400)
        def optional_int(key):
            value = data.get(key)
            if value in (None, ""):
                return None
            try:
                parsed = int(value)
                return parsed if parsed >= 0 else None
            except (TypeError, ValueError):
                return None
        salary_min, salary_max = optional_int("salary_min_ngn"), optional_int("salary_max_ngn")
        if salary_min is not None and salary_max is not None and salary_max < salary_min:
            return _json_error("VALIDATION_ERROR", "Maximum salary cannot be lower than minimum salary.", 400)
        with _connect() as db:
            employer = db.execute("SELECT organization_id FROM employer_profiles WHERE user_id=?", (user["id"],)).fetchone()
            if not employer or not employer["organization_id"]:
                return _json_error("ONBOARDING_INCOMPLETE", "Complete employer organisation setup first.", 400)
            job_id, now = str(uuid.uuid4()), utc_now()
            db.execute("""INSERT INTO jobs(id,employer_user_id,organization_id,title,description,location,work_mode,
                          employment_type,salary_min_ngn,salary_max_ngn,status,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,'draft',?,?)""",
                       (job_id, user["id"], employer["organization_id"], title, description, location or None,
                        work_mode, employment_type, salary_min, salary_max, now, now))
        _audit(user["id"], "job.created", "job", job_id, "success")
        return jsonify({"data": {"job_id": job_id, "status": "draft"}, "request_id": str(uuid.uuid4())}), 201

    @app.get("/api/v1/jobs/<job_id>")
    @_require_user
    def core_job_detail(job_id):
        user = _current_user()
        with _connect() as db:
            job = db.execute("""SELECT j.*,o.name AS organisation_name FROM jobs j
                                LEFT JOIN organizations o ON o.id=j.organization_id WHERE j.id=?""",
                             (job_id,)).fetchone()
        if not job:
            return _json_error("NOT_FOUND", "Job not found.", 404)
        if job["status"] != "published" and user["role"] != "admin" and job["employer_user_id"] != user["id"]:
            return _json_error("NOT_FOUND", "Job not found.", 404)
        return jsonify({"data": dict(job), "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/jobs/<job_id>/publish")
    @_require_user
    def core_job_publish(job_id):
        user = _current_user()
        if user["role"] not in {"employer", "admin"}:
            return _json_error("FORBIDDEN", "Employer permission is required.", 403)
        with _connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or (user["role"] != "admin" and job["employer_user_id"] != user["id"]):
                return _json_error("NOT_FOUND", "Job not found.", 404)
            org = db.execute("SELECT verification_status FROM organizations WHERE id=?", (job["organization_id"],)).fetchone()
            if not org or org["verification_status"] != "verified":
                return _json_error("ORGANISATION_NOT_VERIFIED", "Your organisation must be verified before publishing jobs.", 403)
            now = utc_now()
            db.execute("UPDATE jobs SET status='published',published_at=?,updated_at=? WHERE id=?", (now, now, job_id))
        _audit(user["id"], "job.published", "job", job_id, "success")
        return jsonify({"data": {"published": True}, "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/cvs")
    @_require_user
    def core_cv_list():
        user = _current_user()
        with _connect() as db:
            rows = db.execute("SELECT id,title,document_status,created_at,updated_at FROM cv_documents WHERE user_id=? ORDER BY updated_at DESC",
                              (user["id"],)).fetchall()
        return jsonify({"data": [dict(row) for row in rows], "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/cvs")
    @_require_user
    def core_cv_create():
        user = _current_user()
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        content = str(data.get("content_text", ""))
        if not title or len(title) > 160 or len(content) > 50000:
            return _json_error("VALIDATION_ERROR", "Provide a CV title and keep document content under 50,000 characters.", 400)
        cv_id, now = str(uuid.uuid4()), utc_now()
        with _connect() as db:
            db.execute("INSERT INTO cv_documents(id,user_id,title,content_text,document_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (cv_id, user["id"], title, content, "draft", now, now))
        _audit(user["id"], "cv.created", "cv_document", cv_id, "success")
        return jsonify({"data": {"id": cv_id, "title": title, "document_status": "draft"},
                        "request_id": str(uuid.uuid4())}), 201

    @app.get("/api/v1/cvs/<cv_id>")
    @_require_user
    def core_cv_get(cv_id):
        user = _current_user()
        with _connect() as db:
            row = db.execute("SELECT id,title,content_text,document_status,created_at,updated_at FROM cv_documents WHERE id=? AND user_id=?",
                             (cv_id, user["id"])).fetchone()
        if not row:
            return _json_error("NOT_FOUND", "CV document not found.", 404)
        return jsonify({"data": dict(row), "request_id": str(uuid.uuid4())})

    @app.patch("/api/v1/cvs/<cv_id>")
    @_require_user
    def core_cv_update(cv_id):
        user = _current_user()
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        content = str(data.get("content_text", ""))
        if not title or len(title) > 160 or len(content) > 50000:
            return _json_error("VALIDATION_ERROR", "Provide a CV title and keep document content under 50,000 characters.", 400)
        with _connect() as db:
            cur = db.execute("UPDATE cv_documents SET title=?,content_text=?,updated_at=? WHERE id=? AND user_id=?",
                             (title, content, utc_now(), cv_id, user["id"]))
            if cur.rowcount != 1:
                return _json_error("NOT_FOUND", "CV document not found.", 404)
        _audit(user["id"], "cv.updated", "cv_document", cv_id, "success")
        return jsonify({"data": {"saved": True}, "request_id": str(uuid.uuid4())})

    @app.delete("/api/v1/cvs/<cv_id>")
    @_require_user
    def core_cv_delete(cv_id):
        user = _current_user()
        with _connect() as db:
            cur = db.execute("DELETE FROM cv_documents WHERE id=? AND user_id=?", (cv_id, user["id"]))
            if cur.rowcount != 1:
                return _json_error("NOT_FOUND", "CV document not found.", 404)
        _audit(user["id"], "cv.deleted", "cv_document", cv_id, "success")
        return jsonify({"data": {"deleted": True}, "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/saved-jobs")
    @_require_user
    def core_saved_jobs_list():
        user = _current_user()
        if user["role"] != "job_seeker":
            return _json_error("FORBIDDEN", "Only job seekers can view saved jobs.", 403)
        with _connect() as db:
            rows = db.execute("""SELECT j.id,j.title,j.location,j.work_mode,j.employment_type,
                                 j.published_at,o.name AS organisation_name
                                 FROM saved_jobs s JOIN jobs j ON j.id=s.job_id
                                 LEFT JOIN organizations o ON o.id=j.organization_id
                                 WHERE s.user_id=? AND j.status='published'
                                 ORDER BY s.created_at DESC""", (user["id"],)).fetchall()
        return jsonify({"data": [dict(row) for row in rows], "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/jobs/<job_id>/save")
    @_require_user
    def core_job_save(job_id):
        user = _current_user()
        if user["role"] != "job_seeker":
            return _json_error("FORBIDDEN", "Only job seekers can save jobs.", 403)
        with _connect() as db:
            if not db.execute("SELECT 1 FROM jobs WHERE id=? AND status='published'", (job_id,)).fetchone():
                return _json_error("NOT_FOUND", "Job not found.", 404)
            db.execute("INSERT OR IGNORE INTO saved_jobs(user_id,job_id,created_at) VALUES(?,?,?)",
                       (user["id"], job_id, utc_now()))
        return jsonify({"data": {"saved": True}, "request_id": str(uuid.uuid4())})

    @app.delete("/api/v1/jobs/<job_id>/save")
    @_require_user
    def core_job_unsave(job_id):
        user = _current_user()
        if user["role"] != "job_seeker":
            return _json_error("FORBIDDEN", "Only job seekers can manage saved jobs.", 403)
        with _connect() as db:
            db.execute("DELETE FROM saved_jobs WHERE user_id=? AND job_id=?", (user["id"], job_id))
        return jsonify({"data": {"saved": False}, "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/jobs/<job_id>/apply")
    @_require_user
    def core_job_apply(job_id):
        user = _current_user()
        if user["role"] != "job_seeker":
            return _json_error("FORBIDDEN", "Only job seekers can apply to jobs.", 403)
        data = request.get_json(silent=True) or {}
        cv_id = str(data.get("cv_document_id", "")).strip() or None
        cover = str(data.get("cover_letter", "")).strip()
        if len(cover) > 5000:
            return _json_error("VALIDATION_ERROR", "Cover letter must not exceed 5000 characters.", 400)
        with _connect() as db:
            if not db.execute("SELECT 1 FROM jobs WHERE id=? AND status='published'", (job_id,)).fetchone():
                return _json_error("NOT_FOUND", "This job is not available for applications.", 404)
            if cv_id and not db.execute("SELECT 1 FROM cv_documents WHERE id=? AND user_id=?", (cv_id, user["id"])).fetchone():
                return _json_error("INVALID_CV", "Choose a CV from your own document library.", 400)
            if db.execute("SELECT 1 FROM applications WHERE job_id=? AND applicant_user_id=?", (job_id, user["id"])).fetchone():
                return _json_error("ALREADY_APPLIED", "You have already applied to this job.", 409)
            application_id, now = str(uuid.uuid4()), utc_now()
            db.execute("""INSERT INTO applications(id,job_id,applicant_user_id,cv_document_id,cover_letter,status,applied_at,updated_at)
                          VALUES(?,?,?,?,?,'submitted',?,?)""",
                       (application_id, job_id, user["id"], cv_id, cover or None, now, now))
        _audit(user["id"], "job.application_submitted", "application", application_id, "success")
        return jsonify({"data": {"application_id": application_id, "status": "submitted"},
                        "request_id": str(uuid.uuid4())}), 201

    @app.get("/api/v1/applications")
    @_require_user
    def core_applications_list():
        user = _current_user()
        limit = min(max(request.args.get("limit", default=30, type=int), 1), 100)
        with _connect() as db:
            if user["role"] == "job_seeker":
                rows = db.execute("""SELECT a.id,a.status,a.applied_at,a.updated_at,j.id AS job_id,j.title,j.location,
                                     o.name AS organisation_name FROM applications a JOIN jobs j ON j.id=a.job_id
                                     LEFT JOIN organizations o ON o.id=j.organization_id
                                     WHERE a.applicant_user_id=? ORDER BY a.applied_at DESC LIMIT ?""",
                                  (user["id"], limit)).fetchall()
            elif user["role"] == "employer":
                rows = db.execute("""SELECT a.id,a.status,a.applied_at,a.updated_at,j.id AS job_id,j.title,
                                     u.full_name AS applicant_name FROM applications a JOIN jobs j ON j.id=a.job_id
                                     JOIN users u ON u.id=a.applicant_user_id WHERE j.employer_user_id=?
                                     ORDER BY a.applied_at DESC LIMIT ?""", (user["id"], limit)).fetchall()
            elif user["role"] == "admin":
                rows = db.execute("""SELECT a.id,a.status,a.applied_at,a.updated_at,j.id AS job_id,j.title,
                                     u.full_name AS applicant_name FROM applications a JOIN jobs j ON j.id=a.job_id
                                     JOIN users u ON u.id=a.applicant_user_id ORDER BY a.applied_at DESC LIMIT ?""",
                                  (limit,)).fetchall()
            else:
                rows = []
        return jsonify({"data": [dict(row) for row in rows], "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/applications/<application_id>/status")
    @_require_user
    def core_application_status(application_id):
        user = _current_user()
        if user["role"] not in {"employer", "admin"}:
            return _json_error("FORBIDDEN", "Employer permission is required.", 403)
        data = request.get_json(silent=True) or {}
        status = str(data.get("status", ""))
        if status not in {"reviewing", "shortlisted", "interview", "rejected", "offer"}:
            return _json_error("VALIDATION_ERROR", "Choose a valid application status.", 400)
        with _connect() as db:
            row = db.execute("SELECT a.id,j.employer_user_id FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?",
                             (application_id,)).fetchone()
            if not row or (user["role"] != "admin" and row["employer_user_id"] != user["id"]):
                return _json_error("NOT_FOUND", "Application not found.", 404)
            db.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (status, utc_now(), application_id))
        _audit(user["id"], "application.status_updated", "application", application_id, "success", {"status": status})
        return jsonify({"data": {"updated": True, "status": status}, "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/applications/<application_id>/withdraw")
    @_require_user
    def core_application_withdraw(application_id):
        user = _current_user()
        if user["role"] != "job_seeker":
            return _json_error("FORBIDDEN", "Only the applicant can withdraw an application.", 403)
        with _connect() as db:
            row = db.execute("SELECT id,status FROM applications WHERE id=? AND applicant_user_id=?",
                             (application_id, user["id"])).fetchone()
            if not row:
                return _json_error("NOT_FOUND", "Application not found.", 404)
            if row["status"] in {"rejected", "offer", "withdrawn"}:
                return _json_error("INVALID_TRANSITION", "This application can no longer be withdrawn.", 409)
            db.execute("UPDATE applications SET status='withdrawn',updated_at=? WHERE id=?", (utc_now(), application_id))
        return jsonify({"data": {"withdrawn": True}, "request_id": str(uuid.uuid4())})

    @app.get("/api/v1/dashboard")
    @_require_user
    def core_dashboard():
        user = _current_user()
        uid = user["id"]
        metrics = {}
        with _connect() as db:
            unread = db.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND read_at IS NULL", (uid,)).fetchone()["n"]
            metrics["unread_notifications"] = int(unread)
            if user["role"] == "job_seeker":
                metrics["applications"] = int(db.execute("SELECT COUNT(*) AS n FROM applications WHERE applicant_user_id=?", (uid,)).fetchone()["n"])
                metrics["saved_jobs"] = int(db.execute("SELECT COUNT(*) AS n FROM saved_jobs WHERE user_id=?", (uid,)).fetchone()["n"])
                metrics["cv_documents"] = int(db.execute("SELECT COUNT(*) AS n FROM cv_documents WHERE user_id=?", (uid,)).fetchone()["n"])
                metrics["upcoming_interviews"] = int(db.execute("""SELECT COUNT(*) AS n FROM interviews i
                    JOIN applications a ON a.id=i.application_id
                    WHERE a.applicant_user_id=? AND i.status='scheduled' AND i.scheduled_at>?""", (uid, utc_now())).fetchone()["n"])
            elif user["role"] == "employer":
                metrics["active_jobs"] = int(db.execute("SELECT COUNT(*) AS n FROM jobs WHERE employer_user_id=? AND status='published'", (uid,)).fetchone()["n"])
                metrics["total_jobs"] = int(db.execute("SELECT COUNT(*) AS n FROM jobs WHERE employer_user_id=?", (uid,)).fetchone()["n"])
                metrics["applicants"] = int(db.execute("""SELECT COUNT(*) AS n FROM applications a JOIN jobs j ON j.id=a.job_id
                    WHERE j.employer_user_id=?""", (uid,)).fetchone()["n"])
                metrics["upcoming_interviews"] = int(db.execute("""SELECT COUNT(*) AS n FROM interviews i
                    JOIN applications a ON a.id=i.application_id JOIN jobs j ON j.id=a.job_id
                    WHERE j.employer_user_id=? AND i.status='scheduled' AND i.scheduled_at>?""", (uid, utc_now())).fetchone()["n"])
            elif user["role"] == "recruiter":
                metrics["pipeline_candidates"] = int(db.execute("SELECT COUNT(*) AS n FROM recruiter_pipeline_items WHERE recruiter_user_id=?", (uid,)).fetchone()["n"])
                rows = db.execute("SELECT pipeline_stage,COUNT(*) AS n FROM recruiter_pipeline_items WHERE recruiter_user_id=? GROUP BY pipeline_stage", (uid,)).fetchall()
                metrics["pipeline_by_stage"] = {row["pipeline_stage"]: int(row["n"]) for row in rows}
            elif user["role"] == "admin":
                metrics["users"] = int(db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])
                metrics["jobs"] = int(db.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])
                metrics["applications"] = int(db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"])
                metrics["pending_employers"] = int(db.execute("SELECT COUNT(*) AS n FROM organizations WHERE verification_status='pending'").fetchone()["n"])
        return jsonify({"data": {"role": user["role"], "full_name": user["full_name"],
                                 "credits": int(user["credits"]), "metrics": metrics},
                        "request_id": str(uuid.uuid4())})

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
        role = user["role"]
        role_names = {"job_seeker": "Job Seeker", "employer": "Employer", "recruiter": "Recruiter", "admin": "Administrator"}
        role_label = role_names.get(role, "Career Agency")
        nav_by_role = {
            "job_seeker": [("Overview", "dashboard"), ("Discover jobs", "jobs"), ("My applications", "applications"),
                           ("Saved jobs", "saved-jobs"), ("CV Studio", "cv-studio"), ("AI assistant", "ai-assistant"),
                           ("Interview preparation", "interviews"), ("Career roadmap", "career-roadmap")],
            "employer": [("Overview", "dashboard"), ("My jobs", "jobs"), ("Applicants", "applicants"),
                         ("Find candidates", "candidates"), ("Interviews", "interviews"), ("Team", "team"),
                         ("Analytics", "analytics")],
            "recruiter": [("Overview", "dashboard"), ("Candidate search", "candidates"), ("Pipeline", "pipeline"),
                          ("Clients", "clients"), ("Interviews", "interviews"), ("Reports", "reports")],
            "admin": [("Overview", "dashboard"), ("Users", "users"), ("Jobs", "jobs"),
                      ("Applications", "applications"), ("Employers", "employers"), ("Recruiters", "recruiters"),
                      ("Payments", "payments"), ("Credit management", "credit-management"), ("Audit logs", "audit-logs")]
        }
        nav_html = "".join('<a class="nav-link" href="/workspace/modules/' + key + '">' + label + '</a>'
                           for label, key in nav_by_role.get(role, []))
        safe_name = str(user["full_name"]).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        page = String = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
        <title>Workspace · Career Agency</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">
        <style>
        *{box-sizing:border-box}body{margin:0;background:#080d19;color:#f4f7fc;font-family:"DM Sans",system-ui,sans-serif}
        .shell{min-height:100vh;display:grid;grid-template-columns:250px minmax(0,1fr)}
        aside{background:#0b1425;border-right:1px solid #1d2b43;padding:25px 17px;display:flex;flex-direction:column}
        .brand{display:flex;align-items:center;gap:11px;padding:0 8px 28px}.mark{width:40px;height:40px;border-radius:13px;background:linear-gradient(135deg,#91bdff,#3275e7);display:grid;place-items:center;color:#071329;font-weight:900;font-family:Manrope}
        .brand strong{font:800 12px Manrope;letter-spacing:.14em}.brand small{display:block;color:#7387a6;font-size:10px;margin-top:4px}
        .role{font-size:10px;color:#7186a6;text-transform:uppercase;letter-spacing:.14em;padding:0 10px 12px}
        .nav{display:grid;gap:5px}.nav-link{color:#9fb0c9;text-decoration:none;padding:11px 12px;border-radius:10px;font-size:13px}.nav-link:hover,.nav-link.active{background:#172844;color:#e8f1ff}
        .aside-bottom{margin-top:auto;border-top:1px solid #1d2b43;padding-top:15px;display:grid;gap:7px}
        main{min-width:0;padding:30px clamp(18px,4vw,54px) 90px}.top{display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:34px}
        .eyebrow{font-size:11px;color:#82adf3;letter-spacing:.15em;text-transform:uppercase;font-weight:700}
        h1{font:800 clamp(25px,4vw,34px) Manrope;margin:8px 0 6px;letter-spacing:-.04em}.muted{color:#91a3bd;font-size:14px;line-height:1.6}
        .wallet{border:1px solid #294266;background:#101e34;border-radius:14px;padding:12px 16px;min-width:150px;text-decoration:none;color:#e8f1ff}
        .wallet small{display:block;color:#91a3bd;font-size:10px;letter-spacing:.1em}.wallet strong{font:800 20px Manrope}
        .grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:25px 0}
        .stat{background:#101a2d;border:1px solid #21324d;border-radius:16px;padding:18px;min-height:116px}
        .stat span{color:#9aabc3;font-size:12px}.stat strong{display:block;font:800 27px Manrope;margin-top:12px}
        .section{margin-top:34px}.section h2{font:700 17px Manrope;margin:0 0 14px}
        .actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
        .action{display:block;text-decoration:none;color:#eaf2ff;background:#101a2d;border:1px solid #263852;border-radius:15px;padding:18px}
        .action b{display:block;font:700 14px Manrope;margin-bottom:7px}.action span{color:#95a8c3;font-size:12px;line-height:1.5}
        .empty{border:1px dashed #31445f;border-radius:16px;padding:24px;color:#94a7c2;font-size:13px;line-height:1.6}
        .error{color:#ffaaa8}.mobile-nav{display:none}
        @media(max-width:1050px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:720px){.shell{display:block}aside{display:none}main{padding:22px 16px 105px}.top{align-items:flex-start}.wallet{min-width:120px}.grid{gap:10px}.stat{padding:14px;min-height:98px}.stat strong{font-size:23px}.actions{grid-template-columns:1fr}.mobile-nav{display:flex;position:fixed;z-index:5;left:0;right:0;bottom:0;background:#0b1425;border-top:1px solid #243550;padding:9px 6px calc(9px + env(safe-area-inset-bottom));justify-content:space-around}.mobile-nav a{color:#a8bad2;text-decoration:none;font-size:10px;text-align:center;padding:6px 5px}}
        </style></head><body><div class="shell"><aside><div class="brand"><div class="mark">CA</div><div><strong>CAREER AGENCY</strong><small>CAREER GROWTH, WITH DIRECTION</small></div></div>
        <div class="role">""" + role_label + """ WORKSPACE</div><nav class="nav">""" + nav_html + """</nav>
        <div class="aside-bottom"><a class="nav-link" href="/workspace/modules/profile">My profile</a><a class="nav-link" href="/workspace/modules/settings">Settings</a><a class="nav-link" href="/auth/logout">Sign out</a></div></aside>
        <main><div class="top"><div><div class="eyebrow">CAREER AGENCY / OVERVIEW</div><h1>Welcome back, """ + safe_name + """</h1><div class="muted">Here is your workspace at a glance.</div></div>
        <a class="wallet" href="/workspace/modules/wallet"><small>CAREER CREDITS</small><strong id="credits">""" + str(user["credits"]) + """</strong></a></div>
        <div class="grid" id="stats"><div class="stat"><span>Loading your overview</span><strong>—</strong></div></div>
        <section class="section"><h2>Quick actions</h2><div class="actions">
        <a class="action" href="/workspace/modules/jobs"><b>Explore opportunities</b><span>Find roles and manage opportunities relevant to your goals.</span></a>
        <a class="action" href="/workspace/modules/cv-studio"><b>Open CV Studio</b><span>Prepare and manage your professional documents.</span></a>
        <a class="action" href="/workspace/modules/ai-assistant"><b>Open AI assistant</b><span>Get structured help with your next career task.</span></a>
        </div></section>
        <section class="section"><h2>Recent activity</h2><div class="empty" id="activity">Your recent activity will appear here as you use Career Agency.</div></section>
        <div id="dashboard-error" class="error" role="alert"></div></main></div>
        <nav class="mobile-nav"><a href="/workspace">Home</a><a href="/workspace/modules/jobs">Jobs</a><a href="/workspace/modules/applications">Applications</a><a href="/workspace/modules/profile">Profile</a><a href="/workspace/modules/wallet">Wallet</a></nav>
        <script>
        const role=""" + json.dumps(role) + """;
        const labels={job_seeker:[["applications","Applications"],["saved_jobs","Saved jobs"],["cv_documents","CV documents"],["upcoming_interviews","Upcoming interviews"]],
        employer:[["active_jobs","Active jobs"],["total_jobs","Total jobs"],["applicants","Applicants"],["upcoming_interviews","Upcoming interviews"]],
        recruiter:[["pipeline_candidates","Pipeline candidates"],["unread_notifications","Unread notifications"]],
        admin:[["users","Users"],["jobs","Jobs"],["applications","Applications"],["pending_employers","Pending employers"]]};
        fetch("/api/v1/dashboard").then(async r=>{const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Could not load dashboard.");const d=x.data;document.getElementById("credits").textContent=d.credits.toLocaleString();
        const items=labels[role]||[];document.getElementById("stats").innerHTML=items.map(([k,label])=>'<div class="stat"><span>'+label+'</span><strong>'+Number(d.metrics[k]||0).toLocaleString()+'</strong></div>').join("");
        }).catch(e=>{document.getElementById("dashboard-error").textContent=e.message;document.getElementById("stats").innerHTML='<div class="empty">Dashboard data is temporarily unavailable. Refresh to try again.</div>';});
        </script></body></html>"""
        return page

    @app.get("/workspace/modules/<module_key>")
    @_require_user
    def core_workspace_module_placeholder(module_key):
        user = _current_user()
        if not user["onboarding_completed_at"]:
            return redirect("/onboarding")
        module_titles = {
            "dashboard": "Overview", "jobs": "Job discovery and management", "applications": "Applications",
            "saved-jobs": "Saved jobs", "cv-studio": "CV Studio", "ai-assistant": "AI assistant",
            "interviews": "Interview preparation", "career-roadmap": "Career roadmap", "applicants": "Applicants",
            "candidates": "Candidate search", "team": "Team management", "analytics": "Analytics",
            "pipeline": "Recruitment pipeline", "clients": "Client management", "reports": "Reports",
            "users": "User management", "employers": "Employer management", "recruiters": "Recruiter management",
            "payments": "Payments", "credit-management": "Credit management", "audit-logs": "Audit logs",
            "profile": "My profile", "settings": "Settings", "wallet": "Career Credits wallet"
        }
        title = module_titles.get(module_key)
        if module_key == "profile":
            return redirect("/profile")
        if module_key == "wallet":
            return redirect("/wallet")
        if module_key == "ai-assistant":
            return redirect("/ai-assistant")
        if module_key == "jobs":
            return redirect("/workspace/jobs" if user["role"] == "job_seeker" else "/workspace/employer/jobs")
        if module_key == "applications":
            return redirect("/workspace/applications")
        if module_key == "saved-jobs":
            return redirect("/workspace/saved-jobs")
        if module_key == "pipeline":
            return redirect("/workspace/recruiter/pipeline")
        if module_key == "cv-studio":
            return redirect("/workspace/cv-studio")
        if not title:
            return _json_error("MODULE_NOT_FOUND", "This workspace module does not exist.", 404)
        content = """<div style="padding:18px;border:1px solid #293d5b;border-radius:15px;background:#0a1425;margin:20px 0">
        <p style="color:#dce8f8;line-height:1.7">This module is included in the approved Career Agency architecture. Its dedicated screens and service operations are being implemented in staged releases.</p>
        <p style="color:#9aabc3;font-size:12px">Your existing account and data remain protected while this module is connected.</p></div>
        <div class="links"><a href="/workspace">Return to overview</a></div>"""
        return _auth_page(title, "Role: " + user["role"].replace("_", " ").title(), content)

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
        const x=await r.json();if(!r.ok)throw new Error(x.error?.message||"Unable to create account.");location.href="/verify-email?email="+encodeURIComponent(d.email)+"&delivery="+encodeURIComponent(x.data.verification_email||"queued");
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
        const params=new URLSearchParams(location.search);
        f.elements.email.value=params.get("email")||"";
        if(params.get("delivery")==="not_configured"){document.getElementById("status").textContent="Your account has been created, but email delivery is not configured yet. You must verify your email before signing in. Please try resending later or contact support.";}
        const token=params.get("token");if(token){fetch("/api/v1/auth/csrf").then(x=>x.json()).then(c=>fetch("/api/v1/auth/verify-email",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":c.data.csrf_token},body:JSON.stringify({token})})).then(async r=>{const x=await r.json();document.getElementById("status").textContent=r.ok?"Your email is verified. You can now sign in.":(x.error?.message||"This verification link is invalid or expired.");}).catch(()=>{});}
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
            db.execute("UPDATE mobile_refresh_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?",
                       (utc_now(), row["user_id"]))
            db.execute("UPDATE mobile_access_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?",
                       (utc_now(), row["user_id"]))
            db.commit()
        _audit(row["user_id"], "auth.password_reset", "user", row["user_id"], "success")
        return jsonify({"data": {"password_updated": True, "sessions_revoked": True},
                         "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/mobile/auth/login")
    def core_mobile_login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        bucket = hashlib.sha256(((request.remote_addr or "unknown") + ":" + email).encode()).hexdigest()
        if not _rate_limit("mobile-login:" + bucket, 8, 900):
            return _json_error("RATE_LIMITED", "Too many sign-in attempts. Wait before trying again.", 429)
        with _connect() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return _json_error("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
        if user["account_status"] == "pending_verification" or not user["email_verified_at"]:
            return _json_error("EMAIL_NOT_VERIFIED", "Verify your email address before signing in.", 403)
        if user["account_status"] != "active":
            return _json_error("ACCOUNT_UNAVAILABLE", "This account cannot access the service.", 403)
        refresh, family, _ = _issue_mobile_refresh(user["id"])
        access = _issue_mobile_access(user, family)
        _audit(user["id"], "mobile.auth.login", "user", user["id"], "success")
        return jsonify({"data": {"access_token": access, "token_type": "Bearer", "expires_in": 900,
                                 "refresh_token": refresh, "refresh_expires_in": 2592000,
                                 "user": {"id": user["id"], "email": user["email"],
                                          "full_name": user["full_name"], "role": user["role"]}},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/mobile/auth/refresh")
    def core_mobile_refresh():
        data = request.get_json(silent=True) or {}
        raw = str(data.get("refresh_token", "")).strip()
        if not raw:
            return _json_error("VALIDATION_ERROR", "Refresh token is required.", 400)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            token = db.execute("SELECT * FROM mobile_refresh_tokens WHERE token_hash=?", (digest,)).fetchone()
            if not token:
                db.rollback()
                return _json_error("INVALID_REFRESH_TOKEN", "Sign in again to continue.", 401)
            if token["consumed_at"] or token["revoked_at"] or token["expires_at"] <= utc_now():
                db.execute("UPDATE mobile_refresh_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE family_id=?",
                           (utc_now(), token["family_id"]))
                db.execute("UPDATE mobile_access_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE family_id=?",
                           (utc_now(), token["family_id"]))
                db.commit()
                return _json_error("REFRESH_TOKEN_REUSE", "This session is no longer valid. Sign in again.", 401)
            user = db.execute("SELECT * FROM users WHERE id=? AND account_status='active' AND email_verified_at IS NOT NULL",
                              (token["user_id"],)).fetchone()
            if not user:
                db.rollback()
                return _json_error("ACCOUNT_UNAVAILABLE", "This account cannot access the service.", 403)
            new_raw = secrets.token_urlsafe(48)
            new_id = str(uuid.uuid4())
            new_expiry = datetime.fromtimestamp(time.time() + 30 * 86400, timezone.utc).isoformat()
            db.execute("UPDATE mobile_refresh_tokens SET consumed_at=?,replaced_by_id=? WHERE id=?",
                       (utc_now(), new_id, token["id"]))
            db.execute("INSERT INTO mobile_refresh_tokens(id,user_id,family_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                       (new_id, user["id"], token["family_id"], hashlib.sha256(new_raw.encode()).hexdigest(),
                        new_expiry, utc_now()))
            db.commit()
        access = _issue_mobile_access(user, token["family_id"])
        return jsonify({"data": {"access_token": access, "token_type": "Bearer", "expires_in": 900,
                                 "refresh_token": new_raw, "refresh_expires_in": 2592000},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/mobile/auth/logout")
    def core_mobile_logout():
        data = request.get_json(silent=True) or {}
        raw = str(data.get("refresh_token", "")).strip()
        if raw:
            digest = hashlib.sha256(raw.encode()).hexdigest()
            with _connect() as db:
                token = db.execute("SELECT family_id,user_id FROM mobile_refresh_tokens WHERE token_hash=?", (digest,)).fetchone()
                if token:
                    now = utc_now()
                    db.execute("UPDATE mobile_refresh_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE family_id=?",
                               (now, token["family_id"]))
                    db.execute("UPDATE mobile_access_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE family_id=?",
                               (now, token["family_id"]))
                    _audit(token["user_id"], "mobile.auth.logout", "user", token["user_id"], "success")
        return jsonify({"data": {"logged_out": True}, "request_id": str(uuid.uuid4())})

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
        public_user = {key: user[key] for key in ("id", "email", "full_name", "role", "account_status")}
        return jsonify({"data": {"user": public_user, "wallet": {"credits": user["credits"],
                        "onboarding_completed": bool(user["onboarding_completed_at"])}},
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
                "callback_url": os.environ.get("CAREER_AGENCY_PUBLIC_URL", "").rstrip("/") + "/payments/return",
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

    @app.post("/api/v1/ai/quote")
    @_require_user
    def core_ai_quote():
        user = _current_user()
        data = request.get_json(silent=True) or {}
        action_key = str(data.get("action", ""))
        input_payload = data.get("input")
        if action_key not in ACTION_BASE_COSTS:
            return _json_error("UNKNOWN_ACTION", "This AI action is not supported.", 404)
        if not isinstance(input_payload, dict):
            return _json_error("VALIDATION_ERROR", "The input field must be an object.", 400)
        if not _rate_limit("ai-quote:" + user["id"], 30, 60):
            return _json_error("RATE_LIMITED", "Too many AI quote requests. Wait a moment and try again.", 429)
        model = "server-default"
        prompt_version = "v1"
        key = _cache_key(action_key, user["id"], input_payload, model, prompt_version)
        input_hash = hashlib.sha256(json.dumps(input_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        # Cache is always checked before a price is quoted or any credit debit can occur.
        with _connect() as db:
            cached = db.execute("SELECT 1 FROM llm_cache WHERE cache_key=? AND (expires_at IS NULL OR expires_at>?)",
                                (key, utc_now())).fetchone()
            price = db.execute("SELECT base_cost,cache_hit_cost,active FROM credit_action_prices WHERE action_key=?",
                               (action_key,)).fetchone()
        if not price or not price["active"]:
            return _json_error("ACTION_UNAVAILABLE", "This AI action is temporarily unavailable.", 503)
        cache_hit = cached is not None
        if cache_hit and price["cache_hit_cost"] is None:
            return _json_error("CACHE_PRICE_NOT_CONFIGURED", "A discounted price has not been approved for this cached action.", 503)
        cost = int(price["cache_hit_cost"] if cache_hit else price["base_cost"])
        if int(user["credits"]) < cost:
            return _json_error("INSUFFICIENT_CREDITS", "There are not enough credits for this action.",
                               402, required=cost, available=int(user["credits"]))
        quote_id = str(uuid.uuid4())
        raw_token = secrets.token_urlsafe(32)
        expires = datetime.fromtimestamp(time.time() + 120, timezone.utc).isoformat()
        with _connect() as db:
            db.execute("INSERT INTO ai_quotes(id,user_id,action_key,input_hash,cache_key,cache_hit,credits_cost,quote_token_hash,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (quote_id, user["id"], action_key, input_hash, key, int(cache_hit), cost,
                        hashlib.sha256(raw_token.encode()).hexdigest(), "pending", expires, utc_now()))
        return jsonify({"data": {"quote_id": quote_id, "quote_token": raw_token, "action": action_key,
                                 "cache_hit": cache_hit, "credits_cost": cost,
                                 "total_credits": int(user["credits"]),
                                 "remaining_credits": int(user["credits"]) - cost,
                                 "expires_at": expires, "expires_in": 120},
                        "request_id": str(uuid.uuid4())})

    @app.post("/api/v1/ai/actions/<action_key>")
    @_require_user
    def core_ai_action(action_key):
        user = _current_user()
        if action_key not in ACTION_BASE_COSTS:
            return _json_error("UNKNOWN_ACTION", "This AI action is not supported.", 404)
        data = request.get_json(silent=True) or {}
        input_payload = data.get("input")
        quote_id = str(data.get("quote_id", ""))
        quote_token = str(data.get("quote_token", ""))
        if not isinstance(input_payload, dict):
            return _json_error("VALIDATION_ERROR", "The input field must be an object.", 400)
        if not quote_id or not quote_token:
            return _json_error("CONFIRMATION_REQUIRED", "Request a credit quote and confirm it before running this action.", 428)
        model = "server-default"
        prompt_version = "v1"
        key = _cache_key(action_key, user["id"], input_payload, model, prompt_version)
        input_hash = hashlib.sha256(json.dumps(input_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        # Recheck SQLite cache immediately before consuming the quote and debiting credits.
        with _connect() as db:
            cached = db.execute("SELECT response_json FROM llm_cache WHERE cache_key=? AND (expires_at IS NULL OR expires_at>?)",
                                (key, utc_now())).fetchone()
            price = db.execute("SELECT base_cost,cache_hit_cost,active FROM credit_action_prices WHERE action_key=?",
                               (action_key,)).fetchone()
            quote = db.execute("SELECT * FROM ai_quotes WHERE id=? AND user_id=?",
                               (quote_id, user["id"])).fetchone()
        if not price or not price["active"]:
            return _json_error("ACTION_UNAVAILABLE", "This AI action is temporarily unavailable.", 503)
        cache_hit = cached is not None
        if cache_hit and price["cache_hit_cost"] is None:
            return _json_error("CACHE_PRICE_NOT_CONFIGURED", "A discounted price has not been approved for this cached action.", 503)
        cost = int(price["cache_hit_cost"] if cache_hit else price["base_cost"])
        if not quote or quote["status"] != "pending" or quote["expires_at"] <= utc_now():
            return _json_error("QUOTE_EXPIRED", "This credit quote has expired. Request a new quote.", 409)
        supplied_hash = hashlib.sha256(quote_token.encode()).hexdigest()
        if not hmac.compare_digest(supplied_hash, quote["quote_token_hash"]):
            return _json_error("INVALID_QUOTE", "The credit confirmation is invalid.", 403)
        if (quote["action_key"] != action_key or quote["input_hash"] != input_hash
                or quote["cache_key"] != key or int(quote["cache_hit"]) != int(cache_hit)
                or int(quote["credits_cost"]) != cost):
            return _json_error("QUOTE_STALE", "The action or cached result changed. Review a new credit quote before continuing.", 409)
        request_id = str(uuid.uuid4())
        idem = "ai-quote:" + quote_id
        with _connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current_quote = db.execute("SELECT status,expires_at,quote_token_hash FROM ai_quotes WHERE id=? AND user_id=?",
                                       (quote_id, user["id"])).fetchone()
            if not current_quote or current_quote["status"] != "pending" or current_quote["expires_at"] <= utc_now():
                db.rollback()
                return _json_error("QUOTE_ALREADY_USED", "This confirmation has already been used. Request a new quote.", 409)
            if not hmac.compare_digest(hashlib.sha256(quote_token.encode()).hexdigest(), current_quote["quote_token_hash"]):
                db.rollback()
                return _json_error("INVALID_QUOTE", "The credit confirmation is invalid.", 403)
            balance_row = db.execute("SELECT credits FROM users WHERE id=?", (user["id"],)).fetchone()
            balance = int(balance_row["credits"])
            if balance < cost:
                db.rollback()
                return _json_error("INSUFFICIENT_CREDITS", "There are not enough credits for this action.",
                                   402, required=cost, available=balance)
            new_balance = balance - cost
            db.execute("UPDATE users SET credits=?,updated_at=? WHERE id=?", (new_balance, utc_now(), user["id"]))
            db.execute("""INSERT INTO credit_ledger(id,user_id,delta,balance_after,entry_type,reference_type,reference_id,
                          idempotency_key,description,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (str(uuid.uuid4()), user["id"], -cost, new_balance, "usage", "ai_request", request_id,
                        idem, action_key + " AI action", utc_now()))
            db.execute("UPDATE ai_quotes SET status='consumed',consumed_at=? WHERE id=?", (utc_now(), quote_id))
            db.execute("""INSERT INTO ai_requests
                          (id,user_id,action_key,cache_key,cache_hit,credits_charged,status,provider,model,created_at,completed_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                       (request_id, user["id"], action_key, key, int(cache_hit), cost,
                        "completed" if cache_hit else "pending", "sqlite-cache" if cache_hit else None,
                        model, utc_now(), utc_now() if cache_hit else None))
            if cache_hit:
                db.execute("UPDATE llm_cache SET hit_count=hit_count+1,last_hit_at=? WHERE cache_key=?",
                           (utc_now(), key))
            db.commit()
        if cache_hit:
            return jsonify({"data": {"request_id": request_id, "cache": {"hit": True},
                "credits": {"charged": cost, "balance": new_balance},
                "result": json.loads(cached["response_json"])}, "request_id": request_id})
        try:
            generated = _llm_generate(action_key, input_payload, model)
            response_json = json.dumps(generated, ensure_ascii=False, separators=(",", ":"))
            with _connect() as db:
                db.execute("""INSERT OR REPLACE INTO llm_cache
                              (cache_key,action_key,provider,model,prompt_version,input_hash,response_json,created_at,expires_at,hit_count)
                              VALUES(?,?,?,?,?,?,?,?,?,0)""",
                           (key, action_key, "configured-adapter", model, prompt_version, input_hash,
                            response_json, utc_now(), None))
                db.execute("UPDATE ai_requests SET status=?,provider=?,completed_at=? WHERE id=?",
                           ("completed", "configured-adapter", utc_now(), request_id))
            return jsonify({"data": {"request_id": request_id, "cache": {"hit": False},
                "credits": {"charged": cost, "balance": new_balance}, "result": generated},
                "request_id": request_id})
        except Exception:
            _refund(user["id"], cost, request_id, "AI provider failed; automatic refund")
            with _connect() as db:
                db.execute("UPDATE ai_requests SET status=?,error_code=?,completed_at=? WHERE id=?",
                           ("refunded", "AI_PROVIDER_ERROR", utc_now(), request_id))
            return _json_error("AI_PROVIDER_ERROR",
                "The AI service is temporarily unavailable. Your credits have been refunded.", 502)

    @app.post("/api/v1/admin/organizations/<organization_id>/verification")
    @_require_user
    def core_organization_verification(organization_id):
        user = _current_user()
        if user["role"] != "admin":
            return _json_error("FORBIDDEN", "Administrator permission is required.", 403)
        data = request.get_json(silent=True) or {}
        status = str(data.get("status", ""))
        reason = str(data.get("reason", "")).strip()
        if status not in {"verified", "rejected", "pending"} or len(reason) < 8:
            return _json_error("VALIDATION_ERROR", "Choose a valid verification status and provide an audit reason.", 400)
        with _connect() as db:
            cur = db.execute("UPDATE organizations SET verification_status=?,updated_at=? WHERE id=?",
                             (status, utc_now(), organization_id))
            if cur.rowcount != 1:
                return _json_error("NOT_FOUND", "Organisation not found.", 404)
        _audit(user["id"], "organisation.verification_updated", "organisation", organization_id, "success",
               {"status": status, "reason": reason})
        return jsonify({"data": {"updated": True, "status": status}, "request_id": str(uuid.uuid4())})

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
