import os
import json
import sqlite3
import urllib.parse
from flask import Flask, render_template_string, request, jsonify, redirect, url_for
import ai_helper

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            company TEXT,
            salary TEXT,
            match_score TEXT,
            stage TEXT DEFAULT 'Active Pipeline',
            status TEXT DEFAULT 'Pending Review',
            job_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recruitment_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            subject TEXT,
            category TEXT,
            snippet TEXT,
            suggested_reply TEXT,
            app_id INTEGER,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM applications")
    if cursor.fetchone()[0] == 0:
        sample_jobs = [
            ("Senior React Full-stack Developer", "Lemon.io", "$35,3k- $52k", "95%", "Active Pipeline", "Pending Review", "https://lemon.io/apply"),
            ("Freelance Writer", "IAPWE", "Not Specified", "85%", "Active Pipeline", "Pending Review", "https://iapwe.org/apply"),
            ("Freelance Copywriter", "Coalition Technologies", "Not Specified", "85%", "Active Pipeline", "Pending Review", "https://coalitiontechnologies.com/careers"),
            ("Article Pitch: Asynchronous Python Microservices", "DigitalOcean Community", "Not Specified", "85%", "Active Pipeline", "Pending Review", "https://www.digitalocean.com/community/write-for-donations"),
            ("Lead Technical Author Architect", "Aether Cloud Infrastructure", "$100,000 - $130,000 / yr", "89%", "Active Pipeline", "Pending Review", "")
        ]
        cursor.executemany("INSERT INTO applications (title, company, salary, match_score, stage, status, job_url) VALUES (?, ?, ?, ?, ?, ?, ?)", sample_jobs)
    
    conn.commit()
    conn.close()

init_db()

# --- PROFILE HELPER ---
def get_profile_data():
    profile_path = "profile.json"
    default_profile = {
        "full_name": "EZENWA CHRISTIAN CHIMEREMEZE",
        "headline": "Technical Writer | Developer Documentation | Full-Stack Software Developer",
        "email": "ezenwachristian413@gmail.com",
        "secondary_email": "christianfever31@gmail.com",
        "phone": "+234 813 504 6008",
        "portfolio": "https://ezenwa-christian.netlify.app",
        "github": "https://github.com/christianfever31-commits",
        "medium": "https://ezenwachristianchimeremeze.medium.com",
        "avatar_url": "/static/uploads/profile_avatar.jpg",
        "cover_url": "/static/uploads/cover_banner.jpg",
        "origin": "Umuaka, Njaba LGA, Imo State, Nigeria",
        "summary": "Self-taught technology developer, technical author, and emerging AI & robotics engineer specializing in Python, FastAPI, TypeScript, LLM function calling, Edge AI automation, and developer documentation.",
        "tech_skills": ["Python", "FastAPI", "TypeScript", "JavaScript", "REST APIs", "Pydantic", "React", "React Native", "Git", "Termux", "SQLite"],
        "projects": [
            {"name": "Geminio OS", "desc": "AI-first full-stack development ecosystem designed to unify AI agent workflows, code analysis, and edge automation."},
            {"name": "Termux Edge Voice Command Pipeline", "desc": "Offline-first voice control pipeline connecting Android Termux, Python, local speech recognition, and relay triggers."},
            {"name": "4WD AI Research Robot", "desc": "Planned mobile research robot using Raspberry Pi 5, ESP32, ROS 2, OpenCV, and sensor integration."}
        ]
    }
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_profile.update(data)
        except Exception:
            pass
    return default_profile

# --- HYBRID URL BUILDER ---
def format_direct_job_url(company, title, default_url=""):
    clean_company = (company or "").lower().replace("blog", "").replace("inc", "").replace("ltd", "").strip()
    
    if "lemon" in clean_company: return "https://lemon.io/apply"
    if "sitepoint" in clean_company: return "https://www.sitepoint.com/write-for-us/"
    if "draft" in clean_company: return "https://draft.dev/write"
    if "logrocket" in clean_company: return "https://blog.logrocket.com/author-apply"
    if "digitalocean" in clean_company: return "https://www.digitalocean.com/community/write-for-donations"
    if "iapwe" in clean_company: return "https://iapwe.org/apply"
    if "coalition" in clean_company: return "https://coalitiontechnologies.com/careers"
    
    query = urllib.parse.quote(f"{company} {title} career apply form")
    return f"https://www.google.com/search?q={query}"

