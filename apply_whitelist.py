"""Deterministic brand-line whitelist backfill (fail-closed companion to the engine).

Why a whitelist and not an engine heuristic: the three remaining fixable feed lines are
blocked by name/size-status gates (the engine diffs a feed name against a differently named
storefront line), and every fuzzy heuristic I tried for them also let NEW false positives
through (Bio-Synergy Matcha, TWP Glutamine RAW, Alpha Neon Neon Dreams). A whitelist keeps
the engine untouched and makes each added row auditable by hand.

Every entry below was verified by hand against our OWN catalog + the live storefront page:
  * TWP 'Performance Ready Everyday' 375g  == DolphinFitness 'TWP Pre Raw 30 Servings'
      proof: the feed's own ProductInformation says the RAW range "P.R.E (Performance Ready
      Everyday)"; the Dolphin page panel reads 375 g / 12.5 g serving / 30 servings with the
      SAME ingredient list (L-Citrulline, Creatine Mono, Beta Alanine, ...) and the same 6
      flavours -> identical product, different line name.
  * EHP Labs 'Creatine Gummies' 450 g Berry Bliss == DolphinFitness 'EHPlabs OxyShred
      Creatine Gummies 90 Gummies' (slug ...450g...), page panel 90 gummies / 3 / 30 servings.
  * Bio-Synergy 'Active Woman Energise Creatine & Collagen' 150g == HollandAndBarrett
      'Active Woman Energise Creatine & Collagen - 30 servings'  (brand tokens live in the
      URL slug; the catalog stores brand='' for H&B so brand_ok() can never fire).

Only rows whose competitor/competitorPrice are currently EMPTY are written.
"""
import csv, json, re, sys, hashlib, shutil, os

FX = 1.3233
DELIVERABLE = 'DropshipProductFeedCreatineOnly.9best.923.csv'
DEBUG = 'DropshipProductFeedCreatineOnly.9best.debug.csv'
UNMATCHED = 'DropshipProductFeedCreatineOnly.9best.unmatched_report.csv'

# pc -> (competitor_label, competitor_product, url, gbp)
WHITELIST = {
    'TWP036': ('DolphinFitness', 'TWP Pre Raw 30 Servings',
               'https://www.dolphinfitness.co.uk/en/twp-pre-raw-30-servings/453713', 20.95),
    'TWP037': ('DolphinFitness', 'TWP Pre Raw 30 Servings',
               'https://www.dolphinfitness.co.uk/en/twp-pre-raw-30-servings/453713', 20.95),
    'TWP038': ('DolphinFitness', 'TWP Pre Raw 30 Servings',
               'https://www.dolphinfitness.co.uk/en/twp-pre-raw-30-servings/453713', 20.95),
    'TWP103': ('DolphinFitness', 'TWP Pre Raw 30 Servings',
               'https://www.dolphinfitness.co.uk/en/twp-pre-raw-30-servings/453713', 20.95),
    'TWP104': ('DolphinFitness', 'TWP Pre Raw 30 Servings',
               'https://www.dolphinfitness.co.uk/en/twp-pre-raw-30-servings/453713', 20.95),
    'TWP105': ('DolphinFitness', 'TWP Pre Raw 30 Servings',
               'https://www.dolphinfitness.co.uk/en/twp-pre-raw-30-servings/453713', 20.95),
    'EHP136': ('DolphinFitness', 'EHPlabs OxyShred Creatine Gummies 90 Gummies',
               'https://www.dolphinfitness.co.uk/en/ehplabs-oxyshred-creatine-gummies-450g/476124', 17.99),
    'SYN007': ('HollandAndBarrett', 'Active Woman Energise Creatine & Collagen - 30 servings',
               'https://www.hollandandbarrett.com/shop/product/active-woman-energise-creatine-collagen-30-servings-6100022110', 24.99),
}


def main():
    rows = list(csv.DictReader(open(DELIVERABLE, encoding='utf-8-sig')))
    fields = list(rows[0].keys())
    dbg = list(csv.DictReader(open(DEBUG, encoding='utf-8-sig')))

    touched, skipped = [], []
    for i, r in enumerate(rows):
        pc = r['ProductCode']
        if pc not in WHITELIST:
            continue
        if (r.get('competitor') or '').strip():
            skipped.append((i, pc, 'ALREADY FILLED'))
            continue
        label, prod, url, gbp = WHITELIST[pc]
        usd = round(gbp * FX, 2)
        r['competitor'] = label
        r['competitorPrice'] = f'{usd:.2f}'
        touched.append((i, pc, label, prod, gbp, usd))

    # debug side-car (same order as the feed)
    for d in dbg:
        pc = d['ProductCode']
        if pc in WHITELIST and not (d.get('competitor') or '').strip():
            label, prod, url, gbp = WHITELIST[pc]
            d['competitor'] = label
            d['competitorProduct'] = prod
            d['competitorURL'] = url
            d['competitorPriceGBP'] = f'{gbp:.2f}'
            d['competitorPriceUSD'] = f'{gbp * FX:.2f}'
            d['matchScore'] = '1.00'
            d['resolution'] = 'whitelist-brand-line'
            d['candidates'] = '1'

    out = DELIVERABLE
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(DEBUG, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(dbg[0].keys()))
        w.writeheader()
        w.writerows(dbg)

    hit = sum(1 for r in rows if (r.get('competitor') or '').strip())
    print(f'rows touched : {len(touched)}  (skipped already-filled: {len(skipped)})')
    for t in touched:
        print('  +', t)
    for s in skipped:
        print('  ! skipped', s)
    print(f'HIT now      : {hit}/923  ({hit/923*100:.1f}%)')

    # unmatched report refresh
    un = [r for r in dbg if not (r.get('competitor') or '').strip()]
    with open(UNMATCHED, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['RowIndex', 'ProductCode', 'TranslationName', 'Size', 'Brand', 'Flavour', 'Barcode'])
        for i, d in enumerate(dbg):
            if not (d.get('competitor') or '').strip():
                w.writerow([i, d['ProductCode'], d['TranslationName'], d['Size'], d['Brand'], '', d['Barcode']])
    print(f'unmatched now: {len(un)} rows')
    return touched


if __name__ == '__main__':
    main()
