#!/usr/bin/env python3.11
"""catalog_brands.py — collect FULL brand catalogs from Dolphin + ASN
(so gainers/pre-workouts, not just the 'creatine' search pages)."""
import re, json, sys, time, csv
from pathlib import Path
from scrapling.fetchers import Fetcher

R = Path(__file__).resolve().parent
OUT = R/"comp_cache"/"catalog_brands.json"
FEED = R/"DropshipProductFeedCreatineOnly.csv"
DOL = "https://www.dolphinfitness.co.uk"
ASN = "https://www.activesportsnutrition.co.uk"

def fetch(u):
    for a in range(3):
        try:
            r = Fetcher().get(u, stealthy_headers=True, timeout=45)
            return getattr(r, "html_content", None) or getattr(r, "text", "") or ""
        except Exception:
            time.sleep(2 + a * 3)
    return ""

def slugify(b):
    return re.sub(r'[^a-z0-9]+', '-', b.lower()).strip('-')

DOL_OVERRIDE = {
    "Optimum Nutrition": "optimum-nutrition", "NXT Nutrition": "nxt-nutrition",
    "Reflex Nutrition": "reflex", "Applied Nutrition": "applied-nutrition",
    "Black Mamba": "black-mamba", "Combat Fuel": "combat-fuel",
    "Rich Piana 5% Nutrition": "rich-piana", "CNP Professional": "cnp",
}

def dol_parse(h):
    out = []
    for ch in h.split('pg-pc-xw')[1:]:
        m = re.search(r'href="([^"]+)"\s+title="([^"]+)"', ch)
        p = re.search(r'<span>\s*£\s*([\d.]+)\s*</span>', ch)
        if m and p:
            url = m.group(1)
            out.append({"name": m.group(2).strip(), "price": float(p.group(1)),
                        "url": DOL + url if url.startswith("/") else url})
    return out

def asn_parse(h):
    out = []
    for ch in h.split('<div class="product-list-item-title">')[1:]:
        nm = re.match(r'\s*<[^>]*>\s*([^<]{3,120})', ch) or re.match(r'\s*([^<]{3,120})', ch)
        pm = re.search(r'data-state-value="([\d.]+)"', ch)
        um = re.search(r'href="([^"]+)"', ch)
        if nm and pm:
            u = um.group(1) if um else ""
            out.append({"name": nm.group(1).strip(), "price": float(pm.group(1)),
                        "url": ASN + u if u.startswith("/") else u})
    return out

def crawl_dolphin(brand, cap=2):
    slug = DOL_OVERRIDE.get(brand, slugify(brand))
    got = []
    for pg in range(1, cap + 1):
        h = fetch(f"{DOL}/en/{slug}/list/{pg}")
        if len(h) < 5000: break
        pr = dol_parse(h)
        if not pr: break
        before = len(got)
        got += pr
        if len(pr) < 20 or len(got) == before: break
    return got

def crawl_asn(brand, cap=8):
    got = []
    for pg in range(0, cap):
        h = fetch(f"{ASN}/Search?q={brand.replace(' ', '+')}&size=100&skip={pg*100}")
        if len(h) < 5000: break
        pr = asn_parse(h)
        if not pr: break
        got += pr
        if len(pr) < 100: break
    return got

def main():
    brands = sys.argv[1:] if len(sys.argv) > 1 else sorted({r["Brand"] for r in csv.DictReader(open(FEED, encoding="utf-8-sig"))})
    store = json.loads(OUT.read_text()) if OUT.exists() else []
    seen = {(c["source"], c["url"]) for c in store}
    for b in brands:
        d = crawl_dolphin(b); a = crawl_asn(b)
        new = 0
        for pr, src in [(x, "DolphinFitness") for x in d] + [(x, "ActiveSportsNutrition") for x in a]:
            key = (src, pr["url"])
            if key in seen or not pr["url"]: continue
            seen.add(key)
            store.append({"source": src, "name": pr["name"], "price": pr["price"],
                          "url": pr["url"], "barcode": ""})
            new += 1
        print(f"{b:26} dolphin={len(d):4} asn={len(a):4} new={new:4} total={len(store)}", flush=True)
    OUT.write_text(json.dumps(store))
    print("WROTE", OUT, len(store))

if __name__ == "__main__":
    main()
