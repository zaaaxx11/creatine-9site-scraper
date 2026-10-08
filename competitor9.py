#!/usr/bin/env python3.11
"""
Competitor 9-site price collection (FINAL) -> comp_cache/catalog9.json
Raja-confirmed sources (2026-10-05):
  1 ActiveSportsNutrition  https://www.activesportsnutrition.co.uk/Search?q=Creatine
  2 DolphinFitness         https://www.dolphinfitness.co.uk/en/creatine/list/1
  3 HollandAndBarrett      https://www.hollandandbarrett.com/shop/sports-nutrition/creatine/
  4 AppliedNutrition       https://appliednutrition.uk/products.json
  5 10xAthletic            https://www.10xathletic.com/collections/creatine
  6 AnimalPak              https://uk.animalpak.com/collections/creatine
  7 CellucorUk             https://www.cellucor.uk
  8 IHerbUk                https://uk.iherb.com/search?kw=creatine
  9 ReflexNutrition        https://reflexnutrition.com/products.json
Entry: {name, price, url, source, barcode}
"""
import re, json, html as ihtml, subprocess, time, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "comp_cache"; CACHE.mkdir(exist_ok=True)
OUT = CACHE / "catalog9.json"

def log(*a): print(*a, flush=True)

def F(url, timeout=35, tries=2):
    from scrapling.fetchers import Fetcher
    for _ in range(tries):
        try:
            r = Fetcher().get(url, follow_redirects=True, timeout=timeout)
            if r.status == 200 and r.html_content:
                return r.status, r.html_content
        except Exception:
            pass
        time.sleep(1.0)
    return 0, ""

def J(url, timeout=45):
    try:
        p = subprocess.run(["curl","-sL","--max-time",str(timeout),f"https://r.jina.ai/{url}"],
                           capture_output=True, text=True, timeout=timeout+10)
        return p.stdout or ""
    except Exception:
        return ""

