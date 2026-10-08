# 9-Site Creatine Competitor Scraper

Scrapes best competitor prices for 923 creatine products across 9 UK supplement sites.
Real result: **888/923 matched** (Oct 2026).

No proxy needed. No API key needed. Direct HTTP + free Jina Reader fallback.

## Sites

| # | Site | URL / Method |
|---|------|--------------|
| 1 | ActiveSportsNutrition | `activesportsnutrition.co.uk/Search?q=Creatine` (direct) |
| 2 | DolphinFitness | `dolphinfitness.co.uk/en/creatine/list/1..N` (direct) |
| 3 | HollandAndBarrett | via Jina Reader (direct returns a 202 challenge page) |
| 4 | AppliedNutrition | `appliednutrition.uk/products.json` (Shopify JSON) |
| 5 | 10xAthletic | `10xathletic.com/collections/creatine` (direct) |
| 6 | AnimalPak | `uk.animalpak.com/collections/creatine` (direct) |
| 7 | CellucorUk | `cellucor.uk` (direct) |
| 8 | IHerbUk | via Jina Reader fallback |
| 9 | ReflexNutrition | `reflexnutrition.com/products.json` (Shopify JSON) |

## Files (run in order)

| # | File | Does |
|---|------|------|
| 1 | `competitor9.py` | Scrapes all 9 sites → `comp_cache/catalog9.json` |
| 2 | `catalog_brands.py` | Full brand catalogs (Dolphin + ASN) → `comp_cache/catalog_brands.json`. Optional brand args: `python3.11 catalog_brands.py "Optimum Nutrition"` |
| 3 | `competitor9_engine.py` | **Main engine** — matches 923 feed rows vs catalogs → `DropshipProductFeedCreatineOnly.9best.923.csv` + debug + unmatched report |
| 4 | `apply_whitelist.py` | Backfills 3 hand-verified lines (fill-only, never overwrites) |
| 5 | `diffreport.py` | Human-readable audit of unmatched rows → `unmatched_perbedaan.txt` |
| 6 | `regtest.py` | Regression tests (exit 0 = pass) |
| 7 | `competitor_catalog.py` | Older engine (archive / comparison) |
| 8 | `price_engine.py` | Older engine v2 (archive / comparison) |

## Usage

```bash
pip install "scrapling[fetchers]"

# Put your feed next to the scripts:
# DropshipProductFeedCreatineOnly.csv (utf-8-sig, 923 rows)

python3.11 competitor9.py        # scrape 9 sites
python3.11 catalog_brands.py    # full Dolphin + ASN brand catalogs
python3.11 competitor9_engine.py # match → final CSV + debug + unmatched
python3.11 apply_whitelist.py   # optional whitelist backfill
python3.11 diffreport.py        # audit leftovers
python3.11 regtest.py           # regression check
```

## Notes

- Read the feed CSV with `encoding="utf-8-sig"` (BOM).
- Matching: barcode-exact first, then brand + name + size fuzzy (size is a hard block — 187g never matches 500g).
- Best-price tie-break: most-common competitor (catalog coverage).
- Engine output = original columns + `competitor` + `competitorPrice` (USD, FX 1.3233, Oct 2026).
- Fail-closed: uncertain rows stay empty and go to `unmatched_report.csv` — never guessed.
- Network: plain `scrapling` Fetcher + public `https://r.jina.ai/` reader. No proxy, no key, no login.
