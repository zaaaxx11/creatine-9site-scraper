#!/usr/bin/env python3.11
"""
regtest.py — regression harness for the 5 BUG fixes in competitor9_engine.py.

Sections
  A. Unit assertions on the engine's OWN functions (BUG1 dedup, BUG2 is_supplement,
     BUG3 size_status, BUG4 line_similar/density_ok).
  B. Known FALSE-POSITIVE regression set (each must stay REJECTED).
  C. Known FALSE-NEGATIVE recovery set (each must now MATCH the right product).
  D. GLOBAL false-positive audit over ALL 923 resolved feed rows on the current engine.
  E. Baseline-vs-fixed diff (HIT delta + newly-matched rows) by running the pristine
     /tmp/bl_run/engine_baseline.py in isolation.

Exit code 0 = all unit/regression assertions pass; nonzero = failure (raw output shown).
"""
import sys, os, csv, json, subprocess, shutil
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import competitor9_engine as E   # noqa: E402

BL_DIR = Path("/tmp/bl_run")
BL_ENG = BL_DIR / "engine_baseline.py"
FIX_DBG = ROOT / "DropshipProductFeedCreatineOnly.9best.debug.csv"

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))

# ------------------------------------------------------------------ fixtures
cat = E.load_catalog()
pop = Counter(E.pop_key(c["name"]) for c in cat)
by_bc = {}
for c in cat:
    b = "".join(ch for ch in (c.get("barcode") or "") if ch.isdigit())
    if b:
        by_bc.setdefault(b, []).append(c)

def resolve(name, brand, size):
    r = {"TranslationName": name, "Brand": brand, "Size": size, "Barcodes": ""}
    return E.resolve_row(r, cat, by_bc, pop)

# ------------------------------------------------------------------ SECTION A
print("\n=== SECTION A — unit assertions on engine functions ===")

# BUG1: dedup must keep flavour variants (old key was (source, url))
raw = []
for p in E.CATS:
    raw += json.loads(Path(p).read_text())
old_key_len = len({(c.get("source"), c.get("url")) for c in raw})
check("BUG1 candidate pool > old (source,url) dedup",
      len(cat) > old_key_len, f"new={len(cat)}  old={old_key_len}  raw={len(raw)}")
abe_variants = {c["name"] for c in cat
                if (c.get("url") or "").lower().rstrip("/").endswith("abe-all-black-everything-375g")}
check("BUG1 all ABE flavour variants survive (>=10 distinct names on one URL)",
      len(abe_variants) >= 10, f"{len(abe_variants)} distinct ABE names kept")

# BUG2: free-gift phrasing must not mark a real supplement as an accessory
check("BUG2 'ABE - 30 Servings ... FREE Shaker' IS a supplement",
      E.is_supplement("Applied Nutrition ABE - 30 Servings - Special Offer - FREE Shaker"))
check("BUG2 'ABE Pump 500g ... FREE Shaker' IS a supplement",
      E.is_supplement("Applied Nutrition ABE Pump 500g - Special Offer - FREE Shaker"))
for acc in ["ABE Shaker 700ml", "ABE Shaker 400ml", "Hoodie", "ABE Bottle",
            "Applied Nutrition ABE Water Jug (2.5L) Black",
            "Applied Nutrition ABE Shaker (700 ml) Black"]:
    check(f"BUG2 '{acc}' stays an ACCESSORY", not E.is_supplement(acc))

# BUG3: size tiers
check("BUG3 500g vs 505g -> ok",        E.size_status("X 500g", "X 505g") == "ok")
check("BUG3 500g vs 520g -> near",      E.size_status("X 500g", "X 520g") == "near")
check("BUG3 1.8kg vs 1.89kg -> near",   E.size_status("Reflex Growth Matrix 1.8kg", "Reflex Growth Matrix 1.89kg") == "near")
check("BUG3 500g vs 700g -> conflict",  E.size_status("X 500g", "X 700g") == "conflict")
check("BUG3 1kg vs 4kg -> conflict",    E.size_status("HR Labs 1kg", "HR Labs 4kg") == "conflict")

# BUG4: product-line similarity + density gate
check("BUG4 line_similar HR Labs BASIC 510g <-> 30 Servings",
      E.line_similar("HR Labs BASIC 510g Super Fresh OJ", "HR Labs Basic 30 Servings", "HR Labs"))
check("BUG4 line_similar ABE 375g <-> ABE 30 Servings",
      E.line_similar("Applied Nutrition ABE (All Black Everything) 375g Tropical",
                     "Applied Nutrition ABE 30 Servings", "Applied Nutrition"))
