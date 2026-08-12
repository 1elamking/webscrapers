"""
Lancaster County (PA) Prothonotary — Civil case scraper.
Motor: CountySuite (ASP.NET WebForms + Infragistics, cookieless (S()) session).

>>> ADIM 1 (RECON) <<<
Amaç: All-categories aramasını render ettirip grid HTML'ini diske dökmek.
Grid satır yapısını + case_category kolonunun gerçek metnini görünce ADIM 2'de
(parse + filtre) devam edeceğiz. Bu dosya HENÜZ tam scraper değil.
"""
import requests, time, os
import pytz, datetime

API_URL  = "https://scraper-api.decodo.com/v2/scrape"
TOKEN    = 'VTAwMDA0MDI5MzY6UFdfMTJmNzAwZTIxMzlmMjE2NjI4ZTEwOTYwMGQyNGZjYmUw' #os.environ["DECODO_TOKEN"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

api_headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Basic {TOKEN}",
}

BASE_URL   = "https://portal.lancaster.pa.countysuite-azuregov.us/courts.civil.publicsearch/Default.aspx"
SESSION_ID = f"lanc_{int(time.time())}"

# Tarih aralığı: 2 gün geriye (dün + bugün). Format M/D/YYYY (site: 7/19/2026).
eastern = pytz.timezone("America/New_York")
today   = datetime.datetime.now(eastern)
start   = today - datetime.timedelta(days=2)
date_from = f"{start.month}/{start.day}/{start.year}"
date_to   = f"{today.month}/{today.day}/{today.year}"

# NOT: ddlRequestCategory default = "All Case Categories" (value 0) → dropdown'a
# dokunmuyoruz. Advanced panel'in taze session'da açık geldiğini varsayıyoruz
# (kaydedilen HTML display:block idi). Grid boş dönerse buraya btnAdvanced
# expand click'i ekleriz.
SEARCH_ACTIONS = [
    {"type": "wait_for_element", "selector": {"type": "css", "value": "#ctl00_MainContent_wdcStartDate_input"}, "timeout_s": 25},
    {"type": "click", "selector": {"type": "css", "value": "#ctl00_MainContent_wdcStartDate_input"}},
    {"type": "input", "selector": {"type": "css", "value": "#ctl00_MainContent_wdcStartDate_input"}, "value": date_from},
    {"type": "wait", "wait_time_s": 1},
    {"type": "click", "selector": {"type": "css", "value": "#ctl00_MainContent_wdcEndDate_input"}},
    {"type": "input", "selector": {"type": "css", "value": "#ctl00_MainContent_wdcEndDate_input"}, "value": date_to},
    {"type": "wait", "wait_time_s": 1},
    {"type": "click", "selector": {"type": "css", "value": "#ctl00_MainContent_btnSearch"}},
    {"type": "wait", "wait_time_s": 10},
]


def decodo_get(url, browser_actions=None, retries=3):
    payload = {"url": url, "headless": "html", "session_id": SESSION_ID}
    if browser_actions:
        payload["browser_actions"] = browser_actions
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(API_URL, json=payload, headers=api_headers, timeout=180)
            data = r.json()
            if "results" in data:
                return data["results"][0]["content"]
            print(f"  Decodo hatası (deneme {attempt}/{retries}): {data}")
        except Exception as e:
            print(f"  İstek hatası (deneme {attempt}/{retries}): {e}")
        time.sleep(5)
    return None


import csv, json, re, html as htmllib
from collections import Counter

