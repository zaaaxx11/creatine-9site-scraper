#!/usr/bin/env python3.11
"""
Tropicana competitor price engine — BEST PRICE from 9 UK competitor sites.
Strategy (details matter):
  1. Fetch FULL catalogs (Shopify /products.json -> variants[].barcode = exact match key)
  2. Match: barcode exact (1.0) > barcode-normalised (0.95) > name+size fuzzy Jaccard w/ sameSize hard block
  3. Sort: cheapest matched price wins -> competitor (CamelCase) + competitorPrice
Output: 17 original cols + competitor + competitorPrice (19 cols)
"""
import json, re, csv, sys, time, html as ihtml, urllib.parse
from pathlib import Path
from collections import Counter

CACHE = Path(__file__).resolve().parent / "comp_cache"
CACHE.mkdir(parents=True, exist_ok=True)

SHOPIFY = {
    "AppliedNutrition": "https://appliednutrition.uk",
    "ReflexNutrition": "https://reflexnutrition.com",
    "10xAthletic": "https://www.10xathletic.com",
    "AnimalPak": "https://uk.animalpak.com",
}

def log(*a):
    print(*a, flush=True)

# ---------- fetchers ----------
def fetch_fetcher(url, timeout=30):
    from scrapling.fetchers import Fetcher
    try:
        r = Fetcher().get(url, follow_redirects=True, timeout=timeout)
        return r.status, (r.html_content or "")
    except Exception as e:
        return 0, f"__ERR__ {type(e).__name__}: {e}"

def fetch_jina(url, timeout=35):
    import subprocess
    key = urllib.parse.quote(url, safe="")
    jurl = f"https://r.jina.ai/{url}"
    try:
        p = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), jurl],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        return 200, p.stdout or ""
    except Exception as e:
        return 0, f"__ERR__ {e}"

def clean_shopify_json(body):
    """Scrapling wraps JSON in <html><body>...</body></html>"""
    if not body:
        return None
    s = body.strip()
    i = s.find('{"products"')
    if i < 0:
        i = s.find('{')
    if i < 0:
        return None
    s = s[i:]
    # strip trailing html
    j = s.rfind('}')
    if j > 0:
        s = s[:j+1]
    try:
        return json.loads(s)
    except Exception:
        # try to repair truncation
        try:
            return json.loads(s + ']}')
        except Exception:
            return None

# ---------- catalog builders ----------
def build_shopify(name, base, max_pages=25):
    prods = []
    for page in range(1, max_pages + 1):
        url = f"{base}/products.json?limit=250&page={page}"
        st, body = fetch_fetcher(url)
        j = clean_shopify_json(body)
        if not j or not j.get("products"):
            break
        batch = j["products"]
        prods.extend(batch)
        log(f"  {name} page {page}: +{len(batch)} (total {len(prods)})")
        if len(batch) < 250:
            break
        time.sleep(0.6)
    out = []
    for p in prods:
        title = p.get("title", "") or ""
        vendor = p.get("vendor", "") or ""
        handle = p.get("handle", "") or ""
        ptype = (p.get("product_type") or "")
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        for v in p.get("variants", []) or []:
            try:
                price = float(v.get("price") or 0)
            except Exception:
                price = 0.0
            if not (2 < price < 500):
                continue
            bc = (v.get("barcode") or "").strip()
            vt = v.get("title") or ""
            # full name = product title + variant option (often holds flavour/size)
            full = title if vt.lower() in ("default title", "") else f"{title} {vt}"
            out.append({
                "name": full, "title": title, "variant": vt,
                "price": price, "barcode": bc,
                "url": f"{base}/products/{handle}" if handle else base,
                "source": name, "vendor": vendor, "ptype": ptype,
                "tags": ",".join(tags),
                "available": bool(v.get("available")),
            })
    return out