# --- MASTER UI TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Career Agent Enterprise Hub</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        body { background-color: #070a13; color: #f8fafc; padding-bottom: 85px; min-height: 100vh; }
        
        .top-nav-bar {
            position: sticky; top: 0; z-index: 1000;
            background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(12px);
            border-bottom: 1px solid #1e293b; padding: 10px 16px;
            display: flex; align-items: center; gap: 12px;
        }
        .top-nav-avatar {
            width: 38px; height: 38px; border-radius: 50%; object-fit: cover;
            border: 2px solid #38bdf8; flex-shrink: 0; background: #334155;
        }
        .top-nav-search {
            flex: 1; background: #1e293b; border: 1px solid #334155;
            border-radius: 20px; padding: 8px 16px; color: #f8fafc; font-size: 0.85rem; outline: none;
        }
        
        .container { max-width: 900px; margin: 0 auto; padding: 16px; }
        .header-title { font-size: 1.25rem; font-weight: 700; color: #f8fafc; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; }
        
        .card {
            background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(8px);
            border: 1px solid #334155; border-radius: 12px; padding: 16px; margin-bottom: 14px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); cursor: pointer;
        }
        .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
        .card-title { font-size: 1rem; font-weight: 600; color: #38bdf8; text-decoration: none; }
        .card-company { font-size: 0.85rem; color: #94a3b8; margin-top: 2px; }
        
        .badge { font-size: 0.72rem; font-weight: 700; padding: 4px 10px; border-radius: 20px; display: inline-block; }
        .badge-match { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
        .badge-submitted { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
        .badge-salary { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); margin-top: 6px; }
        .badge-category { background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }

        .btn {
            width: 100%; border: none; padding: 10px 14px; border-radius: 8px; font-weight: 600;
            font-size: 0.85rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;
            margin-top: 10px; transition: background 0.2s; text-decoration: none;
        }
        .btn-primary { background: #10b981; color: #022c22; }
        .btn-revert { background: #dc2626; color: #ffffff; padding: 6px 12px; font-size: 0.75rem; border-radius: 6px; width: auto; }

        /* Modern Chat Bar */
        .chat-display-card {
            background: #0f172a; border: 1px solid #334155; border-radius: 16px;
            padding: 16px; min-height: 280px; font-size: 0.9rem; color: #e2e8f0; line-height: 1.5; white-space: pre-wrap;
            margin-bottom: 20px;
        }
        .chat-input-bar-container {
            background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(12px);
            border: 1px solid #334155; border-radius: 28px; padding: 6px 10px;
            display: flex; align-items: center; gap: 8px;
        }
        .chat-add-btn {
            width: 38px; height: 38px; border-radius: 50%; border: none;
            background: transparent; color: #94a3b8; font-size: 1.3rem;
            display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0;
        }
        .chat-text-input {
            flex: 1; background: transparent; border: none; outline: none;
            color: #f8fafc; font-size: 0.92rem; padding: 8px 4px;
        }
        .chat-send-btn {
            width: 38px; height: 38px; border-radius: 50%; border: none;
            background: #38bdf8; color: #0f172a; font-size: 1.1rem; font-weight: 800;
            display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0;
        }

        /* Bottom Attachment Menu Modal */
        .bottom-drawer-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px); z-index: 2500; display: none; align-items: flex-end; justify-content: center;
        }
        .bottom-drawer-card {
            background: #0f172a; border-top: 1px solid #334155; border-radius: 24px 24px 0 0;
            width: 100%; max-width: 600px; padding: 24px 16px 32px 16px;
        }
        .drawer-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; text-align: center; }
        .drawer-item { display: flex; flex-direction: column; align-items: center; gap: 6px; cursor: pointer; }
        .drawer-icon-box {
            width: 58px; height: 58px; border-radius: 50%; background: #1e293b; border: 1px solid #334155;
            display: flex; align-items: center; justify-content: center; font-size: 1.4rem; color: #38bdf8;
        }
        .drawer-label { font-size: 0.75rem; color: #cbd5e1; font-weight: 500; }

        .bottom-nav-bar {
            position: fixed; bottom: 0; left: 0; right: 0; z-index: 1000;
            background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(12px);
            border-top: 1px solid #1e293b; display: flex; justify-content: space-around; padding: 8px 0;
        }
        .bottom-nav-item {
            display: flex; flex-direction: column; align-items: center; color: #94a3b8;
            text-decoration: none; font-size: 0.68rem; font-weight: 500; position: relative; width: 20%;
        }
        .bottom-nav-item.active { color: #38bdf8; font-weight: 700; }
        .bottom-nav-icon { font-size: 1.25rem; margin-bottom: 2px; }
        
        .modal-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(8px); z-index: 2000; display: none; align-items: center; justify-content: center; padding: 16px;
        }
        .modal-card {
            background: #0f172a; border: 1px solid #334155; border-radius: 16px; width: 100%; max-width: 500px; padding: 20px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5); max-height: 85vh; overflow-y: auto; -webkit-overflow-scrolling: touch;
        }
        .modal-input { width: 100%; background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px; color: #f8fafc; font-size: 0.85rem; margin-top: 8px; }
        .cover-box { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 0.78rem; color: #94a3b8; white-space: pre-wrap; max-height: 140px; overflow-y: auto; margin-top: 8px; }

        .profile-cover-box {
            position: relative; width: 100%; height: 140px; background-size: cover; background-position: center;
            background-image: url('{{ profile.cover_url }}'), linear-gradient(135deg, #0284c7, #0f172a);
            border-radius: 12px 12px 0 0; overflow: hidden;
        }
        .cover-camera-badge {
            position: absolute; top: 10px; right: 10px; width: 34px; height: 34px;
            background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(4px); border: 1px solid #38bdf8;
            border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 0.95rem; cursor: pointer;
        }
        .avatar-camera-container { position: relative; display: inline-block; margin-top: -45px; }
        .camera-overlay-badge {
            position: absolute; bottom: 2px; right: 2px; width: 32px; height: 32px;
            background: #0284c7; border: 2px solid #0f172a; border-radius: 50%;
            display: flex; align-items: center; justify-content: center; color: white; font-size: 0.9rem; cursor: pointer;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        }
    </style>
</head>
<body>

    <div class="top-nav-bar">
        <a href="/profile"><img src="{{ profile.avatar_url }}" class="top-nav-avatar" alt="Profile" onerror="this.src='https://ui-avatars.com/api/?name=Ezenwa+Christian&background=38bdf8&color=0f172a&size=128';"></a>
        <input type="text" class="top-nav-search" placeholder="Search applications, skills, companies...">
    </div>

    <div class="container">
        {% if page == 'kanban' %}
            <div class="header-title">
                <span>⚡ Active Pipeline ({{ active_apps|length }})</span>
                {% if active_apps|length > 0 %}
                    <span class="badge badge-match" style="background: rgba(239, 68, 68, 0.2); color: #f87171; border-color: rgba(239, 68, 68, 0.4);">Search Blocker Active</span>
                {% endif %}
            </div>

            {% for app in active_apps %}
                <div class="card" onclick="triggerSubmitReviewModal('{{ app[0] }}')">
                    <div class="card-header">
                        <div>
                            <div class="card-title">{{ app[1] }}</div>
                            <div class="card-company">🏢 {{ app[2] }}</div>
                        </div>
                        <span class="badge badge-match">🎯 {{ app[4] }} Match</span>
                    </div>
                    {% if app[3] and app[3] != 'Not Specified' %}
                        <div class="badge badge-salary">💰 {{ app[3] }}</div>
                    {% endif %}
                    <button class="btn btn-primary" style="margin-top: 12px;">
                        📖 Read Details & Open Application Page
                    </button>
                </div>
            {% else %}
                <div class="card" style="text-align: center; color: #94a3b8;">
                    No active applications sitting right now. Search engine ready!
                </div>
            {% endfor %}

        {% elif page == 'jobs_archive' %}
            <div class="header-title">💼 Application Analytics & History</div>
            
            <div class="metrics-grid">
                <div class="metric-box">
                    <div class="metric-val">{{ submitted_apps|length }}</div>
                    <div class="metric-lbl">Total Submitted</div>
                </div>
                <div class="metric-box">
                    <div class="metric-val">100%</div>
                    <div class="metric-lbl">Target Direct Match</div>
                </div>
            </div>

            <div class="header-title" style="font-size: 1rem;">✅ Applications Submitted ({{ submitted_apps|length }})</div>
            {% for app in submitted_apps %}
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title" style="color: #cbd5e1;">{{ app[1] }}</div>
                            <div class="card-company">🏢 {{ app[2] }}</div>
                        </div>
                        <span class="badge badge-submitted">SUBMITTED</span>
                    </div>
                    {% if app[3] and app[3] != 'Not Specified' %}
                        <div class="badge badge-salary">💰 {{ app[3] }}</div>
                    {% endif %}
                    <form action="/revert_app/{{ app[0] }}" method="POST" style="margin-top: 10px;">
                        <button type="submit" class="btn btn-revert">↩️ Revert to Active</button>
                    </form>
                </div>
            {% else %}
                <div class="card" style="text-align: center; color: #94a3b8;">
                    No submitted applications yet. Apply to jobs from your Home tab!
                </div>
            {% endfor %}

        {% elif page == 'inbox' %}
            <div class="header-title">📩 Live Gmail Response Tracker</div>
            <div class="card">
                <p style="font-size: 0.85rem; color: #cbd5e1; margin-bottom: 12px;">
                    I monitor your connected Gmail account for direct recruitment responses, confirmation letters, or interview invitations.
                </p>
                <a href="/sync_gmail" class="btn btn-primary" style="background: #38bdf8; color: #0f172a;">
                    🔄 Sync Gmail Inbox Now
                </a>
            </div>

            <div class="header-title" style="font-size: 1rem; margin-top: 20px;">📬 Filtered Recruiter Emails ({{ emails|length }})</div>
            {% for em in emails %}
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title" style="font-size: 0.9rem; color: #f8fafc;">{{ em[2] }}</div>
                            <div class="card-company">From: {{ em[1] }}</div>
                        </div>
                        <span class="badge badge-category">{{ em[3] }}</span>
                    </div>
                    <p style="font-size: 0.8rem; color: #94a3b8; margin-top: 6px;">{{ em[4] }}</p>
                    {% if em[5] %}
                        <div style="margin-top: 10px; border-top: 1px solid #334155; padding-top: 8px;">
                            <strong style="font-size: 0.78rem; color: #38bdf8;">Suggested Draft Reply (Manual Review):</strong>
                            <div class="cover-box">{{ em[5] }}</div>
                        </div>
                    {% endif %}
                </div>
            {% else %}
                <div class="card" style="text-align: center; color: #94a3b8;">
                    No new recruitment emails detected in sync. Tap 'Sync Gmail Inbox Now' to check.
                </div>
            {% endfor %}

        {% elif page == 'ai_assistant' %}
            <div class="header-title" style="position: relative; display: flex; justify-content: space-between; align-items: center;">
                <span>🤖 AI Career Assistant</span>
                <button type="button" onclick="toggleHistoryMenu()" style="background: none; border: none; color: #38bdf8; font-size: 1.5rem; cursor: pointer; padding: 2px 8px;" title="Chat Menu">⋮</button>
                
                <!-- Three Dots Dropdown Menu -->
                <div id="history-dropdown" style="position: absolute; right: 0; top: 40px; background: #0f172a; border: 1px solid #334155; border-radius: 12px; width: 240px; padding: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.6); display: none; z-index: 2000;">
                    <div style="font-size: 0.8rem; font-weight: 700; color: #38bdf8; margin-bottom: 8px; border-bottom: 1px solid #334155; padding-bottom: 4px;">💬 Chat History & Actions</div>
                    <div style="max-height: 140px; overflow-y: auto; margin-bottom: 8px; font-size: 0.75rem; color: #94a3b8;">
                        {% if history %}
                            {% for mid, s, m in history %}
                                <div style="margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">• {{ m[:35] }}</div>
                            {% endfor %}
                        {% else %}
                            <div>No conversation history yet.</div>
                        {% endif %}
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 6px; border-top: 1px solid #334155; padding-top: 8px;">
                        <a href="/export_chat/json" style="font-size: 0.75rem; color: #38bdf8; text-decoration: none;">📥 Export JSON</a>
                        <a href="/export_chat/md" style="font-size: 0.75rem; color: #38bdf8; text-decoration: none;">📥 Export Markdown</a>
                        <form action="/clear_chat" method="POST" onsubmit="return confirm('Are you sure you want to delete all chat history?');">
                            <button type="submit" style="width: 100%; background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 6px; padding: 6px; font-size: 0.75rem; cursor: pointer;">🗑️ Delete History</button>
                        </form>
                    </div>
                </div>
            </div>

            <!-- Chat Container with Right/Left Bubbles -->
            <div id="chat-container" style="background: #0f172a; border: 1px solid #334155; border-radius: 16px; padding: 14px; min-height: 300px; max-height: 480px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px;">
                {% if history %}
                    {% for sender, msg in history %}
                        {% if sender == 'user' %}
                            <div style="background: #0284c7; color: #f8fafc; padding: 10px 14px; border-radius: 16px 16px 4px 16px; max-width: 82%; align-self: flex-end; font-size: 0.88rem; position: relative; padding-right: 35px; word-break: break-word;">
                                👤 {{ msg }}
                                <form action="/delete_msg/{{ msg._id }}" method="POST" style="position: absolute; bottom: 4px; right: 6px;">
                                    <button type="submit" style="background: none; border: none; color: #fca5a5; font-size: 0.65rem; cursor: pointer;" title="Delete">🗑️</button>
                                </form>
                            </div>
                        {% else %}
                            <div style="background: #1e293b; color: #cbd5e1; padding: 10px 14px; border-radius: 16px 16px 16px 4px; max-width: 82%; align-self: flex-start; font-size: 0.88rem; border: 1px solid #334155; position: relative; padding-right: 55px; word-break: break-word;">
                                🤖 {{ msg }}
                                <div style="position: absolute; bottom: 4px; right: 6px; display: flex; gap: 4px;">
                                    <button type="button" onclick="speakText('{{ msg | replace("'", "\'") }}')" style="background: none; border: none; color: #38bdf8; font-size: 0.65rem; cursor: pointer;" title="Read Aloud">🔊</button>
                                    <button type="button" onclick="navigator.clipboard.writeText('{{ msg | replace("'", "\'") }}'); alert('Copied!');" style="background: none; border: none; color: #38bdf8; font-size: 0.65rem; cursor: pointer;" title="Copy">📋</button>
                                    <form action="/delete_msg/{{ loop.index }}" method="POST">
                                        <button type="submit" style="background: none; border: none; color: #fca5a5; font-size: 0.65rem; cursor: pointer;" title="Delete">🗑️</button>
                                    </form>
                                </div>
                            </div>
                        {% endif %}
                    {% endfor %}
                {% else %}
                    <div style="background: #1e293b; color: #cbd5e1; padding: 10px 14px; border-radius: 16px; max-width: 85%; align-self: flex-start; font-size: 0.88rem; border: 1px solid #334155;">
                        🤖 No wahala, my brother! I am your senior AI career assistant. Ask me anything or tap '+' to upload a file!
                    </div>
                {% endif %}
            </div>

            <!-- Prompt Chips & Style Selector -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="display: flex; gap: 4px; overflow-x: auto; max-width: 75%;">
                    <button type="button" class="badge" style="background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 4px 8px; cursor: pointer; white-space: nowrap;" onclick="setQuery('Review my CV and suggest high-impact improvements')">📄 Review CV</button>
                    <button type="button" class="badge" style="background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 4px 8px; cursor: pointer; white-space: nowrap;" onclick="setQuery('Draft a cover letter for my Full-Stack / Technical Writer profile')">✍️ Cover Letter</button>
                    <button type="button" class="badge" style="background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 4px 8px; cursor: pointer; white-space: nowrap;" onclick="setQuery('Generate technical interview questions for Python/FastAPI')">🎯 Mock Interview</button>
                </div>
                <select name="style" form="ai-chat-form" style="background: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 6px; padding: 4px 6px; font-size: 0.7rem;">
                    <option value="balanced">⚖️ Balanced</option>
                    <option value="concise">⚡ Concise</option>
                    <option value="detailed">📑 Detailed</option>
                </select>
            </div>

            <!-- Input Bar Form -->
            <form id="ai-chat-form" action="/ai_assistant" method="POST" enctype="multipart/form-data">
                <input type="file" id="ai-file-input" name="file" style="display:none;" onchange="document.getElementById('ai-chat-form').submit();">
                
                <div class="chat-input-bar-container">
                    <button type="button" class="chat-add-btn" onclick="openAttachmentDrawer()" title="Open Attachment Menu">+</button>
                    <button type="button" class="chat-add-btn" onclick="startVoiceDictation()" title="Voice Dictation" style="color:#38bdf8;">🎤</button>
                    <textarea id="main-chat-input" class="modern-composer" rows="1" placeholder="Ask Career Agency anything..."></textarea>
                    <button type="submit" class="chat-send-btn" title="Send">↑</button>
                </div>
            </form>

            <script>
                function toggleHistoryMenu() {
                    var menu = document.getElementById("history-dropdown");
                    menu.style.display = (menu.style.display === "block") ? "none" : "block";
                }
                function setQuery(text) {
                    document.getElementById("query-input").value = text;
                    document.getElementById("query-input").focus();
                }
                function speakText(text) {
                    if ('speechSynthesis' in window) {
                        window.speechSynthesis.cancel();
                        var utterance = new SpeechSynthesisUtterance(text);
                        window.speechSynthesis.speak(utterance);
                    } else {
                        alert('Speech synthesis not supported.');
                    }
                }
                function startVoiceDictation() {
                    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                        var recognition = new SpeechRecognition();
                        recognition.lang = 'en-US';
                        recognition.onstart = function() { alert('Listening...'); };
                        recognition.onresult = function(event) {
                            document.getElementById('query-input').value = event.results[0][0].transcript;
                        };
                        recognition.start();
                    } else {
                        alert('Speech recognition not supported.');
                    }
                }
                window.onload = function() {
                    var container = document.getElementById("chat-container");
                    if(container) container.scrollTop = container.scrollHeight;
                }
            </script>
        {% elif page == 'profile' %}
            <div class="header-title">⚙️ Enterprise Hub Profile</div>
            <div class="card" style="padding: 0; overflow: hidden;">
                <form id="cover-overlay-form" action="/upload_cover" method="POST" enctype="multipart/form-data" style="display:none;">
                    <input type="file" id="cover-file-input" name="cover" accept="image/*" onchange="document.getElementById('cover-overlay-form').submit();">
                </form>
                <div class="profile-cover-box">
                    <label for="cover-file-input" class="cover-camera-badge" title="Change Cover Banner">📷</label>
                </div>

                <div style="text-align: center; padding: 0 16px 16px 16px; position: relative; z-index: 2;">
                    <form id="avatar-overlay-form" action="/upload_avatar" method="POST" enctype="multipart/form-data" style="display:none;">
                        <input type="file" id="overlay-file-input" name="avatar" accept="image/*" onchange="document.getElementById('avatar-overlay-form').submit();">
                    </form>
                    <div class="avatar-camera-container">
                        <img src="{{ profile.avatar_url }}" style="width: 90px; height: 90px; border-radius: 50%; border: 3px solid #38bdf8; object-fit: cover; background: #1e293b;" onerror="this.src='https://ui-avatars.com/api/?name=Ezenwa+Christian&background=38bdf8&color=0f172a&size=128';">
                        <label for="overlay-file-input" class="camera-overlay-badge" title="Upload Picture from Gallery">📷</label>
                    </div>
                    <h2 style="margin-top: 8px; color: #f8fafc; font-size: 1.1rem; font-weight: 700;">{{ profile.full_name }}</h2>
                    <p style="font-size: 0.8rem; color: #38bdf8; font-weight: 600; margin-top: 2px;">{{ profile.headline }}</p>
                    <p style="font-size: 0.78rem; color: #94a3b8; margin-top: 4px;">📍 {{ profile.origin }}</p>
                </div>

                <div style="padding: 16px; border-top: 1px solid #334155;">
                    <h4 style="color: #38bdf8; font-size: 0.85rem; margin-bottom: 6px;">📝 Professional Summary</h4>
                    <p style="font-size: 0.82rem; color: #cbd5e1; line-height: 1.4;">{{ profile.summary }}</p>
                </div>

                <div style="padding: 16px; border-top: 1px solid #334155;">
                    <h4 style="color: #38bdf8; font-size: 0.85rem; margin-bottom: 6px;">🛠️ Technical Stack & Skills</h4>
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px;">
                        {% for skill in profile.tech_skills %}
                            <span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);">{{ skill }}</span>
                        {% endfor %}
                    </div>
                    <form action="/update_skills" method="POST" style="display: flex; gap: 6px; margin-top: 8px;">
                        <input type="text" name="skills" class="modal-input" style="margin-top:0; font-size: 0.78rem;" placeholder="Python, FastAPI, TypeScript..." value="{{ profile.tech_skills|join(', ') }}">
                        <button type="submit" class="btn btn-primary" style="width: auto; margin-top:0; font-size: 0.75rem; white-space: nowrap;">Save Skills</button>
                    </form>
                </div>

                <div style="padding: 16px; border-top: 1px solid #334155;">
                    <h4 style="color: #38bdf8; font-size: 0.85rem; margin-bottom: 6px;">🚀 Core Engineering & AI Projects</h4>
                    {% for proj in profile.projects %}
                        <div style="margin-bottom: 8px;">
                            <strong style="color: #f8fafc; font-size: 0.82rem;">• {{ proj.name }}:</strong>
                            <p style="font-size: 0.78rem; color: #94a3b8;">{{ proj.desc }}</p>
                        </div>
                    {% endfor %}
                </div>

                <div style="padding: 16px; border-top: 1px solid #334155;">
                    <h4 style="color: #38bdf8; font-size: 0.85rem; margin-bottom: 6px;">🌐 Public Profiles & Links</h4>
                    <p style="font-size: 0.8rem; color: #cbd5e1;"><b>Portfolio:</b> <a href="{{ profile.portfolio }}" target="_blank" style="color: #38bdf8;">{{ profile.portfolio }}</a></p>
                    <p style="font-size: 0.8rem; color: #cbd5e1; margin-top: 4px;"><b>Medium:</b> <a href="{{ profile.medium }}" target="_blank" style="color: #38bdf8;">{{ profile.medium }}</a></p>
                    <p style="font-size: 0.8rem; color: #cbd5e1; margin-top: 4px;"><b>GitHub:</b> <a href="{{ profile.github }}" target="_blank" style="color: #38bdf8;">{{ profile.github }}</a></p>
                    <p style="font-size: 0.8rem; color: #cbd5e1; margin-top: 4px;"><b>Email:</b> {{ profile.email }}</p>
                </div>
            </div>
        {% endif %}
    </div>

    <!-- Direct Application Form & Details Modal -->
    <div id="submit-modal" class="modal-overlay">
        <div class="modal-card">
            <div class="modal-title">🚀 Job Details & Application Dispatch</div>
            <div class="modal-body">
                <div style="margin-bottom: 12px;">
                    <h3 id="review-title" style="color:#38bdf8; font-size: 1.1rem;">Job Title</h3>
                    <div id="review-company" style="color:#f8fafc; font-size: 0.9rem; margin-top: 2px;">Company</div>
                    <div id="review-salary" class="badge badge-salary" style="margin-top: 6px;">Salary</div>
                </div>
                
                <div style="margin-top: 12px; border-top: 1px solid #334155; padding-top: 10px;">
                    <div><b>Applicant:</b> <span id="review-name">EZENWA CHRISTIAN CHIMEREMEZE</span></div>
                    <div><b>Email:</b> <span id="review-email">ezenwachristian413@gmail.com</span></div>
                </div>
                
                <div style="margin-top: 12px;"><b>Tailored Cover Letter & Pitch:</b></div>
                <div class="cover-box" id="review-cover">Cover letter text loading...</div>
                
                <div style="margin-top: 14px;"><b>Target Direct Application Search Dispatch URL:</b></div>
                <form id="submit-form" method="POST" target="_blank" onsubmit="setTimeout(() => { location.reload(); }, 1000);">
                    <input type="text" id="job-url-input" name="job_url" class="modal-input" readonly>
                    <button type="submit" class="btn btn-primary" style="margin-top: 14px;">
                        🌐 Open Application Search & Mark Applied
                    </button>
                    <button type="button" class="btn" onclick="closeSubmitModal()" style="background: #334155; color: white; margin-top: 8px;">
                        Close Details
                    </button>
                </form>
            </div>
        </div>
    </div>

    <div class="bottom-nav-bar">
        <a href="/" class="bottom-nav-item {% if page == 'kanban' %}active{% endif %}">
            <span class="bottom-nav-icon">🏠</span>
            <span>Home</span>
        </a>
        <a href="/jobs" class="bottom-nav-item {% if page == 'jobs_archive' %}active{% endif %}">
            <span class="bottom-nav-icon">💼</span>
            <span>Jobs</span>
        </a>
        <a href="/inbox" class="bottom-nav-item {% if page == 'inbox' %}active{% endif %}">
            <span class="bottom-nav-icon">📩</span>
            <span>Inbox</span>
        </a>
        <a href="/ai_assistant" class="bottom-nav-item {% if page == 'ai_assistant' %}active{% endif %}">
            <span class="bottom-nav-icon">🤖</span>
            <span>AI Coach</span>
        </a>
        <a href="/profile" class="bottom-nav-item {% if page == 'profile' %}active{% endif %}">
            <span class="bottom-nav-icon">⚙️</span>
            <span>Profile</span>
        </a>
    </div>

    <script>
        function openAttachmentDrawer() {
            document.getElementById("attachment-drawer").style.display = "flex";
        }
        function closeAttachmentDrawer(e) {
            document.getElementById("attachment-drawer").style.display = "none";
        }
        function triggerFileUpload() {
            closeAttachmentDrawer();
            document.getElementById("ai-file-input").click();
        }

        function triggerSubmitReviewModal(appId) {
            fetch("/autofill/" + appId)
                .then(res => res.json())
                .then(data => {
                    document.getElementById("review-company").innerText = "🏢 " + data.company;
                    document.getElementById("review-title").innerText = data.title;
                    document.getElementById("review-salary").innerText = "💰 " + (data.salary || "Competitive");
                    document.getElementById("review-cover").innerText = data.mapped_fields.cover_letter_body;
                    document.getElementById("job-url-input").value = data.job_url;
                    document.getElementById("submit-form").action = "/confirm_submit/" + appId;
                    document.getElementById("submit-modal").style.display = "flex";
                })
                .catch(err => {
                    alert("Unable to fetch job details. Please try again.");
                });
        }

        function closeSubmitModal() {
            document.getElementById("submit-modal").style.display = "none";
        }
    
        function previewAttachment(input) {
            if (input.files && input.files[0]) {
                var reader = new FileReader();
                reader.onload = function(e) {
                    document.getElementById("preview-img").src = e.target.result;
                    document.getElementById("attachment-preview").style.display = "block";
                }
                reader.readAsDataURL(input.files[0]);
            }
        }


        function setQuery(text) {
            document.getElementById("query-input").value = text;
            document.getElementById("query-input").focus();
        }


        function startVoiceDictation() {
            if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                var recognition = new SpeechRecognition();
                recognition.lang = 'en-US';
                recognition.onstart = function() { alert('Listening... Speak now.'); };
                recognition.onresult = function(event) {
                    document.getElementById('query-input').value = event.results[0][0].transcript;
                };
                recognition.start();
            } else {
                alert('Speech recognition is not supported in this browser.');
            }
        }


        function speakText(text) {
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                var utterance = new SpeechSynthesisUtterance(text);
                window.speechSynthesis.speak(utterance);
            } else {
                alert('Speech synthesis not supported in this browser.');
            }
        }

</script>

    <!-- Injected Plus Button Menu -->
    <div id="plus-menu" style="display: none; position: absolute; bottom: 90px; left: 20px; background: #2a2a35; padding: 15px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); z-index: 1000;">
       <button onclick="document.getElementById('file-upload').click()" style="background: none; border: 1px solid #555; color: white; padding: 8px 12px; border-radius: 5px; cursor: pointer; margin-bottom: 5px; width: 100%;">📁 Upload File</button>
       <input type="file" id="file-upload" style="display: none;">
       <button onclick="document.getElementById('plus-menu').style.display='none'" style="background: none; border: none; color: #ff6b6b; cursor: pointer; font-size: 12px; margin-top: 5px; width: 100%;">Cancel</button>
    </div>

    <!-- Injected JavaScript for Mic and Plus Icon -->
    <script>
      document.addEventListener('DOMContentLoaded', () => {
        // 1. MICROPHONE FIX
        // Try to find the mic icon by common class names or IDs
        const micBtn = document.querySelector('[class*="microphone"]') || document.querySelector('[class*="mic"]') || document.getElementById('mic-btn');
        const chatInput = document.querySelector('input[type="text"]') || document.querySelector('textarea');
        
        if (micBtn && chatInput) {
          const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
          if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            
            micBtn.addEventListener('click', (e) => {
              e.preventDefault();
              try {
                recognition.start();
                micBtn.style.color = "red"; 
              } catch(err) {
                alert("Mic is already listening.");
              }
            });
            
            recognition.onresult = (event) => {
              chatInput.value = event.results[0][0].transcript;
              micBtn.style.color = "";
            };
            
            recognition.onerror = (event) => {
              console.error("Speech error:", event.error);
              if(event.error === 'not-allowed') {
                  alert("Microphone blocked by browser. You MUST use http://127.0.0.1:5000 instead of the IP address, or use HTTPS.");
              }
              micBtn.style.color = "";
            };
            
            recognition.onend = () => { micBtn.style.color = ""; };
          } else {
            micBtn.addEventListener('click', () => alert("Speech recognition not supported in this browser."));
          }
        }

        // 2. PLUS ICON FIX
        const plusBtn = document.querySelector('[class*="plus"]') || document.getElementById('plus-btn');
        const plusMenu = document.getElementById('plus-menu');
        
        if (plusBtn && plusMenu) {
          plusBtn.addEventListener('click', (e) => {
            e.preventDefault();
            // Toggle menu visibility
            plusMenu.style.display = plusMenu.style.display === 'none' ? 'block' : 'none';
          });
        }
      });
    </script>

