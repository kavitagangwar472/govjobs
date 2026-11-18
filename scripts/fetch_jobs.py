#!/usr/bin/env python3
"""Collect recruitment links from official sites into data/jobs.json (30-day retention)."""
import hashlib, json, re, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests, urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()
DATA = Path(__file__).resolve().parent.parent / "data" / "jobs.json"
RETENTION_DAYS, MAX_PER_SOURCE = 30, 40

# Edit freely: org name, category (must match a chip on the site), page that lists notices.
SOURCES = [
    ("UPSC", "SSC & UPSC", "https://upsc.gov.in/whats-new"),
    ("SSC", "SSC & UPSC", "https://ssc.gov.in/"),
    ("IBPS", "Banking", "https://www.ibps.in/"),
    ("SBI", "Banking", "https://sbi.co.in/web/careers/current-openings"),
    ("RBI", "Banking", "https://opportunities.rbi.org.in/Scripts/Vacancies.aspx"),
    ("RRB Chandigarh", "Railways", "https://www.rrbcdg.gov.in/"),
    ("DRDO RAC", "Defence", "https://rac.gov.in/"),
    ("Indian Army", "Defence", "https://joinindianarmy.nic.in/"),
    ("India Post", "Other", "https://www.indiapost.gov.in/"),
    ("ISRO", "Other", "https://www.isro.gov.in/Careers.html"),
    ("Employment News", "Other", "https://www.employmentnews.gov.in/"),
]
KEEP = re.compile(r"recruit|vacanc|notification|advertis|online application|engagement|walk-?in|bharti|apply", re.I)
DROP = re.compile(r"result|admit card|answer key|tender|quotation|syllabus|cut-?off|corrigendum|merit list|shortlist|schedule|call letter|auction|procurement|archive|tutorial", re.I)
TEACH = re.compile(r"teacher|lecturer|professor|tgt|pgt|prt|faculty", re.I)
UA = {"User-Agent": "Mozilla/5.0 (compatible; GovJobsDailyBot/1.0)"}
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def get(url):
    try:
        return requests.get(url, headers=UA, timeout=30).text
    except requests.exceptions.SSLError:  # some gov sites have broken certificates
        return requests.get(url, headers=UA, timeout=30, verify=False).text


def parse_date(s):
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    try:
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*,?\s+(\d{4})", s)
        if m and m[2].lower() in MONTHS:
            return date(int(m[3]), MONTHS[m[2].lower()], int(m[1])).isoformat()
    except ValueError:
        pass
    return None


def scrape(org, cat, url):
    soup = BeautifulSoup(get(url), "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ").split())
        href = a["href"].strip()
        if not 15 <= len(title) <= 220 or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if not KEEP.search(title) or DROP.search(title):
            continue
        ctx = title + " " + " ".join(a.parent.get_text(" ").split())[:300]
        m = re.search(r"(last date|closing date|last day|till|upto|up to|on or before)(.{0,40})", ctx, re.I)
        link = urljoin(url, href)
        out.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "title": title, "org": org,
            "category": "Teaching" if TEACH.search(title) else cat,
            "url": link, "last_date": parse_date(m[2]) if m else None,
        })
    return out[:MAX_PER_SOURCE]


def main():
    today = date.today()
    old = json.loads(DATA.read_text()) if DATA.exists() else {"jobs": []}
    jobs = {j["id"]: j for j in old["jobs"] if not j.get("demo")}
    ok = 0
    for org, cat, url in SOURCES:
        try:
            found = scrape(org, cat, url)
            ok += 1
            new = 0
            for j in found:
                if j["id"] in jobs:
                    jobs[j["id"]]["last_date"] = j["last_date"] or jobs[j["id"]].get("last_date")
                else:
                    j["first_seen"] = today.isoformat()
                    jobs[j["id"]] = j
                    new += 1
            print(f"OK   {org}: {len(found)} found, {new} new")
        except Exception as e:
            print(f"FAIL {org}: {e}", file=sys.stderr)
    if ok == 0:
        sys.exit("All sources failed; keeping existing data.")
    cutoff = (today - timedelta(days=RETENTION_DAYS)).isoformat()
    kept = [j for j in jobs.values() if j["first_seen"] >= cutoff]
    kept.sort(key=lambda j: j["first_seen"], reverse=True)
    DATA.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": kept}, indent=1, ensure_ascii=False))
    print(f"Saved {len(kept)} jobs (dropped {len(jobs) - len(kept)} older than {RETENTION_DAYS} days)")


if __name__ == "__main__":
    main()