# ── Hedef distress kategorileri — client cevabı gelince SADECE burayı düzenleriz ──
CATEGORY_PREFIXES = (
    "CIVIL: REAL PROPERTY",   # düz + mortgage foreclosure + alt tipler
)
CATEGORY_EXACT = {
    "JUDICIAL TAX SALE", "CIVIL: MISCELLANEOUS", "CIVIL: MISCELLANEOUS WITH ORDER",
    "LANCASTER COUNTY TAX CLAIM", "LANCASTER COUNTY TAX LIEN",
    "TAX LIEN (MUNICIPAL, FEDERAL, COMMONWEALTH OR CERTIFIED COPY)",
    "REFILED FEDERAL TAX LIEN", "COMMONWEALTH OF PA. LIEN", "SCHOOL TAX LIEN",
    "REALTY TRANSFER TAX LIEN", "CLAIM OF LIEN", "MECHANICS LIEN CLAIM",
    "WRIT-SCIRE FACIAS SUR MUNICIPAL LIEN",
    "CONF. JUDGMENT-EJECTMENT", "CONFESSION OF JUDGMENT - MONEY ONLY", "JUDGMENT - MDJ",
    "JUDGMENT - FEDERAL (MUNICIPAL, FEDERAL, COMMONWEALTH OR CERTIFIED COPY)",
    "JUDGMENT - MUNICIPAL (MUNICIPAL, FEDERAL, COMMONWEALTH OR CERTIFIED COPY)",
    "JUDGMENT - STATE (MUNICIPAL, FEDERAL, COMMONWEALTH OR CERTIFIED COPY)",
    "ABSTRACT OF JUDGMENT", "FOREIGN JUDGMENT", "WRIT OF EXECUTION",
    "M.D.J. JUDGMENT / EXEC. W/ ATTACHMENT", "M.D.J. JUDGMENT / EXEC. W/O ATTACHMENT",
    "COMPLAINT IN DIVORCE",
    "COMPLAINT IN DIVORCE - 1 COUNT (NO CUSTODY)",
    "COMPLAINT IN DIVORCE - 2 COUNTS (NO CUSTODY)",
    "COMPLAINT IN DIVORCE - 3 COUNTS (NO CUSTODY)",
    "COMPLAINT IN ANNULMENT",
}

def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()

def category_wanted(cat):
    return cat in CATEGORY_EXACT or any(cat.startswith(p) for p in CATEGORY_PREFIXES)

INITIATOR  = {"PLA", "PLT", "PET", "APP", "APLT", "CLM"}   # başlatan taraf → plaintiff
RESPONDENT = {"DEF", "RES", "RSP", "APE", "APLE", "GAR"}    # karşı taraf → defendant

def parse_participants(td):
    plas, defs, raw = [], [], []
    for part in re.split(r"<br\s*/?>", td, flags=re.I):
        t = clean(part)
        if not t:
            continue
        raw.append(t)
        m = re.match(r"([A-Z]{2,4}):\s*(.*)", t)
        if not m:
            continue
        role, name = m.group(1).upper(), m.group(2).strip()
        if role in INITIATOR:    plas.append(name)
        elif role in RESPONDENT:  defs.append(name)
    return "; ".join(plas), "; ".join(defs), " | ".join(raw)


print(f"Session: {SESSION_ID}")
print(f"Tarih aralığı: {date_from} → {date_to}")
print("Arama render ediliyor (All Categories)...")

html = decodo_get(BASE_URL, browser_actions=SEARCH_ACTIONS)
if not html:
    print("KRİTİK: render alınamadı.")
    raise SystemExit(1)

rows = re.findall(r'<tr title="Click to View"[^>]*>(.*?)</tr>', html, re.S)
print(f"\nGrid satırı: {len(rows)}")

records, dropped = [], Counter()
for r in rows:
    tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
    if len(tds) < 5:
        continue
    category = clean(tds[2])
    if not category_wanted(category):
        dropped[category] += 1
        continue
    plaintiff, defendant, participants_raw = parse_participants(tds[1])
    records.append({
        "case_number":   clean(tds[0]),
        "plaintiff":     plaintiff,
        "defendant":     defendant,
        "case_category": category,
        "date_opened":   clean(re.split(r"<br", tds[3], flags=re.I)[0]),
        "status":        clean(tds[4]),
        "county":        "Lancaster, PA",
        "scraped_at":    today.strftime("%Y-%m-%d %H:%M"),
        "participants_raw": participants_raw,
    })

print(f"Tutulan: {len(records)} | Elenen: {sum(dropped.values())}")
print("\nElenen kategoriler:")
for c, n in dropped.most_common():
    print(f"  {n:>3}  {c}")

keys = list(records[0].keys()) if records else []
with open("lancaster/lancaster_records.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(records)
with open("lancaster/lancaster_records.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"\n✓ {len(records)} kayıt yazıldı → lancaster/lancaster_records.csv / .json")


if WEBHOOK_URL and records:
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(WEBHOOK_URL, json=batch)
        print(f"Webhook batch {i//100 + 1}: {resp.status_code} ({len(batch)} kayıt)")
        time.sleep(1)
elif not WEBHOOK_URL:
    print("Webhook: WEBHOOK_URL yok, atlandı (lokal test).")
