import hashlib
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask

import career_agency_core as core


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "core-test.sqlite3"
    monkeypatch.setenv("CAREER_AGENCY_CORE_DB", str(db_path))
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-session-secret", email_outbox=[])
    monkeypatch.setattr(core, "_send_auth_email",
                        lambda email, subject, body: app.config["email_outbox"].append((email, subject, body)))
    core.register_core_api(app)
    return app.test_client(), db_path, app



def post_json(http, path, payload, headers=None):
    csrf = http.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]
    merged = {"X-CSRF-Token": csrf}
    if headers:
        merged.update(headers)
    return http.post(path, json=payload, headers=merged)


def put_json(http, path, payload):
    csrf = http.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]
    return http.put(path, json=payload, headers={"X-CSRF-Token": csrf})


def patch_json(http, path, payload):
    csrf = http.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]
    return http.patch(path, json=payload, headers={"X-CSRF-Token": csrf})

def create_role_user(client, email, role, name):
    http, _, app = client
    response = post_json(http, "/api/v1/auth/register", {
        "full_name": name,
        "email": email,
        "password": "long-test-password-123",
        "confirm_password": "long-test-password-123",
        "role": role,
        "terms_accepted": True,
    })
    assert response.status_code == 201
    email_body = app.config["email_outbox"][-1][2]
    verify_url = email_body.split("Verify your email: ", 1)[1]
    token = parse_qs(urlparse(verify_url).query)["token"][0]
    assert post_json(http, "/api/v1/auth/verify-email", {"token": token}).status_code == 200
    assert post_json(http, "/api/v1/auth/login", {
        "email": email,
        "password": "long-test-password-123",
    }).status_code == 200
    return http


def create_and_login(client):
    http, db_path, app = client
    created = post_json(http, "/api/v1/auth/register", {
        "full_name": "Test Candidate",
        "email": "candidate@example.com",
        "password": "long-test-password-123",
        "confirm_password": "long-test-password-123",
        "role": "job_seeker",
        "terms_accepted": True,
    })
    assert created.status_code == 201
    assert created.get_json()["data"]["status"] == "pending_verification"
    email_body = app.config["email_outbox"][0][2]
    verify_url = email_body.split("Verify your email: ", 1)[1]
    token = parse_qs(urlparse(verify_url).query)["token"][0]
    verified = post_json(http, "/api/v1/auth/verify-email", {"token": token})
    assert verified.status_code == 200
    logged_in = post_json(http, "/api/v1/auth/login", {
        "email": "candidate@example.com",
        "password": "long-test-password-123",
    })
    assert logged_in.status_code == 200
    return http, db_path, app


def test_registration_login_and_wallet_balance(client):
    http, db_path, _ = create_and_login(client)
    response = http.get("/api/v1/wallet")
    assert response.status_code == 200
    assert response.get_json()["data"]["credits"] == 0
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        assert "credits" in columns


def test_unverified_user_cannot_login(client):
    http, _, _ = client
    post_json(http, "/api/v1/auth/register", {
        "full_name": "Pending Candidate",
        "email": "pending@example.com",
        "password": "long-test-password-123",
        "confirm_password": "long-test-password-123",
        "role": "job_seeker",
        "terms_accepted": True,
    })
    response = post_json(http, "/api/v1/auth/login", {
        "email": "pending@example.com",
        "password": "long-test-password-123",
    })
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_action_price_catalogue_matches_business_rules(client):
    _, db_path, _ = client
    with sqlite3.connect(db_path) as db:
        rows = dict(db.execute("SELECT action_key,base_cost FROM credit_action_prices"))
    assert rows == {"chat": 5, "cv": 25, "mock_interview": 50, "workspace": 72}