<!-- ========================================== -->
<!-- CAREER AGENCY UPGRADED CHAT UI & SCRIPTS   -->
<!-- ========================================== -->
<style>
    /* Responsive Composer Layout */
    .chat-container { display: flex; flex-direction: column; height: 100dvh; }
    .chat-messages { flex: 1; overflow-y: auto; padding-bottom: 120px; /* space for composer */ }
    .composer-wrapper {
        position: fixed;
        bottom: 0; left: 0; right: 0;
        background: #1e1e24; /* Match existing dark theme */
        border-top: 1px solid #333;
        padding: 10px 15px calc(10px + env(safe-area-inset-bottom));
        z-index: 1000;
        display: flex; gap: 8px; align-items: flex-end;
    }
    .composer-input {
        flex: 1; background: #2a2a35; border: 1px solid #444; color: white;
        border-radius: 20px; padding: 12px 15px; resize: none; max-height: 150px;
        font-family: inherit; outline: none; overflow-y: auto;
    }
    .icon-btn {
        background: none; border: none; font-size: 20px; cursor: pointer;
        padding: 8px; color: #aaa; transition: color 0.2s; display: flex;
        align-items: center; justify-content: center; border-radius: 50%;
    }
    .icon-btn:hover { background: #333; color: #fff; }
    .icon-btn.active { color: #ff4d4d; background: rgba(255, 77, 77, 0.1); }
    
    /* Message Actions */
    .msg-actions { display: flex; gap: 8px; margin-top: 5px; opacity: 0.7; transition: opacity 0.2s; }
    .msg-actions:hover { opacity: 1; }
    .msg-actions button { background: none; border: none; color: #888; cursor: pointer; font-size: 12px; }
    .msg-actions button:hover { color: #fff; }
</style>

<script>
document.addEventListener('DOMContentLoaded', () => {
    // 1. AUTO-RESIZE TEXTAREA
    const chatInput = document.querySelector('textarea, input[type="text"]');
    if (chatInput) {
        chatInput.classList.add('composer-input');
        chatInput.placeholder = "Ask Career Agency anything...";
        if (chatInput.tagName === 'INPUT') {
            const newTextarea = document.createElement('textarea');
            newTextarea.className = chatInput.className;
            newTextarea.placeholder = chatInput.placeholder;
            newTextarea.rows = 1;
            chatInput.parentNode.replaceChild(newTextarea, chatInput);
            window.chatInput = newTextarea;
        } else {
            window.chatInput = chatInput;
        }
        window.chatInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
    }

    // 2. SPEECH TO TEXT (MIC)
    const micBtn = Array.from(document.querySelectorAll('button, span')).find(el => el.textContent.includes('🎤'));
    if (micBtn && window.chatInput) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;

            micBtn.addEventListener('click', (e) => {
                e.preventDefault();
                try {
                    recognition.start();
                    micBtn.classList.add('active');
                } catch(e) { alert("Mic is already listening."); }
            });

            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                window.chatInput.value += (window.chatInput.value ? " " : "") + transcript;
                micBtn.classList.remove('active');
            };

            recognition.onerror = (event) => {
                micBtn.classList.remove('active');
                if (event.error === 'not-allowed') {
                    alert("Microphone blocked. You must use http://127.0.0.1:5000 on your phone, not the network IP.");
                }
            };
            recognition.onend = () => micBtn.classList.remove('active');
        } else {
            micBtn.addEventListener('click', () => alert("Speech recognition not supported in this browser."));
        }
    }

    // 3. PLUS ICON / ATTACHMENTS
    const plusBtn = Array.from(document.querySelectorAll('button, span')).find(el => el.textContent.trim() === '+');
    if (plusBtn) {
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.style.display = 'none';
        fileInput.accept = "image/*,.pdf,.doc,.docx,.txt";
        document.body.appendChild(fileInput);
        
        plusBtn.addEventListener('click', (e) => {
            e.preventDefault();
            fileInput.click();
        });
        
        fileInput.addEventListener('change', (e) => {
            if(e.target.files.length > 0) {
                alert(`Selected file: ${e.target.files[0].name}\n(File upload backend logic required to process this)`);
            }
        });
    }

    // 4. TEXT TO SPEECH (Read Aloud) & COPY
    // Add actions to all existing and future AI messages
    function attachMessageActions() {
        // Assuming AI messages have a specific class or background color from your screenshot
        const aiMessages = document.querySelectorAll('.message, .msg'); // Update this selector based on your HTML
        aiMessages.forEach(msg => {
            if (msg.querySelector('.msg-actions')) return; // Already processed
            
            // Only add to AI messages (adjust logic based on your sender check)
            if (msg.innerHTML.includes('🤖')) { 
                const actionBar = document.createElement('div');
                actionBar.className = 'msg-actions';
                actionBar.innerHTML = `
                    <button onclick="copyText(this)">📋 Copy</button>
                    <button onclick="speakText(this)">🔊 Read</button>
                `;
                msg.appendChild(actionBar);
            }
        });
    }
    
    // Run on load and observe DOM changes for new messages
    attachMessageActions();
    const observer = new MutationObserver(attachMessageActions);
    observer.observe(document.body, { childList: true, subtree: true });

    // Helper Functions
    window.copyText = function(btn) {
        const text = btn.closest('.message, .msg').innerText.replace(/📋 Copy|🔊 Read/g, '').trim();
        navigator.clipboard.writeText(text).then(() => {
            btn.innerText = '✅ Copied';
            setTimeout(() => btn.innerText = '📋 Copy', 2000);
        });
    };

    window.speakText = function(btn) {
        if (window.speechSynthesis.speaking) {
            window.speechSynthesis.cancel();
            return;
        }
        const text = btn.closest('.message, .msg').innerText.replace(/📋 Copy|🔊 Read/g, '').trim();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.onstart = () => btn.innerText = '⏹ Stop';
        utterance.onend = () => btn.innerText = '🔊 Read';
        window.speechSynthesis.speak(utterance);
    };
});
</script>

<script>
document.addEventListener('DOMContentLoaded', () => {
    // Find the form, the input box, and the chat message area
    const form = document.querySelector('form');
    const input = document.getElementById('main-chat-input') || document.querySelector('textarea, input[type="text"]');
    
    // Find the container where messages appear
    const chatContainer = document.querySelector('.chat-container') || document.querySelector('.messages') || document.querySelector('main') || document.body;

    if (form && input) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault(); // STOP the page from reloading!
            
            const msg = input.value.trim();
            if (!msg) return;

            // 1. Add user message to the screen
            chatContainer.innerHTML += `<div style="background: #2a2a35; padding: 15px; margin: 10px 0; border-radius: 10px; align-self: flex-end;"><b>You:</b><br>${msg}</div>`;
            input.value = ''; // Clear input
            input.style.height = 'auto';

            // 2. Show "Thinking..." message
            const loadingId = 'loading-' + Date.now();
            chatContainer.innerHTML += `<div id="${loadingId}" style="background: #1e1e24; padding: 15px; margin: 10px 0; border-radius: 10px;"><b>AI:</b><br><span class="spinner">Thinking...</span></div>`;
            chatContainer.scrollTop = chatContainer.scrollHeight;

            try {
                // 3. Send message to backend silently
                const response = await fetch('/ai_assistant', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg })
                });
                
                const data = await response.json();
                
                // 4. Replace "Thinking..." with actual AI response
                const loadingEl = document.getElementById(loadingId);
                if (loadingEl) {
                    loadingEl.innerHTML = `<b>AI:</b><br>${data.reply}`;
                }
            } catch (err) {
                console.error(err);
                const loadingEl = document.getElementById(loadingId);
                if (loadingEl) {
                    loadingEl.innerHTML = `<b>AI:</b><br><span style="color:red;">Error connecting to server. Check Termux terminal.</span>`;
                }
            }
            chatContainer.scrollTop = chatContainer.scrollHeight;
        });
    }
});
</script>