def strip_tags(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', ihtml.unescape(s)).strip()

def mk(name, price, url, source, barcode=""):
    return {"name": (name or "").strip(), "price": round(float(price), 2),
            "url": url, "source": source, "barcode": (barcode or "").strip()}

def sj(body):
    if not body: return None
    i = body.find('{"products"')
    if i < 0: return None
    s = body[i:]; j = s.rfind('}')
    if j > 0: s = s[:j+1]
    for c in (s, s+']}', s+'}', s+']}}'):
        try: return json.loads(c)
        except Exception: pass
    return None

# ---------- 1. ASN ----------
def build_asn():
    out = []; seen = set()
    for skip in range(0, 300, 24):
        u = f"https://www.activesportsnutrition.co.uk/Search?q=Creatine&size=100&skip={skip}"
        st, b = F(u)
        if st != 200: break
        tiles = re.split(r'<div class="product-list-item-title">', b)
        new = 0
        for ch in tiles[1:]:
            am = re.search(r'data-control-role="productDetailLink"[^>]*href="([^"]+)"', ch) or \
                 re.search(r'href="([^"]+)"[^>]*data-control-role="productDetailLink"', ch)
            nm = re.search(r'data-control-role="productDetailLink"[^>]*>\s*([^<]{5,90})', ch)
            if not (am and nm): continue
            href, name = am.group(1), ihtml.unescape(nm.group(1)).strip()
            pm = (re.search(r'"finalPrice":\{"amountIncVat":([\d.]+)', ch)
                  or re.search(r'"rrPrice":\{"amountIncVat":([\d.]+)', ch))
            if not pm: continue
            price = float(pm.group(1))
            if not (2 < price < 500): continue
            key = href.split("#")[0]
            if key in seen: continue
            seen.add(key); new += 1
            full = href if href.startswith("http") else "https://www.activesportsnutrition.co.uk" + key
            out.append(mk(name, price, full, "ActiveSportsNutrition"))
        log(f"  ASN skip={skip} tiles={len(tiles)-1} new={new} total={len(out)}")
        if new == 0: break
    return out

# ---------- 2. Dolphin ----------
def build_dolphin():
    out = []; seen = set()
    for page in range(1, 10):
        u = f"https://www.dolphinfitness.co.uk/en/creatine/list/{page}"
        st, b = F(u)
        if st != 200: break
        chunks = re.split(r'class="ari-pc pg-pc"', b)
        new = 0
        for ch in chunks[1:]:
            tm = (re.search(r'<a href="(/en/[^"]+)"\s+title="([^"]+)"', ch)
                  or re.search(r'title="([^"]+)"[^>]*href="(/en/[^"]+)"', ch))
            if not tm: continue
            if tm.group(1).startswith("/en"):
                href, name = tm.group(1), tm.group(2)
            else:
                name, href = tm.group(1), tm.group(2)
            name = ihtml.unescape(name).strip()
            vals = sorted(float(p.replace(",", "")) for p in re.findall(r'£\s*([\d,]+\.\d{2})', ch)
                          if 2 < float(p.replace(",", "")) < 500)
            if not vals: continue
            if href in seen: continue
            seen.add(href); new += 1
            out.append(mk(name, vals[0], "https://www.dolphinfitness.co.uk" + href, "DolphinFitness"))
        log(f"  Dolphin p{page} new={new} total={len(out)}")
        if new == 0: break
    return out

# ---------- 3. Holland & Barrett ----------
def build_hb():
    out = []
    md = ""
    for attempt in range(4):
        md = J("https://www.hollandandbarrett.com/shop/sports-nutrition/creatine/")
        log(f"  HB attempt {attempt+1} len={len(md)}")
        if len(md) > 20000: break
        time.sleep(8)
    log(f"  HB jina len={len(md)}")
    for m in re.finditer(r'\]\((https://www\.hollandandbarrett\.com/shop/product/[^\)]+)\)', md):
        url = m.group(1)
        start = md.rfind('[', 0, m.start())
        label = md[start+1:m.start()] if start > 0 else ""
        label = re.sub(r'!\[[^\]]*\]\([^\)]*\)', ' ', label)
        if '£' not in label: continue
        prices = re.findall(r'£\s*([\d,]+\.\d{2})', label)
        if not prices: continue
        sale = float(prices[0].replace(",", ""))
        if not (2 < sale < 500): continue
        nm = re.split(r'\s*\(\d+\)|\s*\d+%\s*Off|\s*£', label)[0]
        nm = strip_tags(nm).replace("Add to basket", "").strip(" -|")
        if len(nm) < 5: continue
        out.append(mk(nm, sale, url, "HollandAndBarrett"))
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]: best[k] = p
    return list(best.values())

# ---------- Shopify generic ----------
def build_shopify(name, base, coll=None):
    out = []
    for page in range(1, 30):
        seg = (f"{base}/collections/{coll}/products.json?limit=250&page={page}" if coll
               else f"{base}/products.json?limit=250&page={page}")
        st, b = F(seg)
        j = sj(b)
        if not j or not j.get("products"): break
        batch = j["products"]
        for p in batch:
            t = p.get("title","") or ""; h = p.get("handle","") or ""
            for v in p.get("variants", []) or []:
                try: pr = float(v.get("price") or 0)
                except Exception: continue
                if not (2 < pr < 500): continue
                vt = (v.get("title") or "").strip()
                full = t if vt.lower() in ("default title","") else f"{t} {vt}"
                out.append(mk(full, pr, f"{base}/products/{h}", name, v.get("barcode","")))
        log(f"    {name} p{page}: +{len(batch)} total={len(out)}")
        if len(batch) < 250: break
        time.sleep(0.3)
    return out

