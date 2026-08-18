"""Bucks (PSI) — civil case scraper. Auth YOK, direkt export CSV. Saf requests + Decodo proxy."""
import requests, os, time, csv, io, json
import pytz, datetime
from urllib.parse import quote

PROXY       = f"http://{os.environ['DECODO_PROXY_USER']}:{os.environ['DECODO_PROXY_PASS']}@us.decodo.com:10001"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
BASE        = "https://propublic.buckscountyonline.org"

DAYS    = 2   # TEST; production'da DAYS=2 yap
eastern = pytz.timezone("America/New_York")
today   = datetime.datetime.now(eastern)
d_from  = (today - datetime.timedelta(days=DAYS)).strftime("%-m/%-d/%Y")
d_to    = today.strftime("%-m/%-d/%Y")
SEARCH_QS = (f"Q=&fromAdv=1&CaseType=&DateCommencedFrom={quote(d_from, safe='')}"
             f"&DateCommencedTo={quote(d_to, safe='')}&Court=C&Court=F&Grid=true&Count=1000")

# Distress: uzun CaseType metni → keyword eşleşmesi (client vermedi, distress mantığı).
INCLUDE_KW = [
    "MORTGAGE FORECLOSURE", "LIEN FORECLOSURE", "EJECTMENT", "QUIET TITLE", "PARTITION",
    "MUNICIPAL LIEN", "COMMONWEALTH LIEN", "SCHOOL TAX LIEN", "FEDERAL TAX LIEN",
    "PERSONAL PROPERTY TAX LIEN", "MECHANIC", "TAX LIEN", "TAX CLAIM",
    "SCIRE FACIAS SUR", "CONFESSION OF JUDGMENT", "JUDGMENT NOTE",
    "CERTIFICATION OF JUDGMENT", "COMPLAINT IN DIVORCE", "ANNULMENT",
    "EQUITABLE DISTRIBUTION", "WRIT OF EXECUTION", "LIS PENDENS", "WRIT OF SUMMONS",
    "PROMISSORY NOTE", "PRAECIPE FOR JUDGMENT",
]
EXCLUDE_KW = ["CLERK OF COURTS", "JUVENILE PROBATION", "CUSTODY",
              "OPERATOR'S LICENSE", "CHANGE OF NAME", "COUNSEL FEES"]

def wanted(ct):
    u = (ct or "").upper()
    if any(x in u for x in EXCLUDE_KW): return False
    return any(x in u for x in INCLUDE_KW)

s = requests.Session()
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

def req(method, url, **kw):
    kw.setdefault("timeout", 120)
    for a in range(1, 6):
        try:
            return s.request(method, url, **kw)
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
            print(f"  proxy/bağlantı hatası (deneme {a}/5): {type(e).__name__}"); time.sleep(6)
    raise SystemExit("Proxy sürekli düştü.")

print(f"Tarih: {d_from} → {d_to}")
# Session cookie için önce arama sayfası, sonra export (garanti)
req("GET", f"{BASE}/PSI/v/search/case?{SEARCH_QS}", allow_redirects=True)
r = req("GET", f"{BASE}/PSI/v/search/case?{SEARCH_QS}&Export=csv")
ct = r.headers.get("content-type", "")
if "csv" not in ct.lower():
    open("bucks/step_debug.html", "w", encoding="utf-8").write(r.text)
    print(f"CSV değil (ct={ct}) → bucks/step_debug.html"); raise SystemExit(1)

reader = csv.DictReader(io.StringIO(r.text))
all_rows, records = 0, []
for row in reader:
    all_rows += 1
    if not wanted(row.get("CaseType", "")):
        continue
    records.append({
        "case_number":   row.get("CaseNumber", ""),
        "plaintiff":     row.get("CaptionPlaintiff", ""),
        "defendant":     row.get("CaptionDefendant", ""),
        "case_category": row.get("CaseType", ""),
        "date_opened":   row.get("Commenced", ""),
        "matter_code":   row.get("MatterCode", ""),
        "parcel_number": row.get("ParcelNumber", ""),
        "lis_pendens":   row.get("LisPendens", ""),
        "county":        "Bucks, PA",
        "scraped_at":    today.strftime("%Y-%m-%d %H:%M"),
    })

print(f"Toplam CSV: {all_rows} | Distress tutulan: {len(records)}")
keys = list(records[0].keys()) if records else []
with open("bucks/bucks_records.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(records)
with open("bucks/bucks_records.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"✓ {len(records)} kayıt → bucks/bucks_records.csv / .json")

if WEBHOOK_URL and records:
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(WEBHOOK_URL, json=batch)
        print(f"Webhook batch {i//100 + 1}: {resp.status_code} ({len(batch)})")
elif not WEBHOOK_URL:
    print("Webhook: WEBHOOK_URL yok, atlandı (lokal test).")
