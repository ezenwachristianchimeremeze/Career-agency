"""Offline Flask route and SQLite smoke tests for the single-file Career Agency app."""
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

APP_FILE = Path(__file__).with_name("app.py").resolve()


@pytest.fixture(scope="module")
def flask_module(tmp_path_factory):
    """Import app.py in an isolated directory so tests do not touch the user's DB."""
    old_cwd = Path.cwd()
    test_cwd = tmp_path_factory.mktemp("career-agency-test")
    os.chdir(test_cwd)
    module_name = "career_agency_app_under_test"
    spec = importlib.util.spec_from_file_location(module_name, APP_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        module.app.config.update(TESTING=True)
        yield module
    finally:
        sys.modules.pop(module_name, None)
        os.chdir(old_cwd)


@pytest.fixture
def client(flask_module):
    return flask_module.app.test_client()


def save_test_api_key(value="pytest-not-a-real-key"):
    """Save a dummy Gemini key in the isolated test database."""
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute(
            'INSERT INTO settings("key",value) VALUES(?,?) ON CONFLICT("key") DO UPDATE SET value=excluded.value',
            ("GEMINI_API_KEY",value),
        )


def install_fake_gemini(monkeypatch):
    """Mock the Gemini SSE endpoint so tests remain deterministic and offline."""
    import requests

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "A helpful streamed response."}]}}]}

        def iter_lines(self, decode_unicode=False):
            for text in ("A helpful ", "streamed response."):
                event = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
                line = "data: " + json.dumps(event)
                yield line if decode_unicode else line.encode("utf-8")

    def fake_post(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    save_test_api_key()


def test_home_route_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Active Pipeline" in response.data


def test_ai_assistant_get_returns_200(client):
    response = client.get("/ai_assistant")
    assert response.status_code == 200
    assert b"AI Career Assistant" in response.data or b"Career Agency AI" in response.data


def test_ai_assistant_post_returns_valid_json(client, flask_module, monkeypatch):
    install_fake_gemini(monkeypatch)
    response = client.post("/ai_assistant", json={"message": "Give me one interview tip."})
    assert response.status_code == 200
    assert response.is_json
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert payload.get("reply") == "A helpful streamed response."
    with sqlite3.connect("job_agent.db") as conn:
        saved_senders = [
            row[0]
            for row in conn.execute(
                "SELECT sender FROM chat_history ORDER BY id DESC LIMIT 2"
            )
        ]
    assert saved_senders == ["assistant", "user"]


def test_ai_assistant_streams_server_sent_events(client, monkeypatch):
    install_fake_gemini(monkeypatch)
    response = client.post(
        "/ai_assistant",
        json={"message": "Stream a test answer.", "stream": True},
        buffered=True,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert '"token": "A helpful "' in body
    assert '"token": "streamed response."' in body
    assert '"done": true' in body


def test_chat_history_api_loads_recent_rows_from_sqlite(client):
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("INSERT INTO chat_history(sender,message) VALUES(?,?)",("user","Persisted user question"))
        conn.execute("INSERT INTO chat_history(sender,message) VALUES(?,?)",("assistant","Persisted assistant answer"))
    response=client.get("/api/chat/history")
    assert response.status_code==200
    messages=response.get_json()["messages"]
    assert [item["message"] for item in messages[-2:]]==["Persisted user question","Persisted assistant answer"]
    assert [item["sender"] for item in messages[-2:]]==["user","assistant"]
    assert all(item["id"] and item["timestamp"] for item in messages[-2:])


def test_ai_assistant_injects_sqlite_profile_into_gemini_system_instruction(client,monkeypatch):
    import requests
    save_test_api_key()
    profile={"full_name":"SQLite Profile Candidate","headline":"Platform Engineer", "tech_skills":["Python","FastAPI"]}
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile(id,profile_json) VALUES(1,?)",
            (json.dumps(profile),),
        )
    captured=[]

    class FakeStreamResponse:
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def raise_for_status(self): return None
        def iter_lines(self,decode_unicode=False):
            line='data: '+json.dumps({"candidates":[{"content":{"parts":[{"text":"Profile-aware response."}]}}]})
            yield line if decode_unicode else line.encode("utf-8")

    def fake_post(url,**kwargs):
        captured.append(kwargs["json"]);return FakeStreamResponse()

    monkeypatch.setattr(requests,"post",fake_post)
    response=client.post("/ai_assistant",json={"message":"Write me a tailored cover letter.","stream":True},buffered=True)
    assert response.status_code==200
    system_text=captured[0]["systemInstruction"]["parts"][0]["text"]
    assert "profile loaded from the SQLite user_profile table" in system_text
    assert "SQLite Profile Candidate" in system_text
    assert "Python" in system_text and "FastAPI" in system_text


def test_sqlite_database_initializes_expected_tables(flask_module):
    with sqlite3.connect("job_agent.db") as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"applications", "recruitment_emails", "chat_history", "job_queue", "workspace_tasks", "settings", "cvs"}.issubset(tables)
        queue_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(job_queue)")
        }
        assert {"id", "title", "company", "url", "remotive_url", "url_dead", "description", "status", "date_added"}.issubset(queue_columns)
        workspace_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(workspace_tasks)")
        }
        assert {
            "id", "job_id", "task_title", "ai_draft", "user_final_draft", "status", "date_created"
        }.issubset(workspace_columns)
        application_count = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        assert application_count >= 0