# ---------- 7. Cellucor (/product/* pages) ----------
def build_cellucor():
    out = []
    st, b = F("https://www.cellucor.uk/")
    links = sorted(set(re.findall(r'href="(/product/[^"#?]+)"', b)))
    log(f"  Cellucor product links={links}")
    for href in links:
        full = "https://www.cellucor.uk" + href
        st2, b2 = F(full)
        if st2 != 200: continue
        pm = (re.search(r'"price"\s*:\s*"?([\d.]+)"?[^}]{0,80}?"priceCurrency"\s*:\s*"GBP"', b2)
              or re.search(r'"priceCurrency"\s*:\s*"GBP"[^}]{0,80}?"price"\s*:\s*"?([\d.]+)', b2)
              or re.search(r'"lowPrice"\s*:\s*"?([\d.]+)', b2)
              or re.search(r'£\s*([\d,]+\.\d{2})', b2))
        nm = re.search(r'<title>([^<|]{5,120})', b2) or re.search(r'"name"\s*:\s*"([^"]{5,120})"', b2)
        gtin = re.search(r'"gtin13"\s*:\s*"(\d{8,14})"', b2)
        if not pm: continue
        price = float(pm.group(1).replace(",",""))
        if not (2 < price < 500): continue
        name = ihtml.unescape(nm.group(1)).strip() if nm else href.split("/")[-1]
        out.append(mk(name, price, full, "CellucorUk", gtin.group(1) if gtin else ""))
        time.sleep(0.3)
    return out

# ---------- 8. iHerb ----------
def build_iherb():
    out = []; seen = set()
    for page in range(1, 21):
        u = f"https://uk.iherb.com/search?kw=creatine&p={page}"
        st, b = F(u, timeout=45)
        if st != 200: break
        chunks = re.split(r'data-product-id="', b)
        new = 0
        for ch in chunks[1:]:
            pid = ch[:ch.find('"')]
            if pid in seen: continue
            pm = re.search(r'"discountPrice"\s*:\s*"£([\d,.]+)"', ch) or \
                 re.search(r'data-ga-discount-price="([\d.]+)"', ch[:2500])
            nm = re.search(r'itemprop="name"[^>]*content="([^"]{5,160})"', ch) or \
                 re.search(r'itemprop="name"[^>]*>\s*([^<]{5,160})', ch)
            lm = re.search(r'href="(https://uk\.iherb\.com/pr/[^"]+)"', b[max(0,b.find('data-product-id="'+pid)-500):b.find('data-product-id="'+pid)+50]) or \
                 re.search(r'href="(https://uk\.iherb\.com/pr/[^"]+)"', ch[:6000])
            if not (pm and nm): continue
            price = float(pm.group(1).replace(",",""))
            if not (2 < price < 500): continue
            seen.add(pid); new += 1
            url = lm.group(1) if lm else f"https://uk.iherb.com/pr/{pid}"
            out.append(mk(ihtml.unescape(nm.group(1)), price, url, "IHerbUk"))
        log(f"  iHerb p{page} new={new} total={len(out)}")
        if new == 0: break
        time.sleep(0.3)
    return out

def build_all():
    cat = []
    log("== 1 ASN ==");        cat += build_asn()
    log("== 2 Dolphin ==");    cat += build_dolphin()
    log("== 3 HB ==");         cat += build_hb()
    log("== 4 AppliedNutrition =="); cat += build_shopify("AppliedNutrition", "https://appliednutrition.uk")
    log("== 5 10xAthletic ==");cat += build_shopify("10xAthletic", "https://www.10xathletic.com")
    log("== 6 AnimalPak ==");  cat += build_shopify("AnimalPak", "https://uk.animalpak.com")
    log("== 7 Cellucor ==");   cat += build_cellucor()
    log("== 8 iHerb ==");      cat += build_iherb()
    log("== 9 Reflex ==");     cat += build_shopify("ReflexNutrition", "https://reflexnutrition.com")
    return cat

if __name__ == "__main__":
    cat = build_all()
    OUT.write_text(json.dumps(cat, indent=1))
    log(f"\nTOTAL {len(cat)}")
    log(f"by source {dict(Counter(c['source'] for c in cat))}")
    log(f"with barcode {sum(1 for c in cat if c['barcode'])}")