check("BUG4 line_similar REJECTS Loaded Creatine <-> Loaded Pre",
      not E.line_similar("RYSE Loaded Creatine 393g Unflavoured", "Ryse Loaded Pre 30 Servings", "RYSE"))
check("BUG4 line_similar REJECTS Creatine <-> L-Glycine",
      not E.line_similar("HR Labs Creatine Monohydrate 300g", "HR Labs L-Glycine 300g", "HR Labs"))
check("BUG4 density_ok 510g/30 = 17g OK", E.density_ok("HR Labs BASIC 510g", "HR Labs Basic 30 Servings"))
check("BUG4 density_ok 510g/2 = 255g absurd -> reject",
      not E.density_ok("HR Labs BASIC 510g", "HR Labs Basic 2 Servings"))

# ------------------------------------------------------------------ SECTION B
print("\n=== SECTION B — known false positives must STAY REJECTED ===")
def prod_ok(name, brand, size, forbidden_token, forbidden_cat=None):
    res = resolve(name, brand, size)
    p = res["prod"]
    if not p:
        return True, "(no match)"
    if forbidden_token and forbidden_token.lower() in p.lower():
        return False, f"WRONGLY matched -> {p}"
    if forbidden_cat and E.category(p) == forbidden_cat:
        return False, f"WRONGLY matched ({forbidden_cat}) -> {p}"
    return True, f"-> {p}"

for nm, br, sz, forb_tok, forb_cat, label in [
    ("HR Labs Creatine Monohydrate 300g", "HR Labs", "300g", "glycine", None, "Creatine !-> L-Glycine"),
    ("Per4m Creatine 400g Fizzy Bubblegum Bottles", "Per4m", "400g", "relax", None, "Per4m Creatine !-> Relax"),
    ("Bulk Dope Pre Workout 510g Fruit Punch", "Bulk", "510g", None, "creatine", "Dope Pre !-> Creatine"),
    ("Cellucor Flavoured Creatine 203g Icy Blue Raspberry", "Cellucor", "203g", "c4 sport", None, "Cellucor Creatine !-> C4 Sport Pre"),
    ("Applied Nutrition ABE (All Black Everything) 375g Tropical", "Applied Nutrition", "375g", "pump", None, "ABE !-> ABE Pump 3G"),
    ("RYSE Loaded Creatine 393g Unflavoured", "RYSE", "393g", "loaded pre", None, "RYSE Loaded !-> Loaded Pre"),
]:
    good, det = prod_ok(nm, br, sz, forb_tok, forb_cat)
    check(f"FP {label}", good, det)

# Per4m creating-gummies style row (scan feed) !-> Relax
gum = [r for r in csv.DictReader(open(ROOT/"DropshipProductFeedCreatineOnly.csv", encoding="utf-8-sig"))
       if "gumm" in (r.get("TranslationName") or "").lower() and "per4m" in ((r.get("Brand") or "").lower())]
if gum:
    g = gum[0]
    good, det = prod_ok(g["TranslationName"], g["Brand"], g.get("Size") or "", "relax", None)
    check("FP Per4m Creatine Gummies !-> Relax", good, det)
else:
    print("  [skip] no Per4m gummies feed row present")

# no accessory may ever be a competitor
bad_acc = [ (r.get("TranslationName"), resolve(r.get("TranslationName") or "", r.get("Brand") or "", r.get("Size") or "")["prod"])
            for r in csv.DictReader(open(ROOT/"DropshipProductFeedCreatineOnly.csv", encoding="utf-8-sig")) ]
acc_hits = [x for x in bad_acc if x[1] and not E.is_supplement(x[1])]
check("no feed row matched to an ACCESSORY anywhere", not acc_hits, f"{len(acc_hits)} offender(s)")

# ------------------------------------------------------------------ SECTION C
print("\n=== SECTION C — known false negatives must now MATCH ===")
def expects(name, brand, size, want_sub, label):
    res = resolve(name, brand, size)
    good = want_sub.lower() in (res["prod"] or "").lower()
    check(f"RECOVER {label}", good, f"-> {res['prod']!r} (${res['price']}) score={res['score']:.2f} why={res['why']}")

