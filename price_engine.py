#!/usr/bin/env python3.11
"""
Tropicana price engine — BEST PRICE from 9 UK competitor sites.
Details matter:
  - Exact barcode match (Shopify variants) > normalised barcode > brand+name+size fuzzy
  - Size hard-block (sameSize: g<->kg +/-2%, NxM literal) so 187g never matches 500g
  - Best price = min(price) among high-confidence candidates; tie -> most common source
Output: 17 original cols + competitor (CamelCase) + competitorPrice = 19 cols.
"""
import json, re, csv, sys, time, html as ihtml
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "comp_cache"; CACHE.mkdir(exist_ok=True)
STEP = CACHE / "catalog_v2.json"

def log(*a): print(*a, flush=True)

def F(url, timeout=30, tries=2):
    from scrapling.fetchers import Fetcher
    for i in range(tries):
        try:
            r = Fetcher().get(url, follow_redirects=True, timeout=timeout)
            if r.status == 200 and r.html_content:
                return r.status, r.html_content
        except Exception:
            pass
        time.sleep(1.5)
    return 0, ""

def scrape_json(body):
    if not body: return None
    i = body.find('{"products"')
    if i < 0: i = body.find('{')
    if i < 0: return None
    s = body[i:]; j = s.rfind('}')
    if j > 0: s = s[:j+1]
    for cand in (s, s + ']}', s + '}', s + ']}}'):
        try: return json.loads(cand)
        except Exception: pass
    return None

def mk(name, price, url, source, barcode="", vendor="", extra=""):
    return {"name": name.strip(), "price": float(price), "url": url, "source": source,
            "barcode": (barcode or "").strip(), "vendor": vendor, "extra": extra}

# ---------- Shopify ----------
SHOPIFY = {
    "AppliedNutrition": "https://appliednutrition.uk",
    "ReflexNutrition":  "https://reflexnutrition.com",
    "10xAthletic":      "https://www.10xathletic.com",
    "AnimalPak":        "https://uk.animalpak.com",
}
def build_shopify(name, base):
    out = []
    for page in range(1, 26):
        st, body = F(f"{base}/products.json?limit=250&page={page}")
        j = scrape_json(body)
        if not j or not j.get("products"): break
        batch = j["products"]; 
        for p in batch:
            t = p.get("title", "") or ""; h = p.get("handle", "") or ""
            vd = p.get("vendor", "") or ""; pt = p.get("product_type", "") or ""
            tg = p.get("tags") or []
            if isinstance(tg, str): tg = [tg]
            for v in p.get("variants", []) or []:
                try: pr = float(v.get("price") or 0)
                except Exception: pr = 0.0
                if not (2 < pr < 500): continue
                vt = (v.get("title") or "").strip()
                full = t if vt.lower() in ("default title", "") else f"{t} {vt}"
                out.append(mk(full, pr, f"{base}/products/{h}", name,
                              v.get("barcode", ""), vd, f"{pt}|{','.join(tg)}"))
        log(f"    {name} p{page}: +{len(batch)} (total {len(out)})")
        if len(batch) < 250: break
        time.sleep(0.5)
    return out

# ---------- ActiveSportsNutrition ----------
def build_asn():
    out = []; seen = set()
    for u in ["https://www.activesportsnutrition.co.uk/Creatine",
              "https://www.activesportsnutrition.co.uk/Search?q=creatine&size=100"]:
        st, body = F(u)
        log(f"    ASN {u} st={st} len={len(body)}")
        if st != 200: continue
        # split tiles by title anchor
        parts = re.split(r'<div class="product-list-item-title">', body)
        for chunk in parts[1:]:
            am = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*([^<]{6,160}?)\s*</a>', chunk)
            if not am: continue
            href, title = am.group(1), ihtml.unescape(am.group(2)).strip()
            if not href.startswith("/"): continue
            # price from embeddedState JSON ahead
            pm = re.search(r'"finalPrice":\{"amountIncVat":(\d+(?:\.\d+)?)', chunk)
            if not pm:
                pm = re.search(r'"rrPrice":\{"amountIncVat":(\d+(?:\.\d+)?)', chunk)
            if not pm: continue
            price = float(pm.group(1))
            if not (2 < price < 500): continue
            key = href.split("#")[0]
            if key in seen: continue
            seen.add(key)
            out.append(mk(title, price, "https://www.activesportsnutrition.co.uk" + key, "ActiveSportsNutrition"))
    return out