<script>
document.addEventListener('DOMContentLoaded', () => {
    // Wait slightly for your UI to render
    setTimeout(() => {
        // 1. FIND ELEMENTS
        const form = document.querySelector('form');
        const input = document.querySelector('textarea') || document.querySelector('input[type="text"]');
        
        // Find the Send button (looks for the blue arrow or type="submit")
        const sendBtn = document.querySelector('button[type="submit"]') || document.querySelector('.send-btn') || Array.from(document.querySelectorAll('button, div')).find(el => el.innerHTML.includes('↑'));
        
        // Find the chat message area
        const chatBox = document.querySelector('.chat-container') || document.querySelector('.messages') || document.querySelector('main') || document.body;

        // 2. CREATE CHAT BUBBLES FUNCTION
        window.appendMessage = function(sender, text) {
            const msgDiv = document.createElement('div');
            msgDiv.style.display = 'flex';
            msgDiv.style.flexDirection = 'column';
            msgDiv.style.margin = '15px 0';
            msgDiv.style.alignItems = sender === 'user' ? 'flex-end' : 'flex-start';
            
            const bubble = document.createElement('div');
            bubble.style.background = sender === 'user' ? '#007bff' : '#2a2a35'; // Blue for you, Dark Gray for AI
            bubble.style.color = 'white';
            bubble.style.padding = '12px 16px';
            bubble.style.borderRadius = '18px';
            bubble.style.maxWidth = '85%';
            bubble.style.fontSize = '15px';
            bubble.style.lineHeight = '1.4';
            bubble.innerHTML = text;
            
            // Add Read Aloud button to AI messages
            if (sender === 'ai') {
                const controls = document.createElement('div');
                controls.style.marginTop = '5px';
                controls.innerHTML = `<button onclick="readAloud(this)" style="background:none; border:none; color:#888; cursor:pointer; font-size:12px;">🔊 Read Aloud</button>`;
                msgDiv.appendChild(bubble);
                msgDiv.appendChild(controls);
            } else {
                msgDiv.appendChild(bubble);
            }
            
            chatBox.appendChild(msgDiv);
            chatBox.scrollTop = chatBox.scrollHeight;
            return msgDiv;
        };

        // 3. INTERCEPT FORM SUBMIT (STOP THE CRASH)
        if (form) {
            form.addEventListener('submit', (e) => {
                e.preventDefault(); // STOPS the page from reloading!
                e.stopPropagation();
                processMessage();
            });
        } else if (sendBtn) {
            sendBtn.addEventListener('click', (e) => {
                e.preventDefault();
                processMessage();
            });
        }

        // 4. PROCESS MESSAGE
        async function processMessage() {
            if (!input) return;
            const msg = input.value.trim();
            if (!msg) return;
            
            // Clear input
            input.value = '';
            input.style.height = 'auto';

            // Add User Message (Right)
            appendMessage('user', msg);

            // Add Loading AI Message (Left)
            const loadingDiv = appendMessage('ai', '<span style="color:#aaa;">Thinking...</span>');

            try {
                // Send to backend
                const response = await fetch('/ai_assistant', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg })
                });
                const data = await response.json();
                
                // Replace Thinking with actual response
                loadingDiv.querySelector('div').innerHTML = data.reply;
                // Re-attach the Read button
                loadingDiv.querySelector('div').nextElementSibling.innerHTML = `<button onclick="readAloud(this)" style="background:none; border:none; color:#888; cursor:pointer; font-size:12px;">🔊 Read Aloud</button>`;

            } catch (err) {
                loadingDiv.querySelector('div').innerHTML = "<span style='color:red;'>Error connecting to AI. Check Termux logs.</span>";
            }
        }

        // 5. TEXT-TO-SPEECH (READ ALOUD)
        window.readAloud = function(btn) {
            if (window.speechSynthesis.speaking) {
                window.speechSynthesis.cancel();
                btn.innerText = '🔊 Read Aloud';
                return;
            }
            const text = btn.parentElement.previousElementSibling.innerText;
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.onstart = () => btn.innerText = '⏹ Stop';
            utterance.onend = () => btn.innerText = '🔊 Read Aloud';
            window.speechSynthesis.speak(utterance);
        };

        // 6. MICROPHONE FIX
        const micBtn = Array.from(document.querySelectorAll('button, span, div')).find(el => el.textContent.trim() === '🎤');
        if (micBtn && input) {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (SR) {
                const rec = new SR();
                rec.onresult = (e) => { input.value = e.results[0][0].transcript; };
                rec.onerror = (e) => { 
                    alert("Mic Error: You MUST open the site using http://127.0.0.1:5000, not the 192.168 IP address."); 
                };
                micBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    rec.start();
                    micBtn.style.color = 'red';
                });
                rec.onend = () => micBtn.style.color = '';
            }
        }

        // 7. PLUS ICON FIX
        const plusBtn = Array.from(document.querySelectorAll('button, span, div')).find(el => el.textContent.trim() === '+');
        if (plusBtn) {
            const fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.style.display = 'none';
            document.body.appendChild(fileInput);
            plusBtn.addEventListener('click', (e) => {
                e.preventDefault();
                fileInput.click();
            });
        }

    }, 500); // Wait 500ms for UI to load
});
</script>