expects("HR Labs BASIC 510g Super Fresh OJ", "HR Labs", "510g", "Basic 30 Servings", "HR Labs Basic 510g -> 30 Servings")
expects("Reflex Nutrition Growth Matrix 1.8kg Fruit", "Reflex Nutrition", "1.8kg", "Growth Matrix", "Growth Matrix 1.8kg -> 1.89kg")
expects("Applied Nutrition ABE (All Black Everything) 375g Tropical", "Applied Nutrition", "375g", "ABE", "ABE 375g -> ABE 30 Servings")

# ------------------------------------------------------------------ SECTION D
print("\n=== SECTION D — GLOBAL FP audit over all 923 rows (current engine) ===")
feed = list(csv.DictReader(open(ROOT/"DropshipProductFeedCreatineOnly.csv", encoding="utf-8-sig")))
rows_defs = []
for r in feed:
    nm, br, sz = r.get("TranslationName") or "", r.get("Brand") or "", r.get("Size") or ""
    res = resolve(nm, br, sz)
    if not res["prod"]:
        continue
    flags = []
    if not E.is_supplement(res["prod"]):
        flags.append("ACCESSORY")
    gf, gc = E.category(nm), E.category(res["prod"])
    if gf and gc and gf != gc and "other" not in (gf, gc):
        flags.append(f"GENRE {gf}->{gc}")
    fcomp = set(E.meaningful_tokens(nm)) & E.COMPOUND
    ccomp = set(E.meaningful_tokens(res["prod"])) & E.COMPOUND
    if fcomp and ccomp and not (fcomp & ccomp):
        flags.append(f"COMPOUND {sorted(fcomp)}->{sorted(ccomp)}")
    if flags:
        rows_defs.append((nm, res["prod"], flags))
print(f"  matched rows: {sum(1 for r in feed if resolve(r.get('TranslationName') or '', r.get('Brand') or '', r.get('Size') or '')['prod'])}/{len(feed)}")
print(f"  suspect rows: {len(rows_defs)}")
for nm, p, fl in rows_defs[:25]:
    print(f"    {fl}  |  {nm[:46]}  =>  {p[:52]}")
check("GLOBAL audit: zero accessory matches", not any("ACCESSORY" in f for _, _, f in rows_defs))
check("GLOBAL audit: zero compound mismatches", not any(any(x.startswith('COMPOUND') for x in f) for _, _, f in rows_defs))

# ------------------------------------------------------------------ SECTION E
print("\n=== SECTION E — baseline vs fixed (full run) ===")
if BL_ENG.exists():
    for f in BL_DIR.glob("*.debug.csv"):
        f.unlink()
    subprocess.run([sys.executable, str(BL_ENG)], cwd=str(BL_DIR),
                   stdout=open("/tmp/bl_run/run.log", "w"), stderr=subprocess.STDOUT, check=False)
    bdbg = next((p for p in BL_DIR.glob("*.debug.csv")), None)
    fdbg = FIX_DBG
    if bdbg and fdbg.exists():
        def load(p):
            return {"|".join([r.get("ProductCode") or "", r.get("TranslationName") or "",
                              r.get("Size") or ""]): (r.get("competitor") or "", r.get("competitorProduct") or "")
                    for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
        B, F = load(bdbg), load(fdbg)
        bh = sum(1 for v in B.values() if v[0])
        fh = sum(1 for v in F.values() if v[0])
        print(f"  baseline HIT {bh}/{len(B)} ({100*bh/len(B):.1f}%)   fixed HIT {fh}/{len(F)} ({100*fh/len(F):.1f}%)")
        print(f"  DELTA = +{fh-bh} hits ({(fh-bh)/len(B)*100:+.1f} pp)")
        new = [(k, F[k]) for k in F if F[k][0] and not B.get(k, ("", ""))[0]]
        lost = [(k, B[k]) for k in B if B[k][0] and not F.get(k, ("", ""))[0]]
        print(f"  newly matched: {len(new)}   lost matches: {len(lost)}")
        print("  -- 20 newly-matched rows (feed => competitor product) --")
        for k, (comp, prod) in new[:20]:
            nm = k.split("|")[1]
            print(f"     {nm[:48]:48s} => {comp:20s} {prod[:44]}")
        if lost:
            print("  -- LOST matches --")
            for k, (comp, prod) in lost[:20]:
                print(f"     {k.split('|')[1][:48]} => {prod[:48]}")
        check("full-run HIT improved", fh > bh, f"{bh} -> {fh}")
        check("no previously-matched row was LOST", not lost, f"{len(lost)} lost")
else:
    print(f"  [skip] baseline engine not found at {BL_ENG}")

# ------------------------------------------------------------------ verdict
print("\n" + "=" * 70)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(1 if FAIL else 0)