def test_cv_upload_extracts_all_supported_formats_and_enforces_limits(client,flask_module,monkeypatch):
    from docx import Document
    import pypdf
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("DELETE FROM cvs")

    document=Document();document.add_paragraph("DOCX CV: FastAPI and cloud architecture")
    docx_stream=io.BytesIO();document.save(docx_stream)
    class FakePage:
        def extract_text(self):return "PDF CV: Python, distributed systems"
    class FakePdfReader:
        is_encrypted=False
        pages=[FakePage()]
        def __init__(self,_stream):pass
    monkeypatch.setattr(pypdf,"PdfReader",FakePdfReader)

    response=client.post("/upload_cv",data={"cv_files":[
        (io.BytesIO(b"Plain text CV with TypeScript."),"resume.txt"),
        (io.BytesIO(b"fake pdf"),"backend.pdf"),
        (io.BytesIO(docx_stream.getvalue()),"platform.docx"),
    ]},content_type="multipart/form-data")
    assert response.status_code==201
    assert len(response.get_json()["cvs"])==3
    with sqlite3.connect("job_agent.db") as conn:
        stored={name:text for name,text in conn.execute("SELECT filename,extracted_text FROM cvs")}
    assert "TypeScript" in stored["resume.txt"]
    assert "Python" in stored["backend.pdf"]
    assert "FastAPI" in stored["platform.docx"]

    too_large=client.post("/api/cvs",data={"cv_files":(io.BytesIO(b"x"*(5*1024*1024+1)),"large.txt")},content_type="multipart/form-data")
    assert too_large.status_code==400 and "5 MB" in too_large.get_json()["error"]
    unsupported=client.post("/api/cvs",data={"cv_files":(io.BytesIO(b"bad"),"resume.exe")},content_type="multipart/form-data")
    assert unsupported.status_code==400

    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES('fourth.txt','Some profile text')")
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES('fifth.txt','Some more text')")
    full=client.post("/api/cvs",data={"cv_files":(io.BytesIO(b"another CV"),"sixth.txt")},content_type="multipart/form-data")
    assert full.status_code==409 and "limited to five" in full.get_json()["error"]

    profile_html=client.get("/profile").get_data(as_text=True)
    assert 'id="cv-upload-form"' in profile_html
    assert 'id="cv-file-input"' in profile_html
    assert "input.value='';form.reset()" in profile_html
    assert "resume.txt - Uploaded" in profile_html
    assert "(5/5)" in profile_html
    assert "fetch('/upload_cv'" in profile_html
    assert profile_html.index('id="skills-form"') < profile_html.index('id="cv-upload-form"')
    skills_input=profile_html.index('id="skills-input"')
    skills_badges=profile_html.index('class="badge"',skills_input)
    assert skills_input < skills_badges


def test_skills_save_redirects_with_newly_saved_values(client):
    response=client.post("/update_skills",data={"skills":"Python, FastAPI, SQLite"},follow_redirects=True)
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert "Skills saved. The field below now shows your saved skills." in html
    input_tag=html.split('id="skills-input"',1)[1].split(">",1)[0]
    assert 'value="Python, FastAPI, SQLite"' in input_tag


def _create_applied_workspace_job():
    """Create a minimal Applied queue record for isolated Workspace API tests."""
    with sqlite3.connect("job_agent.db") as conn:
        cursor = conn.execute(
            """INSERT INTO job_queue
               (title, company, url, description, status, date_added)
               VALUES (?, ?, ?, ?, 'Applied', date('now'))""",
            ("Senior Python Engineer", "Workspace Test Co", "https://example.test/job",
             "Build Python APIs and write technical documentation."),
        )
        return cursor.lastrowid


def test_workspace_task_creation_and_mocked_ai_draft_generation(
    client, monkeypatch
):
    import requests

    save_test_api_key()

    class FakeGenerateResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [{"content": {"parts": [{"text": "Draft article about FastAPI."}]}}]
            }

    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeGenerateResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    job_id = _create_applied_workspace_job()

    page = client.get("/workspace")
    assert page.status_code == 200
    assert b"AI Workspace" in page.data
    assert b"Workspace Test Co" in page.data

    response = client.post(
        "/api/workspace/tasks",
        json={"job_id": job_id, "task_description": "Write a 500-word FastAPI article."},
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["ai_draft"] == "Draft article about FastAPI."
    assert payload["status"] == "Needs Review"
    assert calls and "generateContent" in calls[0][0]

    with sqlite3.connect("job_agent.db") as conn:
        row = conn.execute(
            "SELECT job_id, task_title, ai_draft, status FROM workspace_tasks WHERE id=?",
            (payload["task_id"],),
        ).fetchone()
    assert row == (
        job_id,
        "Write a 500-word FastAPI article.",
        "Draft article about FastAPI.",
        "Needs Review",
    )


def test_workspace_submit_saves_final_draft_and_completes_task(client):
    job_id = _create_applied_workspace_job()
    with sqlite3.connect("job_agent.db") as conn:
        cursor = conn.execute(
            "INSERT INTO workspace_tasks(job_id, task_title, ai_draft, status) VALUES (?, ?, ?, 'Needs Review')",
            (job_id, "Write an API guide", "Initial AI draft"),
        )
        task_id = cursor.lastrowid

    final_text = "Human-reviewed guide with corrected examples and verified details."
    response = client.post(
        f"/api/workspace/tasks/{task_id}/submit",
        json={"user_final_draft": final_text},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "Completed"
    assert response.get_json()["message"] == "Task Submitted Successfully"

    detail = client.get(f"/api/workspace/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.get_json()["user_final_draft"] == final_text
    assert detail.get_json()["status"] == "Completed"


def test_application_packet_generation_is_mocked_and_saved_in_task_history(
    client, monkeypatch
):
    import requests

    save_test_api_key()
    packet = {
        "cover_letter": "Dear Workspace Test Co, I am interested in the Senior Python Engineer role.",
        "form_answers": [
            {"question": "Why do you want this role?", "answer": "I enjoy building Python APIs."},
            {"question": "Describe your FastAPI experience.", "answer": "My profile lists FastAPI projects."},
            {"question": "What are your salary expectations?", "answer": "Could you share the approved range?"},
        ],
        "recruiter_dm": "Hello, I am interested in the Senior Python Engineer role. Could we connect?",
    }

    class FakePacketResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(packet)}]}}]}

    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakePacketResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    job_id = _create_applied_workspace_job()
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("DELETE FROM cvs")
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("packet-cv.txt","Packet CV contains verified FastAPI and Python project experience."))
    response = client.post(
        "/api/workspace/application-packet", json={"job_id": job_id}
    )

    assert response.status_code == 201
    result = response.get_json()
    assert result["status"] == "Needs Review"
    assert result["packet"]["cover_letter"] == packet["cover_letter"]
    assert result["packet"]["form_answers"] == packet["form_answers"]
    assert result["packet"]["recruiter_dm"] == packet["recruiter_dm"]
    assert result["packet"]["direct_url"] == "https://example.test/job"
    assert result["packet"]["search_url"] == "https://www.google.com/search?q=Senior+Python+Engineer+Workspace+Test+Co"
    assert calls and "generateContent" in calls[0][0]
    assert calls[0][1]["json"]["generationConfig"]["responseMimeType"] == "application/json"
    prompt=calls[0][1]["json"]["contents"][0]["parts"][0]["text"]
    assert "packet-cv.txt" in prompt and "verified FastAPI and Python project experience" in prompt
    assert "select the one most relevant to this job" in prompt

    with sqlite3.connect("job_agent.db") as conn:
        row = conn.execute(
            "SELECT job_id, task_title, ai_draft, status FROM workspace_tasks WHERE id=?",
            (result["task_id"],),
        ).fetchone()
    assert row[0] == job_id
    assert row[1].startswith("Application Packet — Workspace Test Co — Senior Python Engineer")
    assert json.loads(row[2])["cover_letter"] == packet["cover_letter"]
    assert row[3] == "Needs Review"

    history = client.get("/api/workspace/tasks").get_json()["tasks"]
    assert any(item["id"] == result["task_id"] for item in history)