<style>
    /* Clean up the text box */
    textarea, input[type="text"] {
        resize: none !important; /* Removes the resize handle (//) */
        outline: none !important;
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 10px 15px !important;
    }
    ::-webkit-resizer { display: none !important; }
    
    /* Hide the "Hey Google" or extra mic icons if they are inside the input area */
    input::-webkit-calendar-picker-indicator,
    input::-webkit-search-cancel-button,
    input::-webkit-credentials-auto-fill-button {
        display: none !important;
    }
    
    /* Ensure the composer bottom bar looks clean */
    .composer-wrapper {
        display: flex !important;
        align-items: center !important;
        background: #2a2a35 !important;
        border-radius: 25px !important;
        padding: 5px 10px !important;
        margin: 10px !important;
    }
</style>

<script>
document.addEventListener('DOMContentLoaded', () => {
    // Force remove any extra buttons that clutter the text box
    const input = document.querySelector('textarea, input[type="text"]');
    if (input) {
        // If the browser auto-injects a mic or google icon next to the input, hide it
        const parent = input.parentElement;
        if (parent) {
            Array.from(parent.children).forEach(child => {
                // If it's not the input, mic, plus, or send button, hide it
                if (child !== input && !child.innerHTML.includes('🎤') && !child.innerHTML.includes('+') && !child.innerHTML.includes('↑')) {
                    // Just hide weird overlapping icons
                    if (child.tagName !== 'BUTTON') {
                        child.style.display = 'none';
                    }
                }
            });
        }
    }
});
</script>
</body>



