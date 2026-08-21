"""El Paso County Public Trustee — foreclosure scraper.
ASP.NET WebForms, NED (foreclosure açılış) tarih aralığı → gvSearchResults parse.
reCAPTCHA enforce edilmiyor, captcha yok. Mülk adresi + borçlu + bakiye grid'de."""
import requests, re, csv, json, os, html as htmllib
import pytz, datetime
from bs4 import BeautifulSoup

URL         = "https://elpasopublictrustee.com/GTSSearch/"   # trailing slash şart (yoksa 405)
P           = "ctl00$ctl00$MainContent$CustomContentPlaceHolder$"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PROXY   = f"http://spm9mf1yzr:dR_xA9pbv5tlYI9ne0@us.decodo.com:10001"
PROXIES = {"http": PROXY, "https": PROXY}
PAGE_SIZE   = 25

DAYS  = 2   # TEST; production'da DAYS=2
mtn   = pytz.timezone("America/Denver")           # El Paso = Colorado (Mountain)
today = datetime.datetime.now(mtn)
ned_from = (today - datetime.timedelta(days=DAYS)).strftime("%Y-%m-%d")   # type=date → yyyy-mm-dd
ned_to   = today.strftime("%Y-%m-%d")

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"})
s.proxies = PROXIES

import time
def req(method, url, **kw):
    kw.setdefault("timeout", 120)
    for a in range(1, 6):
        try:
            return s.request(method, url, **kw)
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
            print(f"  proxy/bağlantı hatası (deneme {a}/5): {type(e).__name__}"); time.sleep(6)
    raise SystemExit("Proxy sürekli düştü.")

POST_H = {"Referer": URL, "Origin": "https://elpasopublictrustee.com"}


def clean(x):
    x = re.sub(r"<[^>]+>", " ", x or "")
    return re.sub(r"\s+", " ", htmllib.unescape(x)).strip()

def form_fields(html):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="ctl01")
    data = {}
    for inp in form.find_all("input"):
        n = inp.get("name")
        if n and inp.get("type") not in ("submit", "button", "image"):
            data[n] = inp.get("value", "")
    for sel in form.find_all("select"):
        n = sel.get("name")
        opt = sel.find("option", selected=True) or sel.find("option")
        data[n] = opt.get("value", "") if opt else ""
    return data

def parse_rows(html):
    i = html.find('id="MainContent_CustomContentPlaceHolder_gvSearchResults"')
    if i < 0: return []
    seg = html[i: html.find("</table>", i)]
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 6: continue
        c = [clean(td) for td in tds[:6]]
        if c[0]:
            out.append(c)
    return out


# 1. GET → form + VIEWSTATE
r = req("GET", URL)
data = form_fields(r.text)

# 2. Arama POST (NED aralığı)
data[P + "txtNedDate1"] = ned_from
data[P + "txtNedDate2"] = ned_to
data[P + "btnSearch"]   = "Search"
data["g-recaptcha-response"] = ""
r = req("POST", URL, data=data, headers=POST_H)

m = re.search(r"returned\s+(\d+)\s+records", r.text, re.I)
total = int(m.group(1)) if m else 0
pages = max(1, -(-total // PAGE_SIZE))
print(f"NED {ned_from} → {ned_to} | {total} kayıt, {pages} sayfa")

page1 = form_fields(r.text)           # sayfalama için page-1 VIEWSTATE
all_cells = parse_rows(r.text)

# 3. Sayfa 2..N (page-1 state'inden atla)
for p in range(2, pages + 1):
    d = dict(page1)
    d["__EVENTTARGET"]   = f"{P}TopPager$ctl{p-1:02d}$Page"
    d["__EVENTARGUMENT"] = ""
    d.pop(P + "btnSearch", None)
    d["g-recaptcha-response"] = ""
    rp = req("POST", URL, data=d, headers=POST_H)
    got = parse_rows(rp.text)
    all_cells += got
    print(f"  sayfa {p}: +{len(got)}")

records = [{
    "foreclosure_number": c[0], "grantor": c[1], "property_address": c[2],
    "zip": c[3], "subdivision": c[4], "balance_due": c[5],
    "county": "El Paso, CO", "scraped_at": today.strftime("%Y-%m-%d %H:%M"),
} for c in all_cells]

print(f"✓ {len(records)} kayıt")
keys = list(records[0].keys()) if records else []
with open("elpasopublictrustee/elpaso_foreclosures.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(records)
with open("elpasopublictrustee/elpaso_foreclosures.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"→ elpasopublictrustee/elpaso_foreclosures.csv / .json")

if WEBHOOK_URL and records:
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(WEBHOOK_URL, json=batch)
        print(f"Webhook batch {i//100 + 1}: {resp.status_code} ({len(batch)})")
elif not WEBHOOK_URL:
    print("Webhook: WEBHOOK_URL yok, atlandı (lokal test).")
