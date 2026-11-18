#!/usr/bin/env python3
"""Collect recruitment links from official sites into data/jobs.json (30-day retention)."""
import hashlib, json, re, ssl, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests, urllib3
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

urllib3.disable_warnings()
DATA = Path(__file__).resolve().parent.parent / "data" / "jobs.json"
RETENTION_DAYS, MAX_PER_SOURCE = 30, 40

# Edit freely: (org, category, url[, state]). Add a state name as 4th item for state-level sources.
# Old line: org name, category (must match a chip on the site), page that lists notices.
SOURCES = [
    # --- Central (work from GitHub) ---
    ("SSC", "SSC & UPSC", "https://ssc.gov.in/"),
    ("IBPS", "Banking", "https://www.ibps.in/"),
    ("SBI", "Banking", "https://sbi.co.in/web/careers/current-openings"),
    ("RBI", "Banking", "https://opportunities.rbi.org.in/Scripts/Vacancies.aspx"),
    ("India Post", "Other", "https://www.indiapost.gov.in/"),
    ("ISRO", "Other", "https://www.isro.gov.in/Careers.html"),
    ("Employment News", "Other", "https://www.employmentnews.gov.in/"),
    # Blocked from GitHub's servers in earlier tests (need an Indian IP): UPSC, RRB Chandigarh, DRDO RAC, Indian Army
    # --- State (4th item = state name, powers the State filter) ---
    ("UPSSSC", "State Govt", "https://upsssc.gov.in/AllNotifications.aspx", "Uttar Pradesh"),
    ("UPPSC", "State Govt", "https://uppsc.up.nic.in/CandidatePages/Notifications.aspx", "Uttar Pradesh"),
    ("UP Police Recruitment Board", "Police", "https://uppbpb.gov.in/", "Uttar Pradesh"),
    ("UPESSC", "Teaching", "https://upessc.up.gov.in/", "Uttar Pradesh"),
    ("BPSC", "State Govt", "https://bpsc.bihar.gov.in/", "Bihar"),
    ("BSSC", "State Govt", "https://bssc.bihar.gov.in/", "Bihar"),
    ("Bihar Police (CSBC)", "Police", "https://csbc.bihar.gov.in/", "Bihar"),
    ("RPSC", "State Govt", "https://rpsc.rajasthan.gov.in/", "Rajasthan"),
    ("RSSB", "State Govt", "https://rssb.rajasthan.gov.in/", "Rajasthan"),
    ("DSSSB", "State Govt", "https://dsssb.delhi.gov.in/", "Delhi"),
    ("HSSC", "State Govt", "https://hssc.gov.in/", "Haryana"),
    ("HPSC", "State Govt", "https://hpsc.gov.in/", "Haryana"),
]
KEEP = re.compile(r"recruit|vacanc|notification|advertis|online application|engagement|walk-?in|bharti|apply", re.I)
DROP = re.compile(r"result|admit card|answer key|tender|quotation|syllabus|cut-?off|corrigendum|merit list|shortlist|schedule|call letter|auction|procurement|archive|tutorial", re.I)
QUAL = [("10th", r"\b10th\b|matric|class x\b"), ("12th", r"\b12th\b|intermediate|senior secondary"),
        ("Graduate", r"graduat|degree|b\.?tech|bachelor|master"), ("Diploma/ITI", r"diploma|\bITI\b")]
VAC = re.compile(r"(\d[\d,]{0,6})\s*(?:posts?|vacanc|seats?)", re.I)
TEACH = re.compile(r"teacher|lecturer|professor|tgt|pgt|prt|faculty", re.I)
UA = {"User-Agent": "Mozilla/5.0 (compatible; GovJobsDailyBot/1.0)"}
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


class LegacyTLS(HTTPAdapter):
    """Lets Python talk to older government servers that OpenSSL 3 rejects by default."""

    def __init__(self, insecure=False, **kw):
        self.insecure = insecure
        super().__init__(**kw)

    def init_poolmanager(self, *a, **k):
        ctx = ssl.create_default_context()
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        if self.insecure:  # last resort for broken certificates
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        k["ssl_context"] = ctx
        super().init_poolmanager(*a, **k)


def get(url):
    last = None
    for mode in ("plain", "legacy", "insecure"):
        try:
            if mode == "plain":
                return requests.get(url, headers=UA, timeout=(8, 25)).text
            s = requests.Session()
            s.mount("https://", LegacyTLS(insecure=(mode == "insecure")))
            return s.get(url, headers=UA, timeout=(8, 25), verify=(mode != "insecure")).text
        except requests.exceptions.SSLError as e:
            last = e
    raise last


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


def scrape(org, cat, url, state="All India"):
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
            "url": link, "last_date": parse_date(m[2]) if m else None, "state": state,
            "vac": int(v[1].replace(",", "")) if (v := VAC.search(ctx)) else None,
            "qual": [q for q, rx in QUAL if re.search(rx, ctx, re.I)],
        })
    return out[:MAX_PER_SOURCE]


def main():
    today = date.today()
    old = json.loads(DATA.read_text()) if DATA.exists() else {"jobs": []}
    jobs = {j["id"]: j for j in old["jobs"] if not j.get("demo")}
    ok = 0
    for org, cat, url, *extra in SOURCES:
        try:
            found = scrape(org, cat, url, extra[0] if extra else "All India")
            ok += 1
            new = 0
            for j in found:
                if j["id"] in jobs:
                    jobs[j["id"]]["last_date"] = j["last_date"] or jobs[j["id"]].get("last_date")
                    for k in ("vac", "qual", "state"):
                        jobs[j["id"]][k] = jobs[j["id"]].get(k) or j[k]
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
