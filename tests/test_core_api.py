import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from flask import Flask

import career_agency_core as core


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "core-test.sqlite3"
    monkeypatch.setenv("CAREER_AGENCY_CORE_DB", str(db_path))
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-session-secret")
    core.register_core_api(app)
    return app.test_client(), db_path


def create_and_login(client):
    http, db_path = client
    created = http.post("/api/v1/auth/register", json={
        "full_name": "Test Candidate",
        "email": "candidate@example.com",
        "password": "long-test-password-123",
        "role": "job_seeker",
    })
    assert created.status_code == 201
    logged_in = http.post("/api/v1/auth/login", json={
        "email": "candidate@example.com",
        "password": "long-test-password-123",
    })
    assert logged_in.status_code == 200
    return http, db_path


def test_registration_login_and_wallet_balance(client):
    http, db_path = create_and_login(client)
    response = http.get("/api/v1/wallet")
    assert response.status_code == 200
    assert response.get_json()["data"]["credits"] == 0
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        assert "credits" in columns


def test_action_price_catalogue_matches_business_rules(client):
    _, db_path = client
    with sqlite3.connect(db_path) as db:
        rows = dict(db.execute("SELECT action_key,base_cost FROM credit_action_prices"))
    assert rows == {
        "chat": 5,
        "cv": 25,
        "mock_interview": 50,
        "workspace": 72,
    }


def test_cv_cache_hit_is_checked_before_debit_and_charges_discount(client):
    http, db_path = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE users SET credits=50 WHERE email=?", ("candidate@example.com",))
        db.commit()
    payload = {"input": {"document_id": "cv-test-1", "operation": "analyse"}}
    cache_key = core._cache_key("cv", "candidate-user-id", payload["input"], "server-default", "v1")
    # Get the actual authenticated user id for a correctly scoped cache entry.
    with sqlite3.connect(db_path) as db:
        user_id = db.execute("SELECT id FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
    cache_key = core._cache_key("cv", user_id, payload["input"], "server-default", "v1")
    with sqlite3.connect(db_path) as db:
        db.execute(
            """INSERT INTO llm_cache
               (cache_key,action_key,provider,model,prompt_version,input_hash,response_json,created_at,expires_at)
               VALUES(?,?,?,?,?,?,?,?,NULL)""",
            (cache_key, "cv", "test", "server-default", "v1",
             hashlib.sha256(json.dumps(payload["input"], sort_keys=True).encode()).hexdigest(),
             json.dumps({"analysis": "cached result"}), core.utc_now()),
        )
        db.commit()
    response = http.post("/api/v1/ai/actions/cv", json=payload, headers={"Idempotency-Key": "cv-cache-hit-1"})
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["cache"]["hit"] is True
    assert body["credits"]["charged"] == 10
    assert body["credits"]["balance"] == 40
    with sqlite3.connect(db_path) as db:
        ledger = db.execute("SELECT delta FROM credit_ledger").fetchall()
    assert ledger == [(-10,)]


def test_cache_hit_without_approved_discount_does_not_charge(client):
    http, db_path = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE users SET credits=100 WHERE email=?", ("candidate@example.com",))
        db.execute("UPDATE credit_action_prices SET cache_hit_cost=NULL WHERE action_key='chat'")
        user_id = db.execute("SELECT id FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
        payload = {"message": "same scoped prompt"}
        cache_key = core._cache_key("chat", user_id, payload, "server-default", "v1")
        db.execute(
            """INSERT INTO llm_cache
               (cache_key,action_key,provider,model,prompt_version,input_hash,response_json,created_at,expires_at)
               VALUES(?,?,?,?,?,?,?,?,NULL)""",
            (cache_key, "chat", "test", "server-default", "v1", "test-hash",
             json.dumps({"reply": "cached"}), core.utc_now()),
        )
        db.commit()
    response = http.post("/api/v1/ai/actions/chat", json={"input": payload})
    assert response.status_code == 503
    with sqlite3.connect(db_path) as db:
        balance = db.execute("SELECT credits FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
        count = db.execute("SELECT COUNT(*) FROM credit_ledger").fetchone()[0]
    assert balance == 100
    assert count == 0


def test_paystack_webhook_rejects_invalid_signature(client, monkeypatch):
    http, _ = client
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "test-paystack-secret")
    response = http.post(
        "/api/v1/payments/paystack/webhook",
        data=b'{"event":"charge.success","data":{"reference":"not-real"}}',
        content_type="application/json",
        headers={"x-paystack-signature": "invalid"},
    )
    assert response.status_code == 401


def test_login_screen_is_dark_and_is_available(client):
    http, _ = client
    response = http.get("/auth/login")
    assert response.status_code == 200
    assert b"Welcome back" in response.data
    assert b"background:" in response.data
