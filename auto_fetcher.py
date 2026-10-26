import sqlite3
import requests
import time
import datetime
import re
import threading
import json
import os
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Ignore that annoying BeautifulSoup warning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

DB_NAME = "job_agent.db"

# RELAXED TARGET TITLES: Anything with these words will be accepted
TARGET_TITLES = [
    "developer", "engineer", "writer", "documentation", "programmer", 
    "architect", "frontend", "backend", "full stack", "fullstack", 
    "react", "python", "typescript", "javascript", "software"
]

# VALID LOCATIONS (Global)
VALID_LOCS = ["worldwide", "global", "anywhere", "remote", "africa"]

# RELAXED BLACKLIST: Only block absolute junk
BLACKLIST = [
    "iapwe", "commission", "sales", "office assistant", "data entry", 
    "telegram", "whatsapp", "mlm", "unpaid", "no experience", 
    "drugs", "gambling", "casino", "crypto", "forex", "betting", 
    "interpreter", "translator", "customer support", "customer service", 
    "recruiter", "account manager"
]

def clean_text(text):
    return str(text).lower() if text else ""

def fetch_remotive():
    try:
        res = requests.get("https://remotive.com/api/remote-jobs?limit=50", timeout=10)
        return res.json().get("jobs", [])
    except: return []

def fetch_jobicy():
    try:
        res = requests.get("https://jobicy.com/api/v2/remote-jobs?count=50&geo=anywhere", timeout=10)
        return res.json().get("jobs", [])
    except: return []

def process_and_save():
    print("🤖 Auto-Fetcher: Scanning global job boards...")
    
    all_jobs = []
    
    # 1. Fetch Remotive
    for j in fetch_remotive():
        all_jobs.append({
            "title": j.get("title", ""),
            "company": j.get("company_name", ""),
            "location": j.get("candidate_required_location", ""),
            "url": j.get("url", ""),
            "description": j.get("description", "")
        })
        
    # 2. Fetch Jobicy
    for j in fetch_jobicy():
        all_jobs.append({
            "title": j.get("jobTitle", ""),
            "company": j.get("companyName", ""),
            "location": "Worldwide", 
            "url": j.get("url", ""),
            "description": j.get("jobDescription", "")
        })

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    added_count = 0
    
    for job in all_jobs:
        title = clean_text(job['title'])
        company = clean_text(job['company'])
        loc = clean_text(job['location'])
        desc = clean_text(job['description'])
        url = str(job['url'])

        # Filter 1: Absolute Junk
        if any(bad in title or bad in company for bad in BLACKLIST):
            continue
            
        # Filter 2: Global Locations
        if not any(l in loc for l in VALID_LOCS):
            continue
            
        # Filter 3: Target Roles (Any match is fine)
        if not any(target in title for target in TARGET_TITLES):
            continue

        # Filter 4: Deduplication
        cursor.execute("SELECT id FROM job_queue WHERE url=?", (url,))
        if cursor.fetchone():
            continue

        # Metadata Extraction
        salary_match = re.search(r'\$\s?(\d{2,3}(?:,\d{3})*|\d+k)', desc, re.IGNORECASE)
        extracted_salary = 0
        if salary_match:
            sal_str = salary_match.group(1).replace(',', '').lower()
            if 'k' in sal_str: extracted_salary = int(float(sal_str.replace('k', '')) * 1000)
            else: extracted_salary = int(sal_str)

        # Match Scoring
        my_skills = ["python", "typescript", "react", "fastapi", "sql", "ai", "llm", "technical writing", "node.js", "api"]
        score = 0
        text_to_check = f"{title} {desc}"
        for skill in my_skills:
            if skill in text_to_check: score += 10
        score = min(score, 100)

        # Match Reason
        match_reason = "General match."
        if 'python' in desc and ('react' in desc or 'typescript' in desc): match_reason = "Strong fit: Matches your Python & React stack."
        elif 'technical writing' in desc or 'documentation' in desc: match_reason = "Perfect fit: Aligns with your Technical Writing background."
        elif 'ai' in desc or 'llm' in desc: match_reason = "Great fit: Aligns with your AI & LLM experience."

        # Extract Recruiter Email
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', desc)
        recruiter_email = email_match.group(0) if email_match else None

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            cursor.execute(
                "INSERT INTO job_queue (title, company, location, url, description, status, date_added, match_score, extracted_salary, match_reason, recruiter_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job['title'], job['company'], job['location'], url, job['description'], 'Pending', now, score, extracted_salary, match_reason, recruiter_email)
            )
            added_count += 1
        except Exception as e:
            pass

    conn.commit()
    conn.close()
    print(f"✅ Auto-Fetcher: Added {added_count} highly-targeted jobs.")

if __name__ == "__main__":
    print("🚀 STARTING 24/7 AUTO-FETCHER ROBOT...")
    while True:
        try:
            process_and_save()
            print("😴 Auto-Fetcher sleeping for 30 minutes...")
            time.sleep(1800) # Sleep for exactly 30 minutes
        except Exception as e:
            print(f"⚠️ Auto-Fetcher error: {e}")
            print("Restarting in 60 seconds...")
            time.sleep(60)