def build_asn():
    """ActiveSportsNutrition — custom platform; scrape creatine listing pages."""
    out = []
    urls = [
        "https://www.activesportsnutrition.co.uk/Creatine",
        "https://www.activesportsnutrition.co.uk/Search?q=Creatine",
    ]
    for u in urls:
        st, body = fetch_fetcher(u)
        log(f"  ASN {u} status={st} len={len(body)}")
        if st != 200:
            continue
        for m in re.finditer(r'£\s*(\d+(?:\.\d{2})?)', body):
            try:
                price = float(m.group(1))
            except Exception:
                continue
            if not (2 < price < 500):
                continue
            pre = body[max(0, m.start()-1500):m.start()]
            links = re.findall(r'href="(/[^"#?]+)"[^>]*>\s*([^<]{6,120})\s*<', pre)
            cand = [(t.strip(), h) for h, t in links
                    if len(t.strip()) > 6 and not any(x in t.lower() for x in
                    ["cookie", "privacy", "account", "cart", "brands", "search"])]
            if cand:
                t, h = cand[-1]
                out.append({"name": ihtml.unescape(t), "title": ihtml.unescape(t), "variant": "",
                            "price": price, "barcode": "",
                            "url": "https://www.activesportsnutrition.co.uk" + h,
                            "source": "ActiveSportsNutrition", "vendor": "", "ptype": "", "tags": "",
                            "available": True})
        # also try scrapling css for richer names
        try:
            from scrapling.fetchers import Fetcher
            r = Fetcher().get(u)
            els = r.css('[data-control-role="productDetailLink"]')
            for el in els:
                href = el.attrib.get("href", "")
                txt = (el.text or "").strip()
                if not href or len(txt) < 6:
                    continue
                full = "https://www.activesportsnutrition.co.uk" + href
                # resolve price: nearest price via parent text
                par = el.parent
                ptext = ""
                for _ in range(4):
                    if par is None:
                        break
                    ptext += " " + (par.text or "")
                    par = getattr(par, "parent", None)
                pm = re.search(r'£\s*(\d+(?:\.\d{2})?)', ptext)
                if not pm:
                    continue
                price = float(pm.group(1))
                if not (2 < price < 500):
                    continue
                out.append({"name": txt, "title": txt, "variant": "", "price": price, "barcode": "",
                            "url": full, "source": "ActiveSportsNutrition", "vendor": "",
                            "ptype": "", "tags": "", "available": True})
        except Exception as e:
            log(f"  ASN css err {e}")
        if out:
            break
    # dedup by url keep cheapest
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

def build_hb():
    """Holland & Barrett — Next.js; try __NEXT_DATA__ from direct fetch, fallback Jina."""
    out = []
    urls = ["https://www.hollandandbarrett.com/shop/sports-nutrition/creatine/"]
    for u in urls:
        st, body = fetch_fetcher(u)
        log(f"  HB {u} status={st} len={len(body)}")
        if body and len(body) > 5000:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
            if m:
                try:
                    j = json.loads(m.group(1))
                    out.extend(_walk_hb_json(j))
                except Exception as e:
                    log(f"  HB next json err {e}")
        if not out:
            st2, md = fetch_jina(u)
            log(f"  HB jina status={st2} len={len(md)}")
            out.extend(_parse_md_prices(md, "HollandAndBarrett",
                                        r"https://www\.hollandandbarrett\.com/shop/product/[^\s\)]+"))
            out.extend(_parse_md_prices(md, "HollandAndBarrett",
                                        r"https://www\.hollandandbarrett\.com/p/[^\s\)]+"))
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

def _walk_hb_json(j, acc=None):
    """Recursively find product-like dicts in Next.js payload."""
    if acc is None:
        acc = []
    if isinstance(j, dict):
        name = j.get("name") or j.get("productName") or j.get("title")
        price = j.get("price") or j.get("priceValue") or j.get("nowPrice")
        url = j.get("url") or j.get("productUrl") or j.get("link")
        try:
            pv = float(str(price).replace("£", "").replace(",", "")) if price is not None else 0
        except Exception:
            pv = 0
        if name and pv and 2 < pv < 500 and url and "hollandandbarrett.com" in str(url):
            bc = str(j.get("barcode") or j.get("ean") or j.get("gtin") or "")
            acc.append({"name": str(name), "title": str(name), "variant": "", "price": pv,
                        "barcode": bc, "url": str(url), "source": "HollandAndBarrett",
                        "vendor": "", "ptype": "", "tags": "", "available": True})
        for v in j.values():
            _walk_hb_json(v, acc)
    elif isinstance(j, list):
        for v in j:
            _walk_hb_json(v, acc)
    return acc

