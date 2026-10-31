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

from flask import jsonify, redirect, request, session, url_for
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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=20, isolation_level=None)
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
            credits INTEGER NOT NULL DEFAULT 0 CHECK(credits >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
    if not user_id:
        return None
    own = db or _connect()
    try:
        return own.execute(
            "SELECT id,email,full_name,role,account_status,credits FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
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


def register_core_api(app):
    """Register core routes and auth-first guard on the existing Flask app."""
    app.secret_key = os.environ.get("CAREER_AGENCY_SECRET_KEY", app.secret_key or secrets.token_hex(32))
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", os.environ.get("CAREER_AGENCY_COOKIE_SECURE", "0") == "1")
    _init_db()

    @app.before_request
    def career_agency_auth_first():
        # Existing tests exercise legacy routes in isolation; production defaults to auth-first.
        if app.config.get("TESTING"):
            return None
        if request.endpoint == "static" or request.path.startswith("/static/"):
            return None
        allowed = (
            request.path in {"/login", "/auth/login", "/auth/logout"}
            or request.path.startswith("/api/v1/auth/")
            or request.path == "/api/v1/payments/paystack/webhook"
            or request.path.startswith("/health")
        )
        if allowed or session.get("core_user_id") or session.get("user_id"):
            return None
        if request.path.startswith("/api/"):
            return _json_error("UNAUTHENTICATED", "Please sign in to continue.", 401)
        return redirect("/auth/login?next=" + request.path)

    @app.get("/health/core")
    def core_health():
        return jsonify({"status": "ok", "service": "career-agency-core"})

    @app.get("/auth/login")
    def core_login_screen():
        return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Career Agency</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 20% 0%,#17264a 0,#0a1020 42%,#050812 100%);color:#f8fafc;font-family:Inter,system-ui,sans-serif;display:grid;place-items:center;padding:24px}
.panel{width:min(100%,430px);padding:34px;border:1px solid #263451;border-radius:22px;background:rgba(13,22,42,.94);box-shadow:0 24px 80px #0008}
.brand{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#93c5fd;font-weight:800}.mark{width:42px;height:42px;border-radius:13px;background:linear-gradient(135deg,#60a5fa,#2563eb);display:grid;place-items:center;font-weight:900;color:#071329;margin-bottom:22px}
h1{font-size:28px;margin:10px 0 8px}p{color:#9aabc5;line-height:1.55;margin:0 0 24px}label{display:block;font-size:13px;color:#cbd5e1;margin:16px 0 7px}
input{width:100%;padding:14px 13px;border-radius:11px;border:1px solid #33415c;background:#080f1e;color:white;font-size:15px;outline:none}
input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px #3b82f633}
button{width:100%;margin-top:22px;padding:14px;border:0;border-radius:11px;background:#3b82f6;color:white;font-weight:800;font-size:15px;cursor:pointer}
button:disabled{opacity:.55;cursor:wait}.links{display:flex;justify-content:space-between;gap:12px;margin-top:20px;font-size:13px}
a{color:#93c5fd;text-decoration:none}.error{min-height:20px;color:#fca5a5;font-size:13px;margin-top:12px}
</style></head><body><main class="panel"><div class="mark">CA</div><div class="brand">Career Agency</div>
<h1>Welcome back</h1><p>Sign in to continue to your career workspace.</p>
<form id="login"><label for="email">Email address</label><input id="email" type="email" autocomplete="username" required>
<label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required>
<button id="submit" type="submit">Sign in</button><div class="error" id="error" role="alert"></div></form>
<div class="links"><a href="/forgot-password">Forgot password?</a><a href="/register">Create account</a></div></main>
<script>
const form=document.getElementById('login'),btn=document.getElementById('submit'),err=document.getElementById('error');
form.addEventListener('submit',async e=>{e.preventDefault();btn.disabled=true;btn.textContent='Signing in…';err.textContent='';
try{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value,password:document.getElementById('password').value})});
const d=await r.json();if(!r.ok)throw new Error(d.error?.message||'Unable to sign in.');
location.href='/';}catch(x){err.textContent=x.message;}finally{btn.disabled=false;btn.textContent='Sign in';}});
</script></body></html>"""

    @app.post("/api/v1/auth/register")
    def core_register():
        data = request.get_json(silent=True) or {}
        name, email, password = (str(data.get(k, "")).strip() for k in ("full_name", "email", "password"))
        role = str(data.get("role", "job_seeker"))
        if not name or len(name) > 120 or "@" not in email or len(password) < 10:
            return _json_error("VALIDATION_ERROR", "Provide a name, valid email and password of at least 10 characters.", 400)
        if role not in {"job_seeker", "employer", "recruiter"}:
            return _json_error("VALIDATION_ERROR", "This account type cannot be registered here.", 400)
        user_id = str(uuid.uuid4())
        now = utc_now()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT INTO users(id,email,password_hash,full_name,role,account_status,
                       email_verified_at,credits,created_at,updated_at)
                       VALUES(?,?,?,?,?,'active',?,0,?,?)""",
                    (user_id, email.lower(), generate_password_hash(password, method="scrypt"),
                     name, role, now, now, now),
                )
        except sqlite3.IntegrityError:
            return _json_error("CONFLICT", "An account with these details may already exist.", 409)
        _audit(user_id, "account.registered", "user", user_id, "success", {"role": role})
        return jsonify({"data": {"user_id": user_id, "status": "active"},
                        "request_id": str(uuid.uuid4())}), 201

    @app.post("/api/v1/auth/login")
    def core_login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        with _connect() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or user["account_status"] != "active" or not check_password_hash(user["password_hash"], password):
            return _json_error("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
        session.clear()
        session["core_user_id"] = user["id"]
        session["core_role"] = user["role"]
        _audit(user["id"], "auth.login", "user", user["id"], "success")
        return jsonify({"data": {"user": {"id": user["id"], "email": user["email"],
            "full_name": user["full_name"], "role": user["role"]},
            "wallet": {"credits": user["credits"]}}, "request_id": str(uuid.uuid4())})

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
        # Provider integration is intentionally fail-closed until a provider adapter is configured.
        # A paid miss is refunded exactly once rather than returning a fake/generated result.
        _refund(user["id"], cost, request_id, "AI provider is not configured; automatic refund")
        with _connect() as db:
            db.execute("UPDATE ai_requests SET status='refunded',error_code='AI_PROVIDER_NOT_CONFIGURED',completed_at=? WHERE id=?",
                       (utc_now(), request_id))
        return _json_error("AI_PROVIDER_NOT_CONFIGURED",
            "The AI provider adapter has not been configured yet. Your credits have been refunded.", 503)

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