def test_code_text_draft_generation_is_saved_to_workspace_history(client, monkeypatch):
    import requests

    save_test_api_key()

    class FakeCodeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [{"content": {"parts": [{"text": "import json\n\n# Parse a JSON file"}]}}]
            }

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: FakeCodeResponse())
    job_id = _create_applied_workspace_job()
    response = client.post(
        "/api/workspace/code-draft",
        json={"job_id": job_id, "prompt": "Write a Python script to parse JSON."},
    )
    assert response.status_code == 201
    result = response.get_json()
    assert result["status"] == "Needs Review"
    assert result["ai_draft"].startswith("import json")

    detail = client.get(f"/api/workspace/tasks/{result['task_id']}").get_json()
    assert detail["job_id"] == job_id
    assert detail["task_title"] == "Code/Text: Write a Python script to parse JSON."
    assert detail["ai_draft"] == result["ai_draft"]



def test_remotive_search_persists_and_returns_exact_source_url(client, flask_module, monkeypatch):
    class HealthyGetResponse:
        status_code=200
        url="https://jobs.example.test/role/final"

    monkeypatch.setattr(flask_module.requests,"get",lambda url,**kwargs: HealthyGetResponse())
    listings = [
        {
            "title": f"Remote Python Engineer {index}",
            "company_name": f"Remotive Company {index}",
            "url": f"https://jobs.example.test/role/{index}?source=remotive",
            "description": "Develop Python services and maintain APIs.",
            "candidate_required_location": "United States",
        }
        for index in range(5)
    ]
    monkeypatch.setattr(flask_module, "get_job_feed", lambda: listings)
    response = client.post("/jobs/search", json={})
    assert response.status_code == 200
    with sqlite3.connect("job_agent.db") as conn:
        rows = conn.execute(
            "SELECT id,url,remotive_url FROM job_queue WHERE company LIKE 'Remotive Company %' ORDER BY id"
        ).fetchall()
    assert len(rows) == 5
    for job_id, stored_url, remotive_url in rows:
        assert stored_url == remotive_url
        details = client.get(f"/api/jobs/{job_id}").get_json()
        assert details["url"] == stored_url
        assert details["remotive_url"] == stored_url
    with sqlite3.connect("job_agent.db") as conn:
        title, company, direct_url = conn.execute(
            "SELECT title,company,remotive_url FROM job_queue WHERE id=?", (rows[0][0],)
        ).fetchone()
        cursor = conn.execute(
            "INSERT INTO applications(title,company,salary,match_score,job_url) VALUES(?,?,?,?,?)",
            (title,company,"Not specified","80%", direct_url),
        )
        app_id=cursor.lastrowid
    legacy_detail=client.get(f"/autofill/{app_id}").get_json()
    assert legacy_detail["job_url"]==direct_url
    assert legacy_detail["url_dead"] is False
    assert legacy_detail["direct_job_url"]==direct_url


def test_remotive_feed_uses_current_public_endpoint(monkeypatch, flask_module):
    calls=[]

    class FakeFeedResponse:
        status=200
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def read(self): return json.dumps({"jobs":[]}).encode("utf-8")

    def fake_urlopen(request,timeout):
        calls.append((request.full_url,timeout))
        return FakeFeedResponse()

    monkeypatch.setattr(flask_module.urllib.request,"urlopen",fake_urlopen)
    assert flask_module.REMOTIVE_API_URL=="https://remotive.com/api/remote-jobs"
    assert flask_module.get_job_feed()==[]
    assert calls and calls[0][0].startswith("https://remotive.com/api/remote-jobs?")
    assert "category=software-dev" in calls[0][0]


