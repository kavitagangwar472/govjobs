"""
Collects recruitment notices from OFFICIAL sites only and writes data/jobs.json.
Never guesses: a date that can't be read from the page or PDF stays empty
(the UI then shows "See notice" / "Not announced").
"""
import hashlib, io, json, re, sys, time, datetime as dt
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "data" / "jobs.json"
SOURCES = json.loads((ROOT / "sources.json").read_text())
HEADERS = {"User-Agent": "GovJobsDailyBot/1.0"}
KEEP_DAYS = 30
MAX_PDFS_PER_RUN = 40
ALLOWED = (".gov.in", ".nic.in", ".ac.in", "ibps.in", "sbi.co.in")

JOB_WORDS = re.compile(r"recruit|vacanc|notification|advert|apply|application|posts?\b|examination|exam\b|bharti", re.I)
SKIP_WORDS = re.compile(r"result|admit card|answer key|syllabus|tender|cut.?off|verification|scorecard|corrigendum|admission", re.I)

MONTHS = {m: i for i, m in enumerate(["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}
D1 = r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})"
D2 = r"(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})[,\s\-]+(\d{4})"
D3 = r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"

def to_iso(y, m, d):
    try: return dt.date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError): return None

def find_dates(text):
    out = []
    for m in re.finditer(D1, text):
        iso = to_iso(m[3], m[2], m[1])
        if iso: out.append((m.start(), iso))
    for m in re.finditer(D2, text):
        mo = MONTHS.get(m[2][:3].lower())
        iso = to_iso(m[3], mo, m[1]) if mo else None
        if iso: out.append((m.start(), iso))
    for m in re.finditer(D3, text):
        mo = MONTHS.get(m[1][:3].lower())
        iso = to_iso(m[3], mo, m[2]) if mo else None
        if iso: out.append((m.start(), iso))
    return sorted(out)

def date_near(text, keyword_re, window=140):
    for k in re.finditer(keyword_re, text, re.I):
        d = find_dates(text[k.end(): k.end() + window])
        if d: return d[0][1]
    return None

def allowed(url):
    host = (urlparse(url).hostname or "").lower()
    return url.startswith("http") and any(host.endswith(s) for s in ALLOWED)

def get(url):
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
            if r.ok: return r
        except requests.RequestException:
            time.sleep(2)
    return None

QUAL_RULES = [("10th", r"\b10th\b|matric|high school"),
              ("12th", r"\b12th\b|intermediate|senior secondary|10\+2"),
              ("Graduate", r"graduat|bachelor|degree|b\.?tech"),
              ("Diploma/ITI", r"diploma|\biti\b")]
CAT_RULES = [("Banking", r"bank|ibps|sbi|rbi|nabard"),
             ("Railway", r"railway|rrb|rrc|metro"),
             ("Defence", r"army|navy|air force|agniveer|drdo|defence|bsf|crpf|cisf|itbp"),
             ("Police", r"police|constable"),
             ("Teaching", r"teacher|tgt|pgt|prt|lecturer|professor|kvs|nvs"),
             ("SSC", r"\bssc\b|staff selection"),
             ("Civil Services", r"civil services|upsc"),
             ("Health", r"nurs|medical officer|aiims|pharmac")]

def guess_category(title, default):
    for cat, rx in CAT_RULES:
        if re.search(rx, title, re.I): return cat
    return default

def is_pdf(url): return url.lower().split("?")[0].endswith(".pdf")

def parse_pdf(url):
    facts = {"exam_date": None, "last_date": None, "vac": None, "qual": []}
    try:
        import pdfplumber
        r = get(url)
        if not r or len(r.content) > 15_000_000: return facts
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:6])
    except Exception as e:
        print("  pdf fail", url, e, file=sys.stderr); return facts
    text = re.sub(r"[ \t]+", " ", text)
    facts["exam_date"] = date_near(text, r"(date of (?:written )?(?:exam|examination|test)|(?:exam|examination|cbt|written test)\s*(?:date|on|schedule)|tentative (?:exam|date))")
    facts["last_date"] = date_near(text, r"(last date[^.\n]{0,60}?(?:apply|application|submission|online)|closing date|last date)")
    m = re.search(r"(?:total\s+)?(?:no\.?\s+of\s+)?(?:vacanc(?:y|ies)|posts?)\D{0,25}?(\d[\d,]{1,7})", text, re.I) \
        or re.search(r"(\d[\d,]{1,7})\s+(?:vacanc(?:y|ies)|posts)\b", text, re.I)
    if m:
        n = int(m[1].replace(",", ""))
        if 1 <= n <= 500000: facts["vac"] = n
    facts["qual"] = [q for q, rx in QUAL_RULES if re.search(rx, text, re.I)]
    return facts

def scrape_source(src):
    r = get(src["url"])
    if not r:
        print("FAILED", src["url"], file=sys.stderr); return []
    soup = BeautifulSoup(r.text, "lxml")
    found, seen = [], set()
    for a in soup.select("a[href]"):
        title = " ".join(a.get_text(" ").split())
        href = urljoin(src["url"], a["href"].strip())
        if len(title) < 12 or href in seen or not allowed(href): continue
        if not JOB_WORDS.search(title) or SKIP_WORDS.search(title): continue
        seen.add(href)
        row = a.find_parent(["tr", "li"])
        d = find_dates(" ".join(row.get_text(" ").split())) if row else []
        found.append({"id": hashlib.md5(href.encode()).hexdigest()[:16], "title": title[:200],
                      "org": src["org"], "url": href, "state": src["state"],
                      "category": guess_category(title, src["category"]),
                      "notification_date": d[0][1] if d else None})
    print(f"{src['org']}: {len(found)} candidate links")
    return found

def main():
    today = dt.date.today()
    jobs = {}
    if OUT.exists():
        try: jobs = {j["id"]: j for j in json.loads(OUT.read_text()).get("jobs", [])}
        except Exception: pass
    pdfs = 0
    for src in SOURCES:
        for j in scrape_source(src):
            cur = jobs.get(j["id"])
            if cur:
                if not cur.get("notification_date") and j.get("notification_date"):
                    cur["notification_date"] = j["notification_date"]
                continue
            j.update({"first_seen": today.isoformat(), "last_date": None, "exam_date": None, "vac": None, "qual": []})
            if is_pdf(j["url"]) and pdfs < MAX_PDFS_PER_RUN:
                pdfs += 1
                j.update({k: v for k, v in parse_pdf(j["url"]).items() if v})
            jobs[j["id"]] = j
        time.sleep(2)
    # exam dates often appear later: retry PDFs from the last 7 days that still lack one
    for j in jobs.values():
        if pdfs >= MAX_PDFS_PER_RUN: break
        if is_pdf(j["url"]) and not j.get("exam_date") and (today - dt.date.fromisoformat(j["first_seen"])).days <= 7:
            pdfs += 1
            j.update({k: v for k, v in parse_pdf(j["url"]).items() if v})
    keep = []
    for j in jobs.values():
        age = (today - dt.date.fromisoformat(j["first_seen"])).days
        closed = j.get("last_date") and j["last_date"] < today.isoformat()
        if age <= KEEP_DAYS and not (closed and age > 7):
            keep.append(j)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "jobs": keep}, ensure_ascii=False, indent=1))
    print("wrote", len(keep), "jobs")

if __name__ == "__main__":
    main()