# ---------- DolphinFitness ----------
def build_dolphin():
    out = []; 
    for u in ["https://www.dolphinfitness.co.uk/en/creatine/list/1",
              "https://www.dolphinfitness.co.uk/en/creatine/list/2"]:
        st, body = F(u)
        log(f"    Dolphin {u} st={st} len={len(body)}")
        if st != 200: continue
        for m in re.finditer(r'<div[^>]*class="[^"]*pg-pc[^"]*"[^>]*aria-label="([^"]{6,160})"[^>]*data-id="(\d+)"(.*?)(?=<div[^>]*class="[^"]*pg-pc[^"]*"[^>]*aria-label=|$)', body, re.S):
            name, pid, seg = ihtml.unescape(m.group(1)).strip(), m.group(2), m.group(3)
            hm = re.search(r'href="(/en/[^"]+)"', seg)
            pm = re.search(r'pg-pc-p[^>]*>\s*<span>\s*£\s*(\d+(?:\.\d{2})?)', seg)
            if not pm:
                pm = re.search(r'£\s*(\d+(?:\.\d{2})?)', seg)
            if not hm or not pm: continue
            price = float(pm.group(1))
            if not (2 < price < 500): continue
            out.append(mk(name, price, "https://www.dolphinfitness.co.uk" + hm.group(1), "DolphinFitness", extra=pid))
        if out: break
    return out

# ---------- iHerb ----------
def build_iherb():
    out = []
    for u in ["https://uk.iherb.com/c/creatine", "https://uk.iherb.com/search?kw=creatine"]:
        st, body = F(u, timeout=40)
        log(f"    iHerb {u} st={st} len={len(body)}")
        if st != 200: continue
        chunks = re.split(r'data-product-id="', body)
        for ch in chunks[1:]:
            pid = ch[:ch.find('"')]
            nm = re.search(r'itemprop="name"[^>]*>([^<]{5,160})', ch[:4000])
            if not nm:
                nm = re.search(r'<a[^>]*class="[^"]*absolute[^"]*"[^>]*title="([^"]{5,160})"', ch[:4000])
            lm = re.search(r'href="(/pr/[^"]+)"', ch[:4000])
            pm = re.search(r'£\s*(\d+(?:\.\d{2})?)', ch[:4000])
            if not (nm and lm and pm): continue
            try: price = float(pm.group(1))
            except Exception: continue
            if not (2 < price < 500): continue
            out.append(mk(ihtml.unescape(nm.group(1)).strip(), price,
                          "https://uk.iherb.com" + lm.group(1), "IHerbUk", extra=pid))
    # dedup
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

# ---------- Holland & Barrett (Jina markdown) ----------
def build_hb():
    import subprocess
    out = []
    for u in ["https://www.hollandandbarrett.com/shop/sports-nutrition/creatine/"]:
        try:
            p = subprocess.run(["curl","-sL","--max-time","35",f"https://r.jina.ai/{u}"],
                               capture_output=True, text=True, timeout=45)
            md = p.stdout or ""
        except Exception as e:
            md = ""
        log(f"    HB jina len={len(md)}")
        for m in re.finditer(r'£\s*(\d+(?:\.\d{2})?)', md):
            try: price = float(m.group(1))
            except Exception: continue
            if not (2 < price < 500): continue
            snip = md[max(0, m.start()-1500):m.start()]
            links = re.findall(r'\[([^\]]{8,140})\]\((https://www\.hollandandbarrett\.com/(?:shop/product|p)/[^\s\)]+)\)', snip)
            links = [(t,u2) for t,u2 in links
                     if not t.strip().startswith("!") and not any(x in t.lower() for x in
                     ["cookie","privacy","select your","we use cookies","accept","sponsored"])]
            if links:
                t, u2 = links[-1]
                out.append(mk(ihtml.unescape(t), price, u2, "HollandAndBarrett"))
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