def test_job_detail_views_use_direct_link_primary_and_google_search_secondary(client):
    jobs_page=client.get("/jobs")
    assert jobs_page.status_code==200
    jobs_html=jobs_page.get_data(as_text=True)
    assert 'id="google-job-search-link"' in jobs_html
    assert "🚀 Open Direct Application" in jobs_html
    assert "🔍 Search on Google" in jobs_html
    assert 'id="dead-link-warning"' in jobs_html
    assert "background:#16a34a;color:white" in jobs_html
    assert "const directUrl = String(data.direct_job_url || '')" in jobs_html
    assert "directLink.href = directUrl || '#'" in jobs_html
    assert "deadWarning.hidden=true" in jobs_html
    assert "googleSearchLink.href = searchUrl" in jobs_html
    assert "(data.title || '') + ' ' + (data.company || '')" in jobs_html
    assert 'id="cv-match-select"' in jobs_html
    assert 'id="cv-match-btn"' in jobs_html and "CV Match Score" in jobs_html
    assert "checkCVMatch" in jobs_html and "cv-match-results" in jobs_html
    assert 'id="tailor-application-btn"' in jobs_html and "Tailor CV &amp; Cover Letter" in jobs_html
    assert 'id="tailored-cv-text"' in jobs_html and 'id="tailored-cover-letter-text"' in jobs_html
    assert "📋 Copy CV" in jobs_html and "📋 Copy Cover Letter" in jobs_html
    html2pdf_script='https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js'
    assert html2pdf_script in jobs_html and jobs_html.index(html2pdf_script)<jobs_html.index('</head>')
    assert 'id="cv-preview"' in jobs_html and 'background:white;color:#111827;padding:40px' in jobs_html
    assert "downloadPDF()" in jobs_html and "📄 Download as PDF" in jobs_html
    assert "html2pdf().set(opt).from(element).save()" in jobs_html
    assert "image:{type:'jpeg',quality:0.98}" in jobs_html
    assert "html2canvas:{scale:2}" in jobs_html and "format:'a4'" in jobs_html
    requirements=Path(__file__).with_name("requirements.txt").read_text().lower()
    assert "reportlab" not in requirements and "pdfkit" not in requirements and "weasyprint" not in requirements

    workspace_html=client.get("/workspace").get_data(as_text=True)
    assert "Open Application ↗" in workspace_html
    assert "Try Direct Link (Remotive) ↗" in workspace_html
    assert "packet.search_url" in workspace_html
    assert "packet-cover-text" in workspace_html and "packet-answer-text" in workspace_html
    assert "📋 Copy" in workspace_html

    home_page=client.get("/")
    assert 'id="legacy-google-search-link"' in home_page.get_data(as_text=True)


def test_job_detail_api_keeps_original_remotive_url_and_reports_dead_links(client):
    direct_url="https://jobs.example.test/original-apply"
    search_url="https://www.google.com/search?q=Example+Role+Example+Co+job"
    with sqlite3.connect("job_agent.db") as conn:
        cursor=conn.execute(
            """INSERT INTO job_queue(title,company,url,remotive_url,description,status,date_added,location,source)
               VALUES(?,?,?,?,?,'Pending',date('now'),'Remote','Remotive')""",
            ("Example Role","Example Co",search_url,direct_url,"Example job description."),
        )
        job_id=cursor.lastrowid
    details=client.get(f"/api/jobs/{job_id}")
    assert details.status_code==200
    payload=details.get_json()
    assert payload["url"]==direct_url
    assert payload["remotive_url"]==direct_url
    assert payload["direct_job_url"]==direct_url
    assert payload["google_search_url"]=="https://www.google.com/search?q=Example+Role+Example+Co"
    assert payload["url_dead"]==0

    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("UPDATE job_queue SET url_dead=1 WHERE id=?",(job_id,))
    dead=client.get(f"/api/jobs/{job_id}").get_json()
    assert dead["url"] is None
    assert dead["remotive_url"]==direct_url
    assert dead["direct_job_url"]==direct_url
    assert dead["google_search_url"]=="https://www.google.com/search?q=Example+Role+Example+Co"
    assert dead["url_dead"]==1


