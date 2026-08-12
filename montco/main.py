"""Montco (PSI) — civil case scraper.
CF Turnstile auth (2Captcha) → export CSV → distress filtre. Saf requests + Decodo proxy."""
import requests, os, time, re, csv, io, json
import pytz, datetime
from urllib.parse import quote

CAPTCHA_KEY = os.environ["CAPTCHA_KEY"]
PROXY       = f"http://{os.environ['DECODO_PROXY_USER']}:{os.environ['DECODO_PROXY_PASS']}@us.decodo.com:10001"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
BASE        = "https://courtsapp.montcopa.org"

# Tarih penceresi: TEST için 10 gün; production'da DAYS=2 yap.
DAYS    = 2
eastern = pytz.timezone("America/New_York")
today   = datetime.datetime.now(eastern)
d_from  = (today - datetime.timedelta(days=DAYS)).strftime("%-m/%-d/%Y")
d_to    = today.strftime("%-m/%-d/%Y")
SEARCH_QS = (f"Q=&fromAdv=1&CaseType=&DateCommencedFrom={quote(d_from, safe='')}"
             f"&DateCommencedTo={quote(d_to, safe='')}&Court=C&Court=F&Grid=true&Count=1000")

# Distress CaseType'ları (CSV kolonuyla birebir tam ad). Client vermedi → distress mantığı.
DISTRESS_CASETYPES = {
    "Complaint In Mortgage Foreclosure", "Complaint in Ejectment", "Summons In Ejectment",
    "Complaint In Partition", "Complaint in Quiet Title",
    "Lien", "Lien Commonwealth of PA", "Lien Commonwealth of PA Volume",
    "Mechanics Lien Claim", "Montgomery County Lien", "Municipal Lien",
    "Municipal Lien Govt", "Municipal Lien Volume", "IRS Federal Lien",
    "Department of Justice Lien", "Personal Property Tax",
    "Exception/Objections to Tax Claim Sale",
    "Complaint In Confession of Judgment", "Complaint In Confession of Judgment Money & Possession",
    "Judgment Note", "Foreign Judgment", "Judgment from District Justice",
    "Certification of Judgment", "Indexed Writ of Execution without Garnishee",
    "Indexed Writ of Execution with Garnishee",
    "Complaint Divorce", "Complaint in Annulment",
}


def solve_turnstile(sitekey, pageurl, retries=5):
    for a in range(1, retries + 1):
        try:
            cid = requests.post("http://2captcha.com/in.php", data={
                "key": CAPTCHA_KEY, "method": "turnstile",
                "sitekey": sitekey, "pageurl": pageurl, "json": 1}).json().get("request")
        except Exception as e:
            print(f"  2captcha in hata: {e}"); time.sleep(8); continue
        if not cid or not str(cid).isdigit():
            print(f"  2captcha in yanıt: {cid}"); time.sleep(8); continue
        for _ in range(30):
            time.sleep(5)
            res = requests.get(f"http://2captcha.com/res.php?key={CAPTCHA_KEY}&action=get&id={cid}&json=1").json()
            if res.get("status") == 1:
                return res["request"]
        print(f"  token alınamadı (deneme {a}/{retries})")
    return None


s = requests.Session()
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

def req(method, url, **kw):
    kw.setdefault("timeout", 120)
    for attempt in range(1, 6):
        try:
            return s.request(method, url, **kw)
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
            print(f"  proxy/bağlantı hatası (deneme {attempt}/5): {type(e).__name__}")
            time.sleep(6)
    raise SystemExit("Proxy sürekli düştü.")

# 1. auth sayfası
print(f"Tarih: {d_from} → {d_to}")
r = req("GET", f"{BASE}/psi/v/search/case?{SEARCH_QS}", allow_redirects=True)
if "Just a moment" in r.text or "challenge-platform" in r.text:
    print("CF edge HARD challenge — Decodo-browser gerekiyor."); raise SystemExit(1)
sk = re.search(r'data-sitekey="([^"]+)"', r.text)
ru = re.search(r'name="returnUrl"[^>]*value="([^"]*)"', r.text)
if not sk:
    print("sitekey yok — auth sayfası beklenmedik."); raise SystemExit(1)
returnUrl = re.sub(r"&amp;", "&", ru.group(1)) if ru else ""

# 2. Turnstile
print("Turnstile çözülüyor...")
token = solve_turnstile(sk.group(1), r.url)
if not token:
    print("token alınamadı."); raise SystemExit(1)

# 3. auth POST
req("POST", f"{BASE}/psi/auth/init",
    data={"cf-turnstile-response": token, "returnUrl": returnUrl},
    headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": r.url, "Origin": BASE},
    allow_redirects=True)

# 4. export CSV
r3 = req("GET", f"{BASE}/psi/v/search/case?{SEARCH_QS}&Export=csv")
ct = r3.headers.get("content-type", "")
if "csv" not in ct.lower():
    open("montco/step_debug.html", "w", encoding="utf-8").write(r3.text)
    print(f"Export CSV değil (ct={ct}) → montco/step_debug.html"); raise SystemExit(1)

# 5. parse + filtre
reader = csv.DictReader(io.StringIO(r3.text))
all_rows, records = 0, []
for row in reader:
    all_rows += 1
    if (row.get("CaseType") or "").strip() not in DISTRESS_CASETYPES:
        continue
    records.append({
        "case_number":   row.get("CaseNumber", ""),
        "plaintiff":     row.get("CaptionPlaintiff", ""),
        "defendant":     row.get("CaptionDefendant", ""),
        "case_category": row.get("CaseType", ""),
        "date_opened":   row.get("Commenced", ""),
        "status":        row.get("Status", ""),
        "parcel_number": row.get("ParcelNumber", ""),
        "lis_pendens":   row.get("LisPendens", ""),
        "has_judgment":  row.get("Judgement", ""),
        "county":        "Montgomery, PA",
        "scraped_at":    today.strftime("%Y-%m-%d %H:%M"),
    })

print(f"Toplam CSV satırı: {all_rows} | Distress tutulan: {len(records)}")

keys = list(records[0].keys()) if records else []
with open("montco/montco_records.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(records)
with open("montco/montco_records.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"✓ {len(records)} kayıt → montco/montco_records.csv / .json")

if WEBHOOK_URL and records:
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(WEBHOOK_URL, json=batch)
        print(f"Webhook batch {i//100 + 1}: {resp.status_code} ({len(batch)})")
elif not WEBHOOK_URL:
    print("Webhook: WEBHOOK_URL yok, atlandı (lokal test).")