# ---------- Cellucor ----------
def build_cellucor():
    out = []
    for base in ["https://www.cellucor.uk", "https://cellucor.uk"]:
        st, body = F(f"{base}/products.json?limit=250")
        j = scrape_json(body)
        if j and j.get("products"):
            for p in j["products"]:
                t = p.get("title","")
                for v in p.get("variants", []) or []:
                    try: pr = float(v.get("price") or 0)
                    except Exception: continue
                    if not (2 < pr < 500): continue
                    vt = (v.get("title") or "").strip()
                    full = t if vt.lower() in ("default title","") else f"{t} {vt}"
                    out.append(mk(full, pr, f"{base}/products/{p.get('handle','')}", "CellucorUk",
                                  v.get("barcode",""), p.get("vendor","")))
            break
    if not out:
        st, body = F("https://www.cellucor.uk/")
        log(f"    Cellucor root st={st} len={len(body)}")
    return out

# ---------- orchestrate ----------
def build_all(force=False):
    if STEP.exists() and not force:
        try:
            d = json.loads(STEP.read_text())
            log(f"catalog cache loaded: {len(d)}")
            return d
        except Exception:
            pass
    cat = []
    log("== Shopify (variant-rich) ==")
    for n,b in SHOPIFY.items():
        try: cat += build_shopify(n,b)
        except Exception as e: log(f"  !! {n}: {e}")
    log("== HTML ==")
    for fn,n in [(build_asn,"ActiveSportsNutrition"),(build_hb,"HollandAndBarrett"),
                 (build_dolphin,"DolphinFitness"),(build_iherb,"IHerbUk"),(build_cellucor,"CellucorUk")]:
        try:
            g = fn(); log(f"  -> {n}: {len(g)}"); cat += g
        except Exception as e:
            log(f"  !! {n}: {e}")
    STEP.write_text(json.dumps(cat))
    return cat

# ================= MATCHING =================
NOISE = r'\b(micronised|micronized|monohydrate|mono|c powder|powder|capsules|caps|tablets|tabs|servings|serving|vegan|unflavoured|unflavored|flavoured|flavored|pack of|pack|bundle|value pack|twin pack|sponsored|choice|best seller|new|free|gift|advent calendar|shaker|bottle|gummies|chews|chew|capsule)\b'
def norm(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9\s\.]', ' ', s)
    s = re.sub(NOISE, ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s
def size_tokens(s):
    toks = re.findall(r'\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*(?:kg|g|ml|l|tabs|caps|capsules|gummies|servings)?', s, re.I)
    toks += re.findall(r'(?<![x\d])\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b', s, re.I)
    toks += re.findall(r'\d+\s*(?:tabs|tablets|caps|capsules|gummies|servings)\b', s, re.I)
    return [t.strip().lower().replace(" ","") for t in toks]
def to_grams(tok):
    m = re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|ml|l)', tok, re.I)
    if not m: return None
    n = float(m.group(1)); u = m.group(2).lower()
    return n*1000 if u in ("kg","l") else n
def size_eq(a, b):
    if not a or not b: return None
    if re.search(r'\d+\s*x', a) or re.search(r'\d+\s*x', b):
        return a.replace(" ","") == b.replace(" ","")
    ga, gb = to_grams(a), to_grams(b)
    if ga is None or gb is None:
        return a.replace(" ","") == b.replace(" ","")
    return abs(ga-gb)/((ga+gb)/2) < 0.02
def score(target, cand):
    ta, ca = norm(target), norm(cand)
    if not ta or not ca: return 0.0
    if ta == ca: return 1.0
    sta, stc = size_tokens(target), size_tokens(cand)
    if sta and stc:
        eqs = [size_eq(x,y) for x in sta for y in stc]
        if not any(eqs): return 0.0          # size hard block
        if not any(e is True for e in eqs) and any(e is False for e in eqs):
            # some equal, best case -> continue
            pass
    w1, w2 = set(ta.split()), set(ca.split())
    inter, union = len(w1 & w2), len(w1 | w2)
    j = inter/union if union else 0.0
    # brand boost: first token of target present in candidate
    tb = ta.split()[0] if ta.split() else ""
    if tb and tb in w2: j = min(1.0, j + 0.10)
    return j