@pytest.mark.parametrize("status", [404, 410])
def test_dead_remotive_urls_are_marked_none_after_browser_like_get(flask_module, monkeypatch, status):
    calls=[]

    class FakeGetResponse:
        status_code=status
        url="https://jobs.example.test/role/deleted"

    def fake_get(url,**kwargs):
        calls.append((url,kwargs))
        return FakeGetResponse()

    monkeypatch.setattr(flask_module.requests,"get",fake_get)
    jobs=[{"title":"Platform Engineer","company":"Example Co","url":"https://jobs.example.test/role/1"}]
    result=flask_module.validate_job_application_urls(jobs)
    assert result is jobs
    assert calls[0][0]=="https://jobs.example.test/role/1"
    assert calls[0][1]["timeout"]==5
    assert calls[0][1]["headers"]=={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    assert calls[0][1]["allow_redirects"] is True
    assert jobs[0]["url"] is None
    assert jobs[0]["url_dead"] is True
    assert jobs[0]["remotive_url"]=="https://jobs.example.test/role/1"


@pytest.mark.parametrize("final_url",["https://jobs.example.test/404","https://jobs.example.test/not-found"])
def test_remotive_get_redirect_to_missing_page_marks_url_dead(flask_module,monkeypatch,final_url):
    class RedirectedResponse:
        status_code=200
        url=final_url
    monkeypatch.setattr(flask_module.requests,"get",lambda *_args,**_kwargs:RedirectedResponse())
    job={"title":"Backend Engineer","company":"Hiring Co","url":"https://jobs.example.test/role/3"}
    flask_module.validate_job_application_urls([job])
    assert job["url"] is None
    assert job["url_dead"] is True


def test_remotive_get_request_failure_disables_direct_url(flask_module, monkeypatch):
    import requests
    calls=[]

    def failing_get(url,**kwargs):
        calls.append((url,kwargs))
        raise requests.Timeout("timed out")

    monkeypatch.setattr(flask_module.requests,"get",failing_get)
    jobs=[{"title":"Backend Engineer","company":"Hiring Co","url":"https://jobs.example.test/role/2"}]
    flask_module.validate_job_application_urls(jobs)
    assert calls[0][0]=="https://jobs.example.test/role/2"
    assert calls[0][1]["timeout"]==5
    assert jobs[0]["url"] is None
    assert jobs[0]["url_dead"] is True


def test_search_route_persists_dead_link_flag_and_api_exposes_google_fallback(client,flask_module,monkeypatch):
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("UPDATE job_queue SET status='Skipped' WHERE status='Pending'")
        conn.execute("DELETE FROM job_search_log WHERE search_date=date('now')")
    class DeadResponse:
        status_code=410
        url="https://jobs.example.test/role/gone"
    monkeypatch.setattr(flask_module.requests,"get",lambda *_args,**_kwargs:DeadResponse())
    feed=[{
        "title":f"Dead Link Role {index}","company_name":f"Dead Link Co {index}",
        "url":f"https://jobs.example.test/role/{index}",
        "description":"Remote Python engineer building reliable application services.",
        "candidate_required_location":"United States",
    } for index in range(5)]
    monkeypatch.setattr(flask_module,"get_job_feed",lambda:feed)
    response=client.post("/jobs/search",json={})
    assert response.status_code==200
    with sqlite3.connect("job_agent.db") as conn:
        rows=conn.execute(
            "SELECT id,url,remotive_url,url_dead FROM job_queue WHERE company LIKE 'Dead Link Co %' ORDER BY id"
        ).fetchall()
    assert len(rows)==5
    for job_id,stored_url,remotive_url,url_dead in rows:
        assert stored_url.startswith("https://www.google.com/search?")
        assert remotive_url.startswith("https://jobs.example.test/role/")
        assert url_dead==1
        details=client.get(f"/api/jobs/{job_id}").get_json()
        assert details["url"] is None and details["url_dead"]==1
        assert details["remotive_url"]==remotive_url


def test_job_autofill_and_cover_letter_prompts_select_from_uploaded_cvs(client,flask_module,monkeypatch):
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("DELETE FROM cvs")
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("python-cv.txt","Python CV: FastAPI, PostgreSQL, and service ownership."))
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("design-cv.txt","Design CV: Figma, visual systems, and accessibility."))
        cursor=conn.execute(
            "INSERT INTO job_queue(title,company,url,description,status,date_added) VALUES(?,?,?,?, 'Pending',date('now'))",
            ("Backend Engineer","API Company","https://example.test/apply","Build FastAPI services with PostgreSQL and monitoring."),
        )
        job_id=cursor.lastrowid
    calls=[]
    def fake_generate(prompt,system_instruction,**kwargs):
        calls.append(prompt)
        return '[{"key":"Relevant skills","value":"FastAPI and PostgreSQL"}]' if kwargs.get("response_mime_type")=="application/json" else "Tailored letter using Python CV evidence."
    monkeypatch.setattr(flask_module,"gemini_rest_generate",fake_generate)
    letter=client.post(f"/api/jobs/{job_id}/generate",json={"action":"cover_letter"})
    assert letter.status_code==200 and "Tailored letter" in letter.get_json()["output"]
    form=client.post(f"/api/jobs/{job_id}/generate",json={"action":"autofill"})
    assert form.status_code==200 and "FastAPI" in form.get_json()["output"]
    for prompt in calls:
        assert "Here are the user's CVs:" in prompt
        assert "python-cv.txt" in prompt and "service ownership" in prompt
        assert "design-cv.txt" in prompt and "accessibility" in prompt
        assert "Here is the Job Description:" in prompt and "Build FastAPI services" in prompt
        assert "select the most relevant cv" in prompt.lower()


def test_tailor_application_generates_separate_cv_and_cover_letter_from_profile_and_uploaded_cvs(client,flask_module,monkeypatch):
    profile={"full_name":"Tailor Test Candidate","email":"tailor@example.test","tech_skills":["Python","FastAPI"],"summary":"Owned production API services."}
    monkeypatch.setattr(flask_module,"get_profile_snapshot_from_db",lambda:profile)
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("DELETE FROM cvs")
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("selected-python-cv.txt","Python CV: Built FastAPI APIs, optimized PostgreSQL, mentored engineers."))
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("other-cv.txt","Other CV: Visual design and branding."))
        job_id=conn.execute(
            "INSERT INTO job_queue(title,company,url,description,status,date_added) VALUES(?,?,?,?, 'Pending',date('now'))",
            ("Senior API Engineer","Tailoring Co","https://example.test/apply","Seeking FastAPI, PostgreSQL, API ownership, and mentoring."),
        ).lastrowid
    generated=(
        "### TAILORED CV ###\n# Tailored Test Candidate\nSkills: FastAPI, PostgreSQL, API ownership\n\n"
        "### COVER LETTER ###\nDear Hiring Team, my FastAPI and PostgreSQL experience aligns with this role."
    )
    captured=[]
    def fake_generate(prompt,system_instruction,**kwargs):
        captured.append((prompt,system_instruction,kwargs))
        return generated
    monkeypatch.setattr(flask_module,"gemini_rest_generate",fake_generate)
    response=client.post(f"/api/jobs/{job_id}/generate",json={"action":"tailor_application"})
    assert response.status_code==200
    result=response.get_json()
    assert result["action"]=="tailor_application"
    assert result["tailored_cv"]=="# Tailored Test Candidate\nSkills: FastAPI, PostgreSQL, API ownership"
    assert result["cover_letter"]=="Dear Hiring Team, my FastAPI and PostgreSQL experience aligns with this role."
    prompt,system,_=captured[0]
    assert "Act as an expert career coach." in prompt
    assert "### TAILORED CV ###" in prompt and "### COVER LETTER ###" in prompt
    assert "selected-python-cv.txt" in prompt and "optimized PostgreSQL" in prompt
    assert "other-cv.txt" in prompt and "Visual design and branding" in prompt
    assert "Tailor Test Candidate" in prompt and "tailor@example.test" in prompt and "FastAPI" in prompt
    assert "Seeking FastAPI, PostgreSQL, API ownership, and mentoring." in prompt
    assert "do not fabricate candidate facts" in system.lower()