def _parse_md_prices(md, source, url_re):
    """Generic: £price -> nearest markdown link before it matching url_re."""
    out = []
    if not md:
        return out
    for m in re.finditer(r'£\s*(\d+(?:\.\d{2})?)', md):
        try:
            price = float(m.group(1))
        except Exception:
            continue
        if not (2 < price < 500):
            continue
        start = max(0, m.start() - 1200)
        snip = md[start:m.start()]
        links = re.findall(r'\[([^\]]{6,140})\]\((https://[^\s\)]+)\)', snip)
        good = [(t.strip(), u) for t, u in links
                if len(t.strip()) > 6 and not t.strip().startswith("!")
                and not any(x in t.lower() for x in
                            ["cookie", "privacy", "select your", "we use cookies", "accept",
                             "sponsored", "subscribe", "trustpilot", "shop by", "view all"])
                and re.search(url_re, u)]
        if good:
            t, u = good[-1]
            out.append({"name": ihtml.unescape(t), "title": ihtml.unescape(t), "variant": "",
                        "price": price, "barcode": "", "url": u, "source": source,
                        "vendor": "", "ptype": "", "tags": "", "available": True})
    return out

def build_dolphin():
    out = []
    st, body = fetch_fetcher("https://www.dolphinfitness.co.uk/en/creatine/list/1")
    log(f"  Dolphin status={st} len={len(body)}")
    if st == 200 and len(body) > 2000:
        # product tiles
        for m in re.finditer(r'href="(/en/[^"]*?)"[^>]*title="([^"]{6,140})"', body):
            pass
        for m in re.finditer(r'£\s*(\d+(?:\.\d{2})?)', body):
            try:
                price = float(m.group(1))
            except Exception:
                continue
            if not (2 < price < 500):
                continue
            pre = body[max(0, m.start()-1500):m.start()]
            links = re.findall(r'href="(/en/[^"#?]+)"[^>]*>\s*([^<]{6,120})\s*<', pre)
            cand = [(t.strip(), h) for h, t in links if len(t.strip()) > 6
                    and not any(x in t.lower() for x in
                                ["cookie", "privacy", "account", "basket", "checkout", "brands",
                                 "contact", "delivery", "returns", "sports supplements",
                                 "health & wellbeing", "foods & drinks", "personal care"])]
            if cand:
                t, h = cand[-1]
                out.append({"name": ihtml.unescape(t), "title": ihtml.unescape(t), "variant": "",
                            "price": price, "barcode": "",
                            "url": "https://www.dolphinfitness.co.uk" + h,
                            "source": "DolphinFitness", "vendor": "", "ptype": "", "tags": "",
                            "available": True})
    if not out:
        st2, md = fetch_jina("https://www.dolphinfitness.co.uk/en/creatine/list/1")
        out = _parse_md_prices(md, "DolphinFitness",
                               r"https://www\.dolphinfitness\.co\.uk/en/[^\s\)]+")
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

def build_iherb():
    out = []
    for u in ["https://uk.iherb.com/search?kw=creatine",
              "https://uk.iherb.com/c/creatine"]:
        st, body = fetch_fetcher(u)
        log(f"  iHerb {u} status={st} len={len(body)}")
        if st != 200 or len(body) < 5000:
            continue
        # iHerb tiles
        for m in re.finditer(r'£\s*(\d+(?:\.\d{2})?)', body):
            try:
                price = float(m.group(1))
            except Exception:
                continue
            if not (2 < price < 500):
                continue
            pre = body[max(0, m.start()-1500):m.start()]
            links = re.findall(r'href="(/pr/[^"]+)"[^>]*>([^<]{6,140})<', pre)
            if not links:
                links = re.findall(r'href="(/[^"]*?/[^"]*?-(\d+))"[^>]*>([^<]{6,140})<', pre)
                links = [(h, t) for h, _i, t in links]
            if links:
                h, t = links[-1]
                t = ihtml.unescape(t).strip()
                if len(t) < 6:
                    continue
                out.append({"name": t, "title": t, "variant": "", "price": price, "barcode": "",
                            "url": "https://uk.iherb.com" + h if h.startswith("/") else h,
                            "source": "IHerbUk", "vendor": "", "ptype": "", "tags": "",
                            "available": True})
        if out:
            break
    if not out:
        st2, md = fetch_jina("https://uk.iherb.com/search?kw=creatine")
        out = _parse_md_prices(md, "IHerbUk", r"https://uk\.iherb\.com/pr/[^\s\)]+")
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