def test_cv_cache_hit_is_checked_before_debit_and_charges_discount(client):
    http, db_path, _ = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE users SET credits=50 WHERE email=?", ("candidate@example.com",))
        user_id = db.execute("SELECT id FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
    payload = {"input": {"document_id": "cv-test-1", "operation": "analyse"}}
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
    quote_response = post_json(http, "/api/v1/ai/quote", {"action": "cv", "input": payload["input"]})
    assert quote_response.status_code == 200
    quote = quote_response.get_json()["data"]
    assert quote["credits_cost"] == 10
    assert quote["remaining_credits"] == 40
    response = post_json(http, "/api/v1/ai/actions/cv", {
        "input": payload["input"], "quote_id": quote["quote_id"], "quote_token": quote["quote_token"]
    }, headers={"Idempotency-Key": "cv-cache-hit-1"})
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["cache"]["hit"] is True
    assert body["credits"]["charged"] == 10
    assert body["credits"]["balance"] == 40
    with sqlite3.connect(db_path) as db:
        ledger = db.execute("SELECT delta FROM credit_ledger").fetchall()
    assert ledger == [(-10,)]


def test_ai_action_requires_confirmation_and_quote_is_single_use(client):
    http, db_path, _ = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE users SET credits=100 WHERE email=?", ("candidate@example.com",))
        db.commit()
    payload = {"input": {"message": "Help me plan my job search."}}
    rejected = post_json(http, "/api/v1/ai/actions/chat", payload)
    assert rejected.status_code == 428
    quote_response = post_json(http, "/api/v1/ai/quote", {"action": "chat", "input": payload["input"]})
    assert quote_response.status_code == 200
    quote = quote_response.get_json()["data"]
    assert quote["credits_cost"] == 5
    assert quote["total_credits"] == 100
    assert quote["remaining_credits"] == 95
    with sqlite3.connect(db_path) as db:
        balance = db.execute("SELECT credits FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
        assert balance == 100
    action_payload = {"input": payload["input"], "quote_id": quote["quote_id"], "quote_token": quote["quote_token"]}
    # No provider is configured in tests, so the first confirmation is charged then refunded.
    first = post_json(http, "/api/v1/ai/actions/chat", action_payload)
    assert first.status_code == 502
    second = post_json(http, "/api/v1/ai/actions/chat", action_payload)
    assert second.status_code == 409


def test_cache_hit_without_approved_discount_does_not_charge(client):
    http, db_path, _ = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE users SET credits=100 WHERE email=?", ("candidate@example.com",))
        user_id = db.execute("SELECT id FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
        db.execute("UPDATE credit_action_prices SET cache_hit_cost=NULL WHERE action_key='chat'")
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
    response = post_json(http, "/api/v1/ai/quote", {"action": "chat", "input": payload})
    assert response.status_code == 503
    with sqlite3.connect(db_path) as db:
        balance = db.execute("SELECT credits FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
        count = db.execute("SELECT COUNT(*) FROM credit_ledger").fetchone()[0]
    assert balance == 100
    assert count == 0


def test_password_reset_invalidates_existing_sessions(client):
    http, db_path, app = create_and_login(client)
    old_cookie = http.get_cookie("session")
    post_json(http, "/api/v1/auth/forgot-password", {"email": "candidate@example.com"})
    body = app.config["email_outbox"][-1][2]
    reset_url = body.split("Reset your password: ", 1)[1]
    token = parse_qs(urlparse(reset_url).query)["token"][0]
    reset = post_json(http, "/api/v1/auth/reset-password", {
        "token": token,
        "password": "new-long-password-456",
    })
    assert reset.status_code == 200
    response = http.get("/api/v1/wallet")
    assert response.status_code == 401


def test_ai_assistant_displays_global_credit_confirmation_modal(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria"})
    post_json(http, "/api/v1/onboarding/complete", {})
    page = http.get("/ai-assistant")
    assert page.status_code == 200
    assert b"USING CREDITS" in page.data
    assert b"DEBITING CREDITS" in page.data
    assert b"Remaining credits" in page.data
    assert b"Cancel" in page.data
    assert b"Confirm" in page.data


def test_wallet_screen_shows_balance_and_inactive_package_state(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria"})
    post_json(http, "/api/v1/onboarding/complete", {})
    wallet = http.get("/wallet")
    assert wallet.status_code == 200
    assert b"Career Credits wallet" in wallet.data
    assert b"Credit packages are temporarily unavailable" in wallet.data
    assert http.get("/workspace/modules/wallet").status_code == 302


def test_account_export_contains_only_current_users_data(client):
    http, _, _ = create_and_login(client)
    post_json(http, "/api/v1/cvs", {"title": "Export CV", "content_text": "My CV content."})
    exported = http.get("/api/v1/account/export")
    assert exported.status_code == 200
    data = exported.get_json()["data"]
    assert data["account"]["email"] == "candidate@example.com"
    assert data["cv_documents"][0]["content_text"] == "My CV content."
    assert "password_hash" not in data["account"]


def test_change_password_revokes_browser_session_and_requires_new_login(client):
    http, _, _ = create_and_login(client)
    changed = post_json(http, "/api/v1/account/change-password", {
        "current_password": "long-test-password-123",
        "new_password": "new-long-password-456",
        "confirm_password": "new-long-password-456",
    })
    assert changed.status_code == 200
    assert changed.get_json()["data"]["sessions_revoked"] is True
    assert http.get("/api/v1/wallet").status_code == 401
    login = post_json(http, "/api/v1/auth/login", {
        "email": "candidate@example.com",
        "password": "new-long-password-456",
    })
    assert login.status_code == 200


def test_production_mode_requires_secret_and_secure_cookie(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_AGENCY_ENV", "production")
    monkeypatch.delenv("CAREER_AGENCY_SECRET_KEY", raising=False)
    app = Flask(__name__)
    with pytest.raises(RuntimeError):
        core.register_core_api(app)
    monkeypatch.setenv("CAREER_AGENCY_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("CAREER_AGENCY_CORE_DB", str(tmp_path / "production-test.sqlite3"))
    secure_app = Flask("secure-test")
    core.register_core_api(secure_app)
    assert secure_app.config["SESSION_COOKIE_SECURE"] is True
    assert secure_app.config["SESSION_COOKIE_HTTPONLY"] is True


def test_password_change_revokes_native_mobile_access_tokens(client):
    browser, _, app = create_and_login(client)
    mobile = app.test_client()
    mobile_login = mobile.post("/api/v1/mobile/auth/login", json={
        "email": "candidate@example.com",
        "password": "long-test-password-123",
    })
    access = mobile_login.get_json()["data"]["access_token"]
    assert mobile.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + access}).status_code == 200
    changed = post_json(browser, "/api/v1/account/change-password", {
        "current_password": "long-test-password-123",
        "new_password": "another-long-password-789",
        "confirm_password": "another-long-password-789",
    })
    assert changed.status_code == 200
    assert mobile.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + access}).status_code == 401


def test_settings_security_and_privacy_export_screens_render(client):
    http, _, _ = create_and_login(client)
    assert http.get("/settings").status_code == 200
    assert http.get("/settings/security").status_code == 200


def test_notifications_are_scoped_and_can_be_marked_read(client):
    http, db_path, _ = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        user_id = db.execute("SELECT id FROM users WHERE email=?", ("candidate@example.com",)).fetchone()[0]
        db.execute("INSERT INTO notifications(id,user_id,category,title,body,created_at) VALUES(?,?,?,?,?,?)",
                   ("notice-test-1", user_id, "system", "Welcome", "Welcome to Career Agency.", "2026-10-31T00:00:00+00:00"))
        db.commit()
    items = http.get("/api/v1/notifications")
    assert items.status_code == 200
    assert items.get_json()["data"][0]["title"] == "Welcome"
    read = post_json(http, "/api/v1/notifications/notice-test-1/read", {})
    assert read.status_code == 200
    assert http.get("/api/v1/notifications").get_json()["data"][0]["read_at"] is not None


def test_interview_prep_screen_requires_job_seeker_and_uses_quote_confirmation(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria"})
    post_json(http, "/api/v1/onboarding/complete", {})
    page = http.get("/workspace/interview-prep")
    assert page.status_code == 200
    assert b"Interview Preparation" in page.data
    assert b"USING CREDITS" in page.data
    assert b"Confirm" in page.data
    assert b"mock_interview" in page.data


def test_cover_letter_library_create_read_update_and_delete(client):
    http, _, _ = create_and_login(client)
    created = post_json(http, "/api/v1/cover-letters", {
        "title": "Technical Writer Application",
        "company_name": "Example Company",
        "job_title": "Technical Writer",
        "content_text": "I am applying for the technical writer role.",
    })
    assert created.status_code == 201
    document_id = created.get_json()["data"]["id"]
    detail = http.get("/api/v1/cover-letters/" + document_id)
    assert detail.status_code == 200
    assert detail.get_json()["data"]["company_name"] == "Example Company"
    updated = patch_json(http, "/api/v1/cover-letters/" + document_id, {
        "title": "Updated Application",
        "company_name": "Example Company",
        "job_title": "Developer Documentation Writer",
        "content_text": "I have experience documenting APIs and developer workflows.",
    })
    assert updated.status_code == 200
    assert http.get("/api/v1/cover-letters").get_json()["data"][0]["title"] == "Updated Application"
    csrf = http.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]
    deleted = http.delete("/api/v1/cover-letters/" + document_id, headers={"X-CSRF-Token": csrf})
    assert deleted.status_code == 200
    assert http.get("/api/v1/cover-letters/" + document_id).status_code == 404


def test_cover_letters_are_private_to_their_owner(client):
    owner, _, _ = create_and_login(client)
    created = post_json(owner, "/api/v1/cover-letters", {
        "title": "Private letter",
        "company_name": "Private Company",
        "job_title": "Writer",
        "content_text": "This document belongs to the first account.",
    })
    document_id = created.get_json()["data"]["id"]
    other = create_role_user(client, "other-user@example.com", "job_seeker", "Other User")
    assert other.get("/api/v1/cover-letters/" + document_id).status_code == 404
    assert other.patch("/api/v1/cover-letters/" + document_id, json={
        "title": "Attempted access",
        "content_text": "Should not be able to update another user's letter.",
    }, headers={"X-CSRF-Token": other.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]}).status_code == 404


def test_cover_letter_screen_and_module_route(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria"})
    post_json(http, "/api/v1/onboarding/complete", {})
    page = http.get("/workspace/cover-letters")
    assert page.status_code == 200
    assert b"Cover Letter Studio" in page.data
    assert b"Save letter" in page.data
    assert b"Delete selected letter" in page.data


def test_cv_library_create_read_update_and_delete(client):
    http, _, _ = create_and_login(client)
    created = post_json(http, "/api/v1/cvs", {
        "title": "Software Developer CV",
        "content_text": "Professional Summary\nPython developer with API experience.",
    })
    assert created.status_code == 201
    cv_id = created.get_json()["data"]["id"]
    detail = http.get("/api/v1/cvs/" + cv_id)
    assert detail.status_code == 200
    assert detail.get_json()["data"]["title"] == "Software Developer CV"
    updated = patch_json(http, "/api/v1/cvs/" + cv_id, {
        "title": "Backend Developer CV",
        "content_text": "Professional Summary\nBackend developer focused on secure APIs.",
    })
    assert updated.status_code == 200
    assert http.get("/api/v1/cvs").get_json()["data"][0]["title"] == "Backend Developer CV"
    deleted = http.delete("/api/v1/cvs/" + cv_id, headers={
        "X-CSRF-Token": http.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]
    })
    assert deleted.status_code == 200
    assert http.get("/api/v1/cvs/" + cv_id).status_code == 404


def test_cv_studio_screen_uses_ai_credit_confirmation(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria"})
    post_json(http, "/api/v1/onboarding/complete", {})
    page = http.get("/workspace/cv-studio")
    assert page.status_code == 200
    assert b"CV Studio" in page.data
    assert b"USING CREDITS" in page.data
    assert b"Confirm" in page.data


def test_profile_get_and_patch_are_user_scoped(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria", "city": "Port Harcourt"})
    before = http.get("/api/v1/profile")
    assert before.status_code == 200
    assert before.get_json()["data"]["email"] == "candidate@example.com"
    updated = patch_json(http, "/api/v1/profile", {
        "full_name": "Updated Candidate",
        "country": "Nigeria",
        "city": "Lagos",
        "headline": "Product Designer",
        "professional_summary": "Designs accessible digital products.",
        "years_experience": 3,
    })
    assert updated.status_code == 200
    after = http.get("/api/v1/profile").get_json()["data"]
    assert after["full_name"] == "Updated Candidate"
    assert after["city"] == "Lagos"
    assert after["headline"] == "Product Designer"


def test_published_job_can_be_saved_applied_to_and_withdrawn(client):
    http = create_role_user(client, "hiring@example.com", "employer", "Hiring Employer")
    put_json(http, "/api/v1/onboarding/profile", {
        "country": "Nigeria",
        "organization_name": "Verified Hiring Co",
        "job_title": "Recruitment Lead",
    })
    post_json(http, "/api/v1/onboarding/complete", {})
    created = post_json(http, "/api/v1/jobs", {
        "title": "Python Backend Developer",
        "description": "Build and maintain secure APIs, improve database performance and support product delivery.",
        "location": "Remote, Nigeria",
        "work_mode": "remote",
        "employment_type": "full_time",
    })
    job_id = created.get_json()["data"]["job_id"]
    _, db_path, _ = client
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE organizations SET verification_status='verified' WHERE owner_user_id=(SELECT id FROM users WHERE email=?)",
                   ("hiring@example.com",))
        db.commit()
    published = post_json(http, "/api/v1/jobs/" + job_id + "/publish", {})
    assert published.status_code == 200
    http = create_role_user(client, "applicant@example.com", "job_seeker", "Test Applicant")
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria", "headline": "Python Developer"})
    post_json(http, "/api/v1/onboarding/complete", {})
    listing = http.get("/api/v1/jobs?q=Python")
    assert listing.status_code == 200
    assert len(listing.get_json()["data"]["jobs"]) == 1
    assert post_json(http, "/api/v1/jobs/" + job_id + "/save", {}).status_code == 200
    saved = http.get("/api/v1/saved-jobs")
    assert len(saved.get_json()["data"]) == 1
    applied = post_json(http, "/api/v1/jobs/" + job_id + "/apply", {"cover_letter": "I am interested in this role and can contribute to the team."})
    assert applied.status_code == 201
    application_id = applied.get_json()["data"]["application_id"]
    applications = http.get("/api/v1/applications")
    assert len(applications.get_json()["data"]) == 1
    withdrawn = post_json(http, "/api/v1/applications/" + application_id + "/withdraw", {})
    assert withdrawn.status_code == 200
    assert http.get("/api/v1/applications").get_json()["data"][0]["status"] == "withdrawn"


def test_recruiter_pipeline_requires_candidate_consent_and_tracks_stage(client):
    http = create_role_user(client, "recruiter@example.com", "recruiter", "Test Recruiter")
    put_json(http, "/api/v1/onboarding/profile", {
        "country": "Nigeria",
        "agency_name": "Talent Search Partners",
        "client_focus": "Technology roles",
    })
    post_json(http, "/api/v1/onboarding/complete", {})
    denied = post_json(http, "/api/v1/recruiter/pipeline", {
        "candidate_name": "Candidate One",
        "role_title": "Backend Engineer",
    })
    assert denied.status_code == 400
    assert denied.get_json()["error"]["code"] == "CANDIDATE_CONSENT_REQUIRED"
    created = post_json(http, "/api/v1/recruiter/pipeline", {
        "candidate_name": "Candidate One",
        "candidate_email": "candidate.one@example.com",
        "role_title": "Backend Engineer",
        "candidate_consent": True,
    })
    assert created.status_code == 201
    item_id = created.get_json()["data"]["id"]
    updated = patch_json(http, "/api/v1/recruiter/pipeline/" + item_id, {"pipeline_stage": "shortlisted"})
    assert updated.status_code == 200
    pipeline = http.get("/api/v1/recruiter/pipeline")
    assert pipeline.get_json()["data"][0]["pipeline_stage"] == "shortlisted"


def test_employer_can_create_draft_but_cannot_publish_unverified_organisation(client):
    http = create_role_user(client, "employer@example.com", "employer", "Test Employer")
    profile = put_json(http, "/api/v1/onboarding/profile", {
        "country": "Nigeria",
        "organization_name": "Example Technologies",
        "website": "https://example.com",
        "job_title": "Hiring Manager",
    })
    assert profile.status_code == 200
    assert post_json(http, "/api/v1/onboarding/complete", {}).status_code == 200
    created = post_json(http, "/api/v1/jobs", {
        "title": "Backend Engineer",
        "description": "We are looking for an engineer to build reliable APIs and maintain production services.",
        "location": "Lagos, Nigeria",
        "work_mode": "hybrid",
        "employment_type": "full_time",
        "salary_min_ngn": 500000,
        "salary_max_ngn": 900000,
    })
    assert created.status_code == 201
    job_id = created.get_json()["data"]["job_id"]
    assert created.get_json()["data"]["status"] == "draft"
    publish = post_json(http, "/api/v1/jobs/" + job_id + "/publish", {})
    assert publish.status_code == 403
    assert publish.get_json()["error"]["code"] == "ORGANISATION_NOT_VERIFIED"


def test_job_seeker_cannot_create_jobs_and_only_sees_published_jobs(client):
    http, _, _ = create_and_login(client)
    denied = post_json(http, "/api/v1/jobs", {
        "title": "Invalid attempt",
        "description": "This description is long enough to pass the minimum description length check.",
    })
    assert denied.status_code == 403
    listed = http.get("/api/v1/jobs")
    assert listed.status_code == 200
    assert listed.get_json()["data"]["jobs"] == []


def test_role_dashboard_metrics_and_workspace_navigation(client):
    http, _, _ = create_and_login(client)
    put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria"})
    post_json(http, "/api/v1/onboarding/complete", {})
    dashboard = http.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    data = dashboard.get_json()["data"]
    assert data["role"] == "job_seeker"
    assert data["metrics"]["applications"] == 0
    page = http.get("/workspace")
    assert page.status_code == 200
    assert b"Welcome back, Test Candidate" in page.data
    module = http.get("/workspace/modules/cv-studio", follow_redirects=True)
    assert module.status_code == 200
    assert b"CV Studio" in module.data


def test_mobile_login_bearer_access_and_refresh_rotation(client):
    _, _, app = create_and_login(client)
    mobile = app.test_client()
    login = mobile.post("/api/v1/mobile/auth/login", json={
        "email": "candidate@example.com",
        "password": "long-test-password-123",
    })
    assert login.status_code == 200
    tokens = login.get_json()["data"]
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]
    wallet = mobile.get("/api/v1/wallet", headers={"Authorization": "Bearer " + access})
    assert wallet.status_code == 200
    rotated = mobile.post("/api/v1/mobile/auth/refresh", json={"refresh_token": refresh})
    assert rotated.status_code == 200
    new_tokens = rotated.get_json()["data"]
    assert new_tokens["refresh_token"] != refresh
    reused = mobile.post("/api/v1/mobile/auth/refresh", json={"refresh_token": refresh})
    assert reused.status_code == 401
    revoked_wallet = mobile.get("/api/v1/wallet", headers={"Authorization": "Bearer " + new_tokens["access_token"]})
    assert revoked_wallet.status_code == 401


def test_mobile_logout_revokes_access_and_refresh_family(client):
    _, _, app = create_and_login(client)
    mobile = app.test_client()
    login = mobile.post("/api/v1/mobile/auth/login", json={
        "email": "candidate@example.com",
        "password": "long-test-password-123",
    })
    tokens = login.get_json()["data"]
    logged_out = mobile.post("/api/v1/mobile/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logged_out.status_code == 200
    wallet = mobile.get("/api/v1/wallet", headers={"Authorization": "Bearer " + tokens["access_token"]})
    assert wallet.status_code == 401


def test_paystack_webhook_rejects_invalid_signature(client, monkeypatch):
    http, _, _ = client
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "test-paystack-secret")
    response = http.post(
        "/api/v1/payments/paystack/webhook",
        data=b'{"event":"charge.success","data":{"reference":"not-real"}}',
        content_type="application/json",
        headers={"x-paystack-signature": "invalid"},
    )
    assert response.status_code == 401


def test_root_is_login_first_then_onboarding_then_workspace(client):
    http, _, _ = client
    first = http.get("/", follow_redirects=False)
    assert first.status_code == 302
    assert first.headers["Location"].endswith("/auth/login")
    create_and_login(client)
    root = http.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["Location"].endswith("/workspace")
    workspace_redirect = http.get("/workspace", follow_redirects=False)
    assert workspace_redirect.status_code == 302
    assert workspace_redirect.headers["Location"].endswith("/onboarding")
    assert http.get("/onboarding").status_code == 200
    assert put_json(http, "/api/v1/onboarding/profile", {"country": "Nigeria", "city": "Port Harcourt"}).status_code == 200
    assert put_json(http, "/api/v1/onboarding/preferences", {"desired_roles": ["Software Developer"], "work_modes": ["Remote"]}).status_code == 200
    complete = post_json(http, "/api/v1/onboarding/complete", {})
    assert complete.status_code == 200
    root = http.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["Location"].endswith("/workspace")
    workspace = http.get("/workspace")
    assert workspace.status_code == 200
    assert b"Welcome back, Test Candidate" in workspace.data


def test_onboarding_requires_country_before_completion(client):
    http, _, _ = create_and_login(client)
    response = post_json(http, "/api/v1/onboarding/complete", {})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "ONBOARDING_INCOMPLETE"


def test_csrf_is_required_for_browser_mutations(client):
    http, _, _ = client
    response = http.post("/api/v1/auth/login", json={
        "email": "nobody@example.com",
        "password": "not-a-real-password",
    })
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


def test_auth_screens_render_and_login_is_dark(client):
    http, _, _ = client
    for path in ["/auth/login", "/register", "/forgot-password", "/reset-password", "/verify-email", "/terms", "/privacy"]:
        response = http.get(path)
        assert response.status_code == 200
        assert b"CAREER AGENCY" in response.data
        assert b"Manrope" in response.data
    assert b"Welcome back." in http.get("/auth/login").data
    assert b"background:" in http.get("/auth/login").data



def test_only_approved_credit_package_endpoints_are_active(client):
    http, _, _ = create_and_login(client)
    response = http.get("/api/v1/credit-packages")
    assert response.status_code == 200
    packages = response.get_json()["data"]["packages"]
    assert {(p["price_kobo"], p["credits"]) for p in packages} == {
        (50_000, 100),
        (20_000_000, 120_000),
    }


def test_employer_can_schedule_interview_and_candidate_can_only_view_it(client):
    http, db_path, _ = create_and_login(client)
    with sqlite3.connect(db_path) as db:
        candidate_id = db.execute(
            "SELECT id FROM users WHERE email='candidate@example.com'"
        ).fetchone()[0]
    http.post("/api/v1/auth/logout")
    employer_http = create_role_user(client, "employer@example.com", "employer", "Test Employer")
    with sqlite3.connect(db_path) as db:
        employer_id = db.execute(
            "SELECT id FROM users WHERE email='employer@example.com'"
        ).fetchone()[0]
        job_id, application_id = "job-interview-test", "application-interview-test"
        now = core.utc_now()
        db.execute(
            """INSERT INTO jobs(id,employer_user_id,title,description,status,created_at,updated_at)
               VALUES(?,?,?,'Test role','published',?,?)""",
            (job_id, employer_id, "Backend Engineer", now, now),
        )
        db.execute(
            """INSERT INTO applications(id,job_id,applicant_user_id,status,applied_at,updated_at)
               VALUES(?,?,?,'submitted',?,?)""",
            (application_id, job_id, candidate_id, now, now),
        )
        db.commit()
    from datetime import datetime, timedelta, timezone
    scheduled = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    created = post_json(employer_http, "/api/v1/interviews", {
        "application_id": application_id,
        "scheduled_at": scheduled,
        "duration_minutes": 45,
        "meeting_url": "https://meet.example.com/interview",
    })
    assert created.status_code == 201
    interview_id = created.get_json()["data"]["id"]
    listed = employer_http.get("/api/v1/interviews")
    assert listed.status_code == 200
    assert len(listed.get_json()["data"]) == 1
    assert listed.get_json()["data"][0]["applicant_name"] == "Test Candidate"
    http = client[0]
    http.post("/api/v1/auth/logout")
    post_json(http, "/api/v1/auth/login", {
        "email": "candidate@example.com",
        "password": "long-test-password-123",
    })
    candidate_list = http.get("/api/v1/interviews")
    assert candidate_list.status_code == 200
    assert http.get("/workspace/interviews").status_code == 200
    assert [item["id"] for item in candidate_list.get_json()["data"]] == [interview_id]
    denied = post_json(http, "/api/v1/interviews", {
        "application_id": application_id,
        "scheduled_at": scheduled,
    })
    assert denied.status_code == 403