def test_cv_match_score_uses_selected_cv_and_validates_result(client,flask_module,monkeypatch):
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("DELETE FROM cvs")
        cv_id=conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("selected-resume.txt","Selected resume: Python, FastAPI, PostgreSQL." )).lastrowid
        job_id=conn.execute(
            "INSERT INTO job_queue(title,company,url,description,status,date_added) VALUES(?,?,?,?, 'Pending',date('now'))",
            ("Python API Engineer","CV Match Co","https://example.test/job","Requires Python, API design, and PostgreSQL."),
        ).lastrowid
    captured=[]
    def fake_generate(prompt,_system,**kwargs):
        captured.append(prompt)
        return json.dumps({"score":88,"reasons":["Python matches","FastAPI matches","PostgreSQL matches"]})
    monkeypatch.setattr(flask_module,"gemini_rest_generate",fake_generate)
    response=client.post(f"/api/jobs/{job_id}/cv-match",json={"cv_id":cv_id})
    assert response.status_code==200
    assert response.get_json()=={"score":88,"filename":"selected-resume.txt","reasons":["Python matches","FastAPI matches","PostgreSQL matches"]}
    assert "SELECTED CV (selected-resume.txt)" in captured[0]
    assert "Selected resume: Python, FastAPI, PostgreSQL." in captured[0]
    assert client.post(f"/api/jobs/{job_id}/cv-match",json={"cv_id":999999}).status_code==404


def test_database_backup_includes_uploaded_cv_records(client):
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute("DELETE FROM cvs")
        conn.execute("INSERT INTO cvs(filename,extracted_text) VALUES(?,?)",("backup-cv.txt","Backup CV includes confidential CV content."))
    response=client.get("/backup_database")
    assert response.status_code==200
    assert "career_hub.db" in response.headers.get("Content-Disposition","")
    with tempfile.NamedTemporaryFile(suffix=".db") as backup:
        backup.write(response.data);backup.flush()
        with sqlite3.connect(backup.name) as conn:
            assert conn.execute("SELECT filename,extracted_text FROM cvs").fetchone()==("backup-cv.txt","Backup CV includes confidential CV content.")


def test_legacy_application_modal_uses_live_direct_url_and_keeps_google_fallback(client,monkeypatch):
    import requests
    direct_url = "https://careers.example.test/jobs/123/apply"
    class LiveResponse:
        status_code=200
        url=direct_url
    monkeypatch.setattr(requests,"get",lambda *_args,**_kwargs:LiveResponse())
    with sqlite3.connect("job_agent.db") as conn:
        cursor = conn.execute(
            "INSERT INTO applications(title,company,salary,match_score,job_url) VALUES(?,?,?,?,?)",
            ("Backend Engineer", "Example Hiring", "Not specified", "80%", direct_url),
        )
        app_id = cursor.lastrowid
    payload = client.get(f"/autofill/{app_id}").get_json()
    assert payload["job_url"] == direct_url
    assert payload["google_search_url"] == "https://www.google.com/search?q=Backend+Engineer+Example+Hiring"
    assert payload["direct_job_url"] == direct_url
    assert payload["url_dead"] is False

    # The backend ignores a tampered form URL and redirects to the URL stored for this job.
    submitted = client.post(
        f"/confirm_submit/{app_id}", data={"job_url": "https://www.google.com/search?q=wrong"}
    )
    assert submitted.status_code == 302
    assert submitted.headers["Location"] == "/jobs"
    with sqlite3.connect("job_agent.db") as conn:
        old_cursor=conn.execute(
            "INSERT INTO applications(title,company,salary,match_score,job_url) VALUES(?,?,?,?,?)",
            ("Infrastructure Engineer", "Unknown Company", "Not specified", "70%", "https://www.google.com/search?q=old"),
        )
        old_app_id=old_cursor.lastrowid
    old_payload=client.get(f"/autofill/{old_app_id}").get_json()
    assert old_payload["job_url"] == "https://www.google.com/search?q=Infrastructure+Engineer+Unknown+Company"
    assert old_payload["direct_job_url"] == ""
    assert old_payload["url_dead"] is True


def test_legacy_application_modal_preserves_direct_url_without_probing(client,flask_module,monkeypatch):
    dead_url="https://careers.example.test/jobs/expired"
    def unexpected_probe(*_args,**_kwargs):
        raise AssertionError("/autofill must not probe external job URLs")
    monkeypatch.setattr(flask_module.requests,"get",unexpected_probe)
    with sqlite3.connect("job_agent.db") as conn:
        app_id=conn.execute(
            "INSERT INTO applications(title,company,salary,match_score,job_url) VALUES(?,?,?,?,?)",
            ("Expired Role","Example Corp","Not specified","70%",dead_url),
        ).lastrowid
    payload=client.get(f"/autofill/{app_id}").get_json()
    search="https://www.google.com/search?q=Expired+Role+Example+Corp"
    assert payload["direct_job_url"]==dead_url
    assert payload["url_dead"] is False
    assert payload["job_url"]==dead_url
    assert payload["google_search_url"]==search
    submitted=client.post(f"/confirm_submit/{app_id}",data={"job_url":dead_url})
    assert submitted.status_code==302 and submitted.headers["Location"]=="/jobs"


@pytest.mark.parametrize("method", ["get", "post"])
def test_confirm_submit_accepts_get_and_post_and_redirects_to_jobs(client,method):
    with sqlite3.connect("job_agent.db") as conn:
        app_id=conn.execute(
            "INSERT INTO applications(title,company,salary,match_score,job_url) VALUES(?,?,?,?,?)",
            ("Workflow Role","Example Company","Not specified","75%","https://jobs.example.test/apply"),
        ).lastrowid
    response=getattr(client,method)(f"/confirm_submit/{app_id}")
    assert response.status_code==302
    assert response.headers["Location"]=="/jobs"
    with sqlite3.connect("job_agent.db") as conn:
        status=conn.execute("SELECT status FROM applications WHERE id=?",(app_id,)).fetchone()[0]
    assert status=="Applied"