def build_cellucor():
    """cellucor.uk — not Shopify. Try common platforms."""
    out = []
    cands = [
        ("https://www.cellucor.uk/products.json?limit=250", "shopify"),
        ("https://cellucor.uk/products.json?limit=250", "shopify"),
        ("https://www.cellucor.uk/collections/creatine", "html"),
        ("https://www.cellucor.uk/search?q=creatine", "html"),
    ]
    for u, kind in cands:
        st, body = fetch_fetcher(u)
        log(f"  Cellucor {u} status={st} len={len(body)}")
        if kind == "shopify":
            j = clean_shopify_json(body)
            if j and j.get("products"):
                for p in j["products"]:
                    title = p.get("title", "")
                    for v in p.get("variants", []) or []:
                        try:
                            price = float(v.get("price") or 0)
                        except Exception:
                            continue
                        if not (2 < price < 500):
                            continue
                        vt = v.get("title") or ""
                        full = title if vt.lower() in ("default title", "") else f"{title} {vt}"
                        out.append({"name": full, "title": title, "variant": vt, "price": price,
                                    "barcode": (v.get("barcode") or "").strip(),
                                    "url": f"https://www.cellucor.uk/products/{p.get('handle','')}",
                                    "source": "CellucorUk", "vendor": p.get("vendor", ""),
                                    "ptype": p.get("product_type", ""), "tags": "", "available": True})
                break
        else:
            if st == 200 and len(body) > 3000:
                for m in re.finditer(r'£\s*(\d+(?:\.\d{2})?)', body):
                    try:
                        price = float(m.group(1))
                    except Exception:
                        continue
                    if not (2 < price < 500):
                        continue
                    pre = body[max(0, m.start()-1500):m.start()]
                    links = re.findall(r'href="(/[^"#?]+)"[^>]*>\s*([^<]{6,120})\s*<', pre)
                    cand = [(t.strip(), h) for h, t in links if len(t.strip()) > 6
                            and not any(x in t.lower() for x in
                                        ["cookie", "privacy", "account", "cart", "search", "brand"])]
                    if cand:
                        t, h = cand[-1]
                        out.append({"name": ihtml.unescape(t), "title": ihtml.unescape(t),
                                    "variant": "", "price": price, "barcode": "",
                                    "url": "https://www.cellucor.uk" + h, "source": "CellucorUk",
                                    "vendor": "", "ptype": "", "tags": "", "available": True})
                if out:
                    break
    best = {}
    for p in out:
        k = p["url"]
        if k not in best or p["price"] < best[k]["price"]:
            best[k] = p
    return list(best.values())

# ---------- catalog orchestration ----------
def load_catalog(force=False):
    p = CACHE / "catalog_full.json"
    if p.exists() and not force:
        data = json.loads(p.read_text())
        return data
    cat = []
    log("== Shopify catalogs (barcode-rich) ==")
    for name, base in SHOPIFY.items():
        try:
            got = build_shopify(name, base)
            log(f"  -> {name}: {len(got)} variants")
            cat.extend(got)
        except Exception as e:
            log(f"  !! {name} failed: {e}")
    log("== HTML catalogs ==")
    for fn, nm in [(build_asn, "ActiveSportsNutrition"), (build_hb, "HollandAndBarrett"),
                   (build_dolphin, "DolphinFitness"), (build_iherb, "IHerbUk"),
                   (build_cellucor, "CellucorUk")]:
        try:
            got = fn()
            log(f"  -> {nm}: {len(got)} products")
            cat.extend(got)
        except Exception as e:
            log(f"  !! {nm} failed: {e}")
    p.write_text(json.dumps(cat, indent=1))
    return cat

if __name__ == "__main__":
    cat = load_catalog(force="--force" in sys.argv)
    log(f"\nTOTAL catalog: {len(cat)}")
    log(f"By source: {dict(Counter(c['source'] for c in cat))}")
    withbc = [c for c in cat if c.get("barcode")]
    log(f"With barcode: {len(withbc)}")
    for c in cat[:5]:
        log(c)
