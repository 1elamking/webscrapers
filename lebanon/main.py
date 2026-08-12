"""
Lebanon County (PA) Civil Court — case scraper.
Motor: CountySuite Portal (Teleosoft) — modern Angular + açık JSON API. Saf HTTP.
Search endpoint auth'suz; caseId response'ta geliyor (adres detayı için ileride hazır).
"""
import requests, json, csv, re, os, html as htmllib
import pytz, datetime

SEARCH_URL = "https://portal.lebanon.pa.countysuite-azuregov.us/courts.civil.portal/CaseSearch/Search"
PROXY_USER = 'spm9mf1yzr' #os.environ["DECODO_PROXY_USER"]
PROXY_PASS = 'dR_xA9pbv5tlYI9ne0' #os.environ["DECODO_PROXY_PASS"]
PROXY      = f"http://{PROXY_USER}:{PROXY_PASS}@us.decodo.com:10001"
PROXIES    = {"http": PROXY, "https": PROXY}


# Müşterinin DatabasePlan Lebanon tablosundaki distress kategorileri (dropdown value'ları)
DISTRESS_CATEGORIES = [
    "134",                                  # Civil: Real Property (foreclosure/ejectment/L&T dahil)
    "274", "279",                           # Judgment: DJ Judgment, Note
    "309", "313", "308", "310", "312", "224",  # Liens: Fed/State Tax, Commonwealth, Municipal, Sewer, Mechanic's
    "237", "246", "238", "245", "248", "247", "239", "240",  # Divorce + variantlar
    "369",                                  # Writ of Summons
]

# Tarih aralığı: 7 gün (TEST). Production'da days=2 yapacağız. Eastern → UTC (site Z bekliyor).
eastern = pytz.timezone("America/New_York")
now     = datetime.datetime.now(eastern)
start_l = (now - datetime.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
end_l   = now.replace(hour=23, minute=59, second=59, microsecond=0)
iso = lambda d: d.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://portal.lebanon.pa.countysuite-azuregov.us",
    "Referer": "https://portal.lebanon.pa.countysuite-azuregov.us/courts.civil.portal/CaseSearch",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
}
payload = {
    "userSearchString": "", "caseSearchType": "CaseNumber", "isJudgments": False,
    "startDate": iso(start_l), "endDate": iso(end_l),
    "requestCategories": DISTRESS_CATEGORIES, "caseContactCategories": [],
    "includeAttorneysInSearch": False,
}


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()

INITIATOR  = {"PLA", "PLT", "PET", "APP", "APLT", "CLM"}
RESPONDENT = {"DEF", "RES", "RSP", "APE", "APLE", "GAR"}

def parse_participants(raw):
    plas, defs, allp = [], [], []
    for seg in re.split(r"</br>|<br\s*/?>", raw or "", flags=re.I):
        t = clean(seg).rstrip(",").strip()
        if not t:
            continue
        allp.append(t)
        m = re.match(r"([A-Za-z]{2,4}):\s*(.*)", t)
        if not m:
            continue
        role, name = m.group(1).upper(), m.group(2).strip()
        if role in INITIATOR:    plas.append(name)
        elif role in RESPONDENT:  defs.append(name)
    return "; ".join(plas), "; ".join(defs), " | ".join(allp)


print(f"Tarih aralığı: {start_l:%m/%d/%Y} → {end_l:%m/%d/%Y}")
print(f"Kategori: {len(DISTRESS_CATEGORIES)} distress kategori")
r = requests.post(SEARCH_URL, headers=headers, json=payload, timeout=90, proxies=PROXIES)
print(f"HTTP {r.status_code}")
data = r.json()
dtos = data.get("caseSearchDTOs") or []
print(f"Dönen case: {len(dtos)}")

records = []
for d in dtos:
    plaintiff, defendant, participants_raw = parse_participants(d.get("caseParticipants"))
    records.append({
        "case_number":      d.get("caseNumber", ""),
        "plaintiff":        plaintiff,
        "defendant":        defendant,
        "participants_raw": participants_raw,
        "case_category":    clean((d.get("caseCategoryName") or "").replace("</br>", " - ")),
        "date_opened":      clean((d.get("opened") or "").split("</br>")[0]),
        "status":           d.get("status", ""),
        "case_id":          d.get("caseId", ""),
        "county":           "Lebanon, PA",
        "scraped_at":       now.strftime("%Y-%m-%d %H:%M"),
    })

keys = list(records[0].keys()) if records else []
with open("lebanon/lebanon_records.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(records)
with open("lebanon/lebanon_records.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"✓ {len(records)} kayıt yazıldı → lebanon/lebanon_records.csv / .json")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
if WEBHOOK_URL and records:
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(WEBHOOK_URL, json=batch)
        print(f"Webhook batch {i//100 + 1}: {resp.status_code} ({len(batch)} kayıt)")
elif not WEBHOOK_URL:
    print("Webhook: WEBHOOK_URL yok, atlandı (lokal test).")
