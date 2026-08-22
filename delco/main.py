"""Delco (Delaware County PA) — C-Track Public Access civil scraper.
JSON API (delcopublicaccessapi), filedDate aralığı → caseType distress filtre. requests + proxy."""
import requests, os, time, json, csv
import pytz, datetime

API   = "https://delcopublicaccessapi.co.delaware.pa.us/api/v1/cases/search"
PROXY = f"http://{os.environ['DECODO_PROXY_USER']}:{os.environ['DECODO_PROXY_PASS']}@us.decodo.com:10001"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# Müşterinin Delco distress kategorileri (caseType). appeal/tort/custody/mass tort/prof.liability ele.
KEEP_CASE_TYPES = {
    "Real Property", "Lien", "Municipal Lien", "Judgment",
    "Divorce", "Miscellaneous", "Contract", "Annulment",
}

DAYS  = 2   # TEST; production'da DAYS=2
eastern = pytz.timezone("America/New_York")
today   = datetime.datetime.now(eastern)
d_from  = (today - datetime.timedelta(days=DAYS)).strftime("%m/%d/%Y")
d_to    = today.strftime("%m/%d/%Y")

s = requests.Session()
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://delcopublicaccess.co.delaware.pa.us",
    "Referer": "https://delcopublicaccess.co.delaware.pa.us/",
    "X-CTrack-Paging-MaxResults": "500",
    "X-CTrack-Paging-CalculateTotalCount": "true",
})

def req(method, url, **kw):
    kw.setdefault("timeout", 120)
    for a in range(1, 6):
        try:
            return s.request(method, url, **kw)
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
            print(f"  proxy/bağlantı hatası (deneme {a}/5): {type(e).__name__}"); time.sleep(6)
    raise SystemExit("Proxy sürekli düştü.")

def fetch(start):
    params = [
        ("queryString", "true"),
        ("searchFields[0].searchType", ""), ("searchFields[0].operation", ">="),
        ("searchFields[0].values[0]", d_from), ("searchFields[0].indexFieldName", "filedDate"),
        ("searchFields[1].searchType", ""), ("searchFields[1].operation", "<="),
        ("searchFields[1].values[0]", d_to), ("searchFields[1].indexFieldName", "filedDate"),
    ]
    return req("GET", API, params=params, headers={"X-CTrack-Paging-StartIndex": str(start)})


print(f"Tarih: {d_from} → {d_to}")
items, start = [], 1
while True:
    r = fetch(start)
    if r.status_code != 200:
        open("delco/step_debug.txt", "w", encoding="utf-8").write(f"{r.status_code}\n{r.text[:2000]}")
        print(f"API {r.status_code} → delco/step_debug.txt"); raise SystemExit(1)
    batch = r.json().get("resultItems", [])
    items += batch
    total = int(r.headers.get("x-ctrack-paging-totalcount", len(items)))
    more  = r.headers.get("x-ctrack-paging-moreresults", "false").lower() == "true"
    print(f"  startRow={start}: +{len(batch)} (toplam {len(items)}/{total})")
    if not more or not batch:
        break
    start += len(batch)

records, dropped = [], {}
for it in items:
    rm = it.get("rowMap", {})
    ct = (rm.get("caseType") or "").strip()
    if ct not in KEEP_CASE_TYPES:
        dropped[ct] = dropped.get(ct, 0) + 1
        continue
    records.append({
        "case_number":         rm.get("caseNumber", ""),
        "case_type":           ct,
        "case_classification": rm.get("caseClassification", ""),
        "short_title":         rm.get("shortTitle", ""),
        "filed_date":          (rm.get("filedDate", "") or "")[:10],
        "closed":              rm.get("closed", ""),
        "case_id":             rm.get("caseID", ""),
        "county":              "Delaware, PA",
        "scraped_at":          today.strftime("%Y-%m-%d %H:%M"),
    })

print(f"\nToplam çekilen: {len(items)} | Distress tutulan: {len(records)}")
print("Elenen caseType'lar:", dropped)

keys = list(records[0].keys()) if records else []
with open("delco/delco_records.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(records)
with open("delco/delco_records.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"✓ {len(records)} kayıt → delco/delco_records.csv / .json")

if WEBHOOK_URL and records:
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(WEBHOOK_URL, json=batch)
        print(f"Webhook batch {i//100 + 1}: {resp.status_code} ({len(batch)})")
elif not WEBHOOK_URL:
    print("Webhook: WEBHOOK_URL yok, atlandı (lokal test).")