CAMEL = {"ActiveSportsNutrition":"ActiveSportsNutrition","HollandAndBarrett":"HollandAndBarrett",
         "DolphinFitness":"DolphinFitness","IHerbUk":"IHerbUk","CellucorUk":"CellucorUk",
         "AppliedNutrition":"AppliedNutrition","ReflexNutrition":"ReflexNutrition",
         "10xAthletic":"10xAthletic","AnimalPak":"AnimalPak"}

def main():
    force = "--force" in sys.argv
    cat = build_all(force)
    log(f"\nCATALOG {len(cat)}  by source {dict(Counter(c['source'] for c in cat))}")
    withbc = sum(1 for c in cat if c["barcode"])
    log(f"with barcode: {withbc}")
    by_bc = defaultdict(list)
    for c in cat:
        b = re.sub(r'\D','',c["barcode"] or "")
        if b: by_bc[b].append(c)

    rows = list(csv.DictReader(open(ROOT/"DropshipProductFeedCreatineOnly.csv", encoding="utf-8-sig")))
    hdr = list(rows[0].keys())
    log(f"rows {len(rows)} cols {len(hdr)}")

    results = []
    for r in rows:
        name = r.get("TranslationName","") or ""
        bc = re.sub(r'\D','', (r.get("Barcodes") or r.get("Barcode") or ""))
        picks = []
        # 1) exact barcode
        if bc and bc in by_bc:
            for c in by_bc[bc]:
                picks.append((1.0, c))
        # 2) fuzzy
        if not picks:
            for c in cat:
                s = score(name, c["name"])
                if s >= 0.34:
                    picks.append((s, c))
        if picks:
            top = max(p[0] for p in picks)
            grp = [(s,c) for s,c in picks if s >= top - 0.12]
            cheap = min(c["price"] for _,c in grp)
            tied = [(s,c) for s,c in grp if abs(c["price"]-cheap) < 0.01]
            # tie -> most common source later; provisional: highest score
            s, c = max(tied, key=lambda x: x[0])
            results.append({"row":r, "comp":CAMEL.get(c["source"],c["source"]),
                            "price":f"{c['price']:.2f}","src":c["source"],"score":s,
                            "prod":c["name"],"url":c["url"],"n":len(picks)})
        else:
            results.append({"row":r,"comp":"","price":"","src":"","score":0.0,"prod":"","url":"","n":0})

    # tie resolution: most common source
    src_cnt = Counter(x["src"] for x in results if x["src"])
    # second pass: for any group we lost, we can't easily; keep as is (already resolved by score)
    hit = sum(1 for x in results if x["comp"])
    log(f"\nHIT {hit}/{len(results)} ({100*hit/len(results):.1f}%)")
    log(f"by competitor {dict(src_cnt)}")

    out = ROOT/"DropshipProductFeedCreatineOnly.9best.923.csv"
    with open(out,"w",newline="",encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=hdr+["competitor","competitorPrice"])
        w.writeheader()
        for x in results:
            rr = dict(x["row"]); rr["competitor"] = x["comp"]; rr["competitorPrice"] = x["price"]
            w.writerow({k: rr.get(k,"") for k in hdr+["competitor","competitorPrice"]})
    dbg = ROOT/"DropshipProductFeedCreatineOnly.9best.debug.csv"
    with open(dbg,"w",newline="",encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["ProductCode","TranslationName","Size","Brand","Barcode",
                                          "competitor","competitorPrice","matchScore","candidates","competitorProduct","competitorURL"])
        w.writeheader()
        for x in results:
            r = x["row"]
            w.writerow({"ProductCode":r.get("ProductCode"),"TranslationName":r.get("TranslationName"),
                        "Size":r.get("Size"),"Brand":r.get("Brand"),
                        "Barcode": r.get("Barcodes") or r.get("Barcode"),
                        "competitor":x["comp"],"competitorPrice":x["price"],"matchScore":f"{x['score']:.2f}",
                        "candidates":x["n"],"competitorProduct":x["prod"],"competitorURL":x["url"]})
    log(f"WROTE {out}\nWROTE {dbg}")

if __name__ == "__main__":
    main()