</html>
"""

# --- ROUTES ---
@app.route("/")
def index():
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, company, salary, match_score, stage, status FROM applications WHERE stage = 'Active Pipeline'")
    active_apps = cursor.fetchall()
    conn.close()
    profile = get_profile_data()
    return render_template_string(HTML_TEMPLATE, page='kanban', active_apps=active_apps, profile=profile)

@app.route("/jobs")
def jobs_page():
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, company, salary, match_score, stage, status FROM applications WHERE stage = 'Submitted'")
    submitted_apps = cursor.fetchall()
    conn.close()
    profile = get_profile_data()
    return render_template_string(HTML_TEMPLATE, page='jobs_archive', submitted_apps=submitted_apps, profile=profile)

@app.route("/inbox")
def inbox():
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, sender, subject, category, snippet, suggested_reply FROM recruitment_emails ORDER BY id DESC")
    emails = cursor.fetchall()
    conn.close()
    profile = get_profile_data()
    return render_template_string(HTML_TEMPLATE, page='inbox', emails=emails, profile=profile)

@app.route("/sync_gmail")
def sync_gmail():
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    sample_emails = [
        ("recruitment@lemon.io", "Application Received: Senior React Developer", "Confirmation Received", "Thanks for submitting your application to Lemon.io! Our team is reviewing your profile.", "Dear Lemon.io Hiring Team,\n\nThank you for confirming receipt. I look forward to your update.\n\nBest regards,\nEzenwa Christian"),
        ("hiring@coalitiontechnologies.com", "Interview Request for Remote Role", "Interview Invitation", "We were impressed by your background and would love to schedule a technical round.", "Dear Coalition Technologies Team,\n\nI am thrilled to receive this invitation! I am available for the technical call.\n\nBest regards,\nEzenwa Christian")
    ]
    for em in sample_emails:
        cursor.execute("INSERT INTO recruitment_emails (sender, subject, category, snippet, suggested_reply) VALUES (?, ?, ?, ?, ?)", em)
    conn.commit()
    conn.close()
    return redirect("/inbox")

@app.route("/profile")
def profile():
    profile = get_profile_data()
    return render_template_string(HTML_TEMPLATE, page='profile', profile=profile)

@app.route("/update_skills", methods=["POST"])
def update_skills():
    new_skills_raw = request.form.get("skills", "")
    if new_skills_raw:
        skills_list = [s.strip() for s in new_skills_raw.split(",") if s.strip()]
        profile = get_profile_data()
        profile["tech_skills"] = skills_list
        with open("profile.json", "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
    return redirect(url_for("profile"))

@app.route("/upload_avatar", methods=["POST"])
def upload_avatar():
    if "avatar" not in request.files:
        return redirect(url_for("profile"))
    file = request.files["avatar"]
    if file.filename == "":
        return redirect(url_for("profile"))
    if file:
        filename = "profile_avatar.jpg"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        
        profile = get_profile_data()
        profile["avatar_url"] = "/static/uploads/" + filename + "?t=" + os.urandom(4).hex()
        with open("profile.json", "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
            
        return redirect(url_for("profile"))

@app.route("/upload_cover", methods=["POST"])
def upload_cover():
    if "cover" not in request.files:
        return redirect(url_for("profile"))
    file = request.files["cover"]
    if file.filename == "":
        return redirect(url_for("profile"))
    if file:
        filename = "cover_banner.jpg"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        
        profile = get_profile_data()
        profile["cover_url"] = "/static/uploads/" + filename + "?t=" + os.urandom(4).hex()
        with open("profile.json", "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
            
        return redirect(url_for("profile"))


import requests


import requests


@app.route("/ai_assistant", methods=["GET", "POST"])
def ai_assistant():
    if request.method == "GET":
        return render_template_string(HTML_TEMPLATE, page='ai_assistant', active_apps=[], profile={})

    # Safely handle BOTH JSON (fetch) and Form Data (traditional submit)
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    user_msg = data.get("message", "")
    if not user_msg:
        return jsonify({"reply": "Please enter a message."})

    # ---- YOUR API KEY GOES HERE ----
    API_KEY = "YOUR_GEMINI_API_KEY_HERE" 
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": user_msg}]}]}
    
    try:
        import requests
        res = requests.post(url, json=payload, timeout=15)
        res.raise_for_status()
        reply = res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"API ERROR: {e}")
        reply = f"Connection Error. Please check your API key."
        
    return jsonify({"reply": reply})
@app.route("/autofill/<int:app_id>")
def autofill(app_id):
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, company, salary, job_url FROM applications WHERE id = ?", (app_id,))
    row = cursor.fetchone()
    conn.close()
    
    profile = get_profile_data()
    
    if row:
        cover_letter = f"Dear Hiring Team at {row[2]},\n\nI am writing to express my strong interest in the {row[1]} position. With my background in backend Python development, API architecture, and published technical writing, I am confident in delivering high-impact work for your team.\n\nBest regards,\n{profile['full_name']}"
        target_url = format_direct_job_url(row[2], row[1], row[4])
        return jsonify({
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "salary": row[3],
            "job_url": target_url,
            "mapped_fields": {
                "applicant_name": profile["full_name"],
                "applicant_email": profile["email"],
                "cover_letter_body": cover_letter
            }
        })
    return jsonify({"error": "Job not found"}), 404

@app.route("/confirm_submit/<int:app_id>", methods=["POST"])
def confirm_submit(app_id):
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET stage = 'Submitted', status = 'Applied' WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
    
    redirect_url = request.form.get("job_url", "/")
    return redirect(redirect_url)

@app.route("/revert_app/<int:app_id>", methods=["POST"])
def revert_app(app_id):
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET stage = 'Active Pipeline', status = 'Pending Review' WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
    return redirect("/jobs")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

@app.route("/export_chat/<fmt>")
def export_chat(fmt):
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("SELECT sender, message, timestamp FROM chat_history ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    
    if fmt == "json":
        import json
        data = [{"sender": r[0], "message": r[1], "timestamp": r[2]} for r in rows]
        return app.response_class(json.dumps(data, indent=2), mimetype="application/json")
    else:
        md = "# Career Agent Enterprise Hub - Chat History\n\n"
        for r in rows:
            role = "You" if r[0] == "user" else "AI"
            md += f"**{role}** *({r[2]})*:\n{r[1]}\n\n---\n\n"
        return app.response_class(md, mimetype="text/markdown")

@app.route("/clear_chat", methods=["POST"])
def clear_chat():
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    return redirect(url_for("ai_assistant"))

@app.route("/delete_msg/<int:msg_id>", methods=["POST"])
def delete_msg(msg_id):
    conn = sqlite3.connect("job_agent.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history WHERE id = ?", (loop.index,))
    conn.commit()
    conn.close()
    return redirect(url_for("ai_assistant"))