def test_autofill_missing_job_returns_clear_json_and_logs_requested_id(client,capsys):
    missing_id=987654321
    response=client.get(f"/autofill/{missing_id}")
    assert response.status_code==404
    assert response.get_json()=={"error":"Job not found"}
    output=capsys.readouterr().out
    assert f"/autofill requested app_id={missing_id}" in output
    assert f'/autofill app_id={missing_id} returned={{"error": "Job not found"}}' in output


def test_legacy_details_frontend_shows_backend_error_and_direct_link_fallback(client):
    html=client.get("/").get_data(as_text=True)
    assert 'id="submit-form" method="POST"' in html
    assert "if (!response.ok) throw new Error(data.error" in html
    assert "console.error(err)" in html
    assert "window.showToast(err.message || 'Unable to fetch job details. Please try again.'" in html
    assert "const directUrl=String(data.direct_job_url||'')" in html
    assert "document.getElementById('job-url-input').value=directUrl" in html
    assert "primaryButton.disabled=false" in html
    assert 'id="legacy-dead-link-warning"' in html
    assert "document.getElementById('legacy-dead-link-warning').hidden=true" in html
    assert "googleFallback.href=googleUrl||'#'" in html
    assert "🚀 Open Direct Application" in html
    assert "Search on Google" in html
    assert "legacy-google-search-link" in html


def test_ai_assistant_uses_generate_content_and_returns_actual_google_error(client, monkeypatch, capsys):
    import requests

    save_test_api_key()
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    calls = []
    error_message = "API key not valid. Please pass a valid API key."

    class ErrorResponse:
        status_code = 400
        text = json.dumps({"error": {"code": 400, "message": error_message, "status": "INVALID_ARGUMENT"}})

        def json(self):
            return json.loads(self.text)

        def raise_for_status(self):
            raise requests.HTTPError("400 Client Error", response=self)

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return ErrorResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    response = client.post("/ai_assistant", json={"message": "Test actual API error."})
    assert response.status_code == 503
    assert "API Error: HTTP 400" in response.get_json()["reply"]
    assert error_message in response.get_json()["reply"]
    assert calls and "/models/gemini-3.8-flash:generateContent" in calls[0][0]
    assert calls[0][1]["headers"]["x-goog-api-key"] == "pytest-not-a-real-key"
    assert error_message in capsys.readouterr().err


def test_gemini_generation_retries_once_after_timeout(flask_module,monkeypatch):
    import requests
    save_test_api_key()
    calls=[]
    sleeps=[]

    class SuccessResponse:
        def raise_for_status(self): return None
        def json(self):
            return {"candidates":[{"content":{"parts":[{"text":"Retry succeeded."}]}}]}

    def fake_post(url,**kwargs):
        calls.append((url,kwargs))
        if len(calls)==1:raise requests.exceptions.Timeout("simulated mobile network timeout")
        return SuccessResponse()

    monkeypatch.setattr(flask_module.requests,"post",fake_post)
    monkeypatch.setattr(flask_module.time,"sleep",lambda seconds:sleeps.append(seconds))
    result=flask_module.gemini_rest_generate("Test retry","Be concise.")
    assert result=="Retry succeeded."
    assert len(calls)==2
    assert all(call[1]["timeout"]==(10,120) for call in calls)
    assert sleeps==[2]


def test_gemini_generation_reports_clear_error_after_second_timeout(flask_module,monkeypatch):
    import requests
    save_test_api_key()
    calls=[]
    def timeout_post(url,**kwargs):
        calls.append((url,kwargs))
        raise requests.exceptions.Timeout("read timeout")
    monkeypatch.setattr(flask_module.requests,"post",timeout_post)
    monkeypatch.setattr(flask_module.time,"sleep",lambda _seconds:None)
    with pytest.raises(RuntimeError,match="^Network timeout\\. Please check your internet connection and try again\\.$"):
        flask_module.gemini_rest_generate("Test timeout","Be concise.")
    assert len(calls)==2
    assert all(call[1]["timeout"]==(10,120) for call in calls)


def test_ai_buttons_show_generating_state_and_timeout_toast(client):
    html=client.get("/jobs").get_data(as_text=True)
    assert "button.textContent='Generating... ⏳'" in html
    assert "button.disabled=true;button.textContent='Generating... ⏳'" in html
    assert "Network timeout. Please check your internet connection and try again." in html



