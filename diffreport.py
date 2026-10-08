#!/usr/bin/env python3.11
"""
diffreport.py — human-readable audit of the feed rows the 9-site engine could NOT match.

Moved into the repo from the throwaway /tmp/mktxt.py (BUG5). Two corrections:
  * the "nearest candidate" picker now runs the engine's FULL gate stack — brand gate,
    category gate, forms gate, distinctiveness gate AND is_supplement() — so an ACCESSORY
    (shaker / hoodie / bottle / jug) can never be shown as the nearest competitor.
  * nearest is ranked by the same product-line similarity used for matching, not bare jaccard.

Usage:
  python3.11 diffreport.py                       # reads the engine's *.unmatched_report.csv
  python3.11 diffreport.py --report <path.csv>   # explicit input
"""
import csv, sys, argparse
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import competitor9_engine as E          # noqa: E402

DEFAULT_REPORT = ROOT / "DropshipProductFeedCreatineOnly.9best.unmatched_report.csv"
OUT = ROOT / "unmatched_perbedaan.txt"


def nearest(feed_name, brand, size, cat):
    """Return (score, catalog_entry) for the best LEGITIMATE competitor, or (0.0, None).

    Only entries that pass every matching gate are eligible, so accessories and
    wrong-category products are excluded by construction.
    """
    target = (feed_name + " " + size).strip()
    ft = set(E.meaningful_tokens(feed_name))
    best = (0.0, None)
    for c in cat:
        if not E.is_supplement(c["name"]):            continue   # BUG5: no shaker/hoodie/bottle
        if not E.brand_ok(brand, c["name"], c["source"]):        continue
        if not E.forms_ok(feed_name, c["name"]):      continue
        if not E.category_ok(feed_name, c["name"]):   continue
        if not E.distinctiveness_ok(feed_name, brand, c["name"]): continue
        # rank by product-line overlap, then by title jaccard — accessories already gone
        ct = set(E.meaningful_tokens(c["name"]))
        core = len(ft & ct) / max(len(ft | ct), 1)
        score = max(core, E.jaccard(feed_name, c["name"]))
        if score > best[0]:
            best = (score, c)
    return best


def tier(j):
    return ("SANGAT MIRIP" if j >= 0.85 else "MIRIP" if j >= 0.65
            else "SEDANG" if j >= 0.45 else "JAUH")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    cat = E.load_catalog()
    rp = Path(args.report)
    if not rp.exists():
        sys.exit(f"ERROR: report not found: {rp}\n"
                 f"       run the engine first (python3.11 competitor9_engine.py)")
    rep = list(csv.DictReader(open(rp, encoding="utf-8-sig")))

    rows = []
    for r in rep:
        nm, brand, size = r.get("TranslationName") or "", r.get("Brand") or "", r.get("Size") or ""
        j, c = nearest(nm, brand, size, cat)
        if c is not None:
            ss = E.size_status((nm + " " + size).strip(), c["name"])
            rows.append(dict(name=nm, brand=brand, size=size, j=j, cand=c["name"], ss=ss,
                             g1=E.category(nm), g2=E.category(c["name"]), usd=c["usd"],
                             src=c["source"], reason=r.get("reason", "")))
        else:
            rows.append(dict(name=nm, brand=brand, size=size, j=0.0, cand="", ss="", g1="", g2="",
                             usd="", src="", reason=r.get("reason", "")))
    rows.sort(key=lambda x: -x["j"])

    L = []
    L.append("=" * 96)
    L.append(f"SEBERAPA BEDA — {len(rows)} produk sisa (tidak ter-match di 9 situs UK)")
    L.append("=" * 96)
    bands = Counter(tier(x["j"]) for x in rows)
    for t in ["SANGAT MIRIP", "MIRIP", "SEDANG", "JAUH"]:
        L.append(f"  {t:14s} {bands[t]:3d} produk")
    L.append("")
    L.append("  Alasan tidak di-match:")
    for k, v in Counter(x["reason"].split("(")[0].strip() for x in rows).most_common():
        L.append(f"    {v:3d}  {k}")
    L.append("")
    L.append("  Beda GENRE (produk beda senyawa/jenis) pada kandidat terdekat:")
    gc = Counter((x["g1"], x["g2"]) for x in rows if x["g1"] and x["g2"] and x["g1"] != x["g2"])
    for (a, b), v in gc.most_common(10):
        L.append(f"    {v:3d}x  {a} vs {b}")
    L.append("")
    L.append("=" * 96)
    L.append("DETAIL per produk (mirip -> jauh)")
    L.append("=" * 96)
    for x in rows:
        mark = ""
        if x["g1"] and x["g2"] and x["g1"] != x["g2"] and "other" not in (x["g1"], x["g2"]):
            mark += " [GENRE BEDA]"
        if x["ss"] == "conflict":
            mark += " [UKURAN BEDA]"
        L.append(f"\n[{x['j']:.2f}] {tier(x['j']):12s}{mark}")
        L.append(f"    FEED : {x['name']}  ({x['size']})  [{x['brand']}]")
        if x["cand"]:
            L.append(f"    DEKAT: {x['cand']}  ${x['usd']} ({x['src']}) "
                     f"size={x['ss']} genre={x['g1']}->{x['g2']}")
        else:
            L.append("    DEKAT: (brand tidak ada di katalog 9 situs / kandidat hanya aksesori)")
    txt = "\n".join(L)
    out = Path(args.out)
    out.write_text(txt, encoding="utf-8")
    print(f"WROTE {out}  ({len(txt)} chars, {len(rows)} produk)")
    print("RINGKASAN TIER:", dict(bands))
    print("GENRE BEDA:", dict(gc.most_common(6)))


if __name__ == "__main__":
    main()