def test_ai_chat_renders_resilient_composer_and_mic_handlers(client):
    response = client.get("/ai_assistant")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "form.addEventListener('submit'" in html
    assert "event.preventDefault();" in html
    assert "sendPrompt(submittedText" in html
    assert "console.log(\"Mic clicked\")" in html
    assert "#ai-chat-form button#mic-btn.chat-icon-btn" in html
    assert "if (!window.isSecureContext)" in html
    assert "Microphone requires HTTPS or localhost. Please open http://127.0.0.1:5000" in html
    assert "recognition.continuous = false; recognition.interimResults = true;" in html
    assert "event.resultIndex" in html
    assert "if (result.isFinal) finalTranscript" in html
    assert "speechFinalTranscript='';" in html
    assert "if (!finalTranscript.trim()||speechFinalTranscript) return" in html
    assert "interimTranscript=''; // Discard all interim hypotheses" in html
    assert "let isListening = false" in html
    assert "isListening = true; // Set synchronously" in html
    assert "recognition.onstart = () => { isListening=true" in html
    assert "recognition.onend = () => { isListening=false" in html
    assert "isListening=false;" in html
    assert "bubble.classList.add('message-error')" in html
    assert "messageInput.value = ''" in html
    assert "messageInput.style.height = 'auto'" in html
    assert "clearSentDraft(query)" in html
    assert "async function loadChatHistory()" in html
    assert "fetch('/api/chat/history'" in html
    assert "window.addEventListener('load'" in html
    assert "void loadChatHistory()" in html
    marked_cdn='https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js'
    purifier_cdn='https://cdn.jsdelivr.net/npm/dompurify@3.2.6/dist/purify.min.js'
    assert marked_cdn in html and purifier_cdn in html
    assert html.index(marked_cdn)<html.index('</head>') and html.index(purifier_cdn)<html.index('</head>')
    assert "window.marked.parse(ai_reply_text" in html
    assert "DOMPurify.sanitize(parsedHtml" in html
    assert "function readAloud(button)" in html
    assert "window.readAloud=readAloud" in html
    assert "text.replace(/<[^>]*>?/gm, '')" in html
    assert "window.speechSynthesis.onvoiceschanged=updateReadAloudVoices" in html
    assert "waitForReadAloudVoices()" in html
    assert "window.speechSynthesis.cancel();" in html and "window.speechSynthesis.speak(utterance)" in html
    assert "speechSynthesis.getVoices()" in html
    assert "Read Aloud speech synthesis error" in html and "Read Aloud speak() threw an error" in html



def test_profile_saves_gemini_key_locally_without_rendering_secret(client, flask_module):
    test_key = "local-test-api-key-value-123456"
    openai_test_key = "local-openai-test-key-value-654321"
    before = client.get("/profile")
    assert before.status_code == 200
    html_before = before.get_data(as_text=True)
    assert 'id="gemini-api-key"' in html_before
    assert 'id="openai-api-key"' in html_before
    assert 'type="password"' in html_before
    assert "Save API Key" in html_before

    response = client.post(
        "/settings/api-key",
        data={"gemini_api_key": test_key,"openai_api_key":openai_test_key},
        follow_redirects=True,
    )
    assert response.status_code == 200
    html_after = response.get_data(as_text=True)
    assert "API key saved successfully." in html_after
    assert test_key not in html_after
    assert openai_test_key not in html_after
    input_tag = html_after.split('id="gemini-api-key"', 1)[1].split(">", 1)[0]
    assert "value=" not in input_tag

    with sqlite3.connect("job_agent.db") as conn:
        stored = dict(conn.execute(
            'SELECT "key",value FROM settings WHERE "key" IN (?,?)',
            ("GEMINI_API_KEY","OPENAI_API_KEY"),
        ).fetchall())
    assert stored == {"GEMINI_API_KEY":test_key,"OPENAI_API_KEY":openai_test_key}
    assert flask_module.get_gemini_api_key()==test_key
    assert flask_module.get_openai_api_key()==openai_test_key
    with sqlite3.connect("job_agent.db") as reopened:
        assert reopened.execute('SELECT value FROM settings WHERE "key"=?',("GEMINI_API_KEY",)).fetchone()[0]==test_key

    # A blank OpenAI field preserves the previously stored OpenAI key.
    client.post("/settings/api-key",data={"gemini_api_key":"replacement-gemini-key","openai_api_key":""})
    assert flask_module.get_gemini_api_key()=="replacement-gemini-key"
    assert flask_module.get_openai_api_key()==openai_test_key
    assert Path("job_agent.db").stat().st_mode & 0o777 == 0o600


def test_missing_key_banner_when_database_and_environment_are_empty(client, monkeypatch):
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute('DELETE FROM settings WHERE "key"=?', ("GEMINI_API_KEY",))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    page = client.get("/jobs")
    assert page.status_code == 200
    assert b"Please add your Gemini API Key in Profile Settings" in page.data

    response = client.post("/ai_assistant", json={"message": "This must not use environment settings."})
    assert response.status_code == 503
    assert response.get_json()["reply"] == "Please add your Gemini API Key in Profile Settings."


def test_ai_assistant_reads_environment_key_only_when_database_is_empty(client, monkeypatch):
    import requests
    with sqlite3.connect("job_agent.db") as conn:
        conn.execute('DELETE FROM settings WHERE "key"=?', ("GEMINI_API_KEY",))
    environment_key="environment-fallback-test-key"
    monkeypatch.setenv("GEMINI_API_KEY",environment_key)
    calls=[]

    class FakeStreamResponse:
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def raise_for_status(self): return None
        def iter_lines(self,decode_unicode=False):
            line='data: '+json.dumps({"candidates":[{"content":{"parts":[{"text":"Fallback key works."}]}}]})
            yield line if decode_unicode else line.encode("utf-8")

    def fake_post(url,**kwargs):
        calls.append((url,kwargs));return FakeStreamResponse()

    monkeypatch.setattr(requests,"post",fake_post)
    response=client.post("/ai_assistant",json={"message":"Use env key","stream":True},buffered=True)
    assert response.status_code==200
    assert calls and calls[0][1]["headers"]["x-goog-api-key"]==environment_key
    assert "Fallback key works." in response.get_data(as_text=True)



def test_chat_stream_uses_supported_gemini_flash_model(client, monkeypatch):
    import requests

    save_test_api_key()
    calls=[]

    class FakeStreamResponse:
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def raise_for_status(self): return None
        def iter_lines(self,decode_unicode=False):
            line='data: '+json.dumps({"candidates":[{"content":{"parts":[{"text":"Stream OK."}]}}]})
            yield line if decode_unicode else line.encode("utf-8")

    def fake_post(url,**kwargs):
        calls.append((url,kwargs))
        return FakeStreamResponse()

    monkeypatch.setattr(requests,"post",fake_post)
    response=client.post("/ai_assistant",json={"message":"Check stable streaming model.","stream":True},buffered=True)
    assert response.status_code==200
    assert calls and "/models/gemini-3.8-flash:streamGenerateContent" in calls[0][0]
