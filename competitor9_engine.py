#!/usr/bin/env python3.11
"""
Tropicana BEST-PRICE engine v5 — 923 creatine-containing products x 9 UK sites.
Gates (precision-first):
  B barcode-exact  >  C brand-gate(fixed) + category-gate + distinctiveness-gate + size
  D best price = min(USD); tie -> most-common competitor (catalog coverage)
NOTE: every feed row contains creatine (per Raja) so ALL 923 are in scope; rows whose
      PRODUCT is a pre-workout/gainer/hydration are matched to those product pages.
"""
import json, re, csv
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
CATS = [ROOT/"comp_cache"/"catalog9.json", ROOT/"comp_cache"/"catalog_brands.json"]
FEED = ROOT/"DropshipProductFeedCreatineOnly.csv"
OUT  = ROOT/"DropshipProductFeedCreatineOnly.9best.923.csv"
DBG  = ROOT/"DropshipProductFeedCreatineOnly.9best.debug.csv"
UMP  = ROOT/"DropshipProductFeedCreatineOnly.9best.unmatched_report.csv"
FX_GBP_USD = 1.323338          # open.er-api.com 2026-10-05

def log(*a): print(*a, flush=True)

NOISE = re.compile(r'\b(micronised|micronized|monohydrate|mono|c powder|powder|capsules|capsule|caps|tablets|tablet|tabs|'
                   r'servings|serving|vegan|unflavoured|unflavored|flavoured|flavored|pack of|pack|bundle|value pack|'
                   r'twin pack|sponsored|choice|best seller|new|free|gift|advent calendar|shaker|bottle)\b')
SITE_BRAND = {"AppliedNutrition": ["applied", "nutrition"], "10xAthletic": ["10x", "athletic"],
              "AnimalPak": ["animal", "pak"], "ReflexNutrition": ["reflex", "nutrition"],
              "CellucorUk": ["cellucor"]}
GENERIC_BRAND = {"nutrition","sports","sport","supplements","supplement","fitness","labs","lab",
                 "health","performance","natural","science","sciences","research","formula","formulas",
                 "foods","food","group","holdings","uk","the","co","ltd","inc","official","store","shop"}

def brand_ok(brand, cand, source=""):
    site = SITE_BRAND.get(source)
    if site:                                   # brand-owned store
        fb = re.sub(r'[^a-z0-9]', '', (brand or "").lower())
        return any(t in fb for t in site)
    b = re.sub(r'[^a-z0-9]', '', (brand or "").lower())
    c = re.sub(r'[^a-z0-9]', '', (cand or "").lower())
    if b and b in c: return True
    btoks = [t for t in re.findall(r'[a-z0-9]+', (brand or "").lower())
             if len(t) >= 2 and not t.isdigit() and t not in GENERIC_BRAND]
    if not btoks: return False                 # purely generic brand -> cannot verify
    ctoks = set(re.findall(r'[a-z0-9]+', (cand or "").lower()))
    return any(t in ctoks for t in btoks)

def norm(s):
    s = (s or "").lower()
    s = re.sub(r'[^a-z0-9\s\.]', ' ', s)
    s = NOISE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def clean_name(s):
    """Strip markdown/image noise that leaks into some scraped titles."""
    s = str(s or "").split("](")[0]
    s = re.sub(r'https?://\S+', ' ', s)
    s = re.sub(r'!?\S+\.(?:jpg|jpeg|png|gif|webp)\S*', ' ', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' -|')
    return s[:140]

def size_tokens(s):
    s = s or ""
    toks  = []
    pm = re.search(r'(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:s\s*)?'
                   r'(kg|g|ml|l|bars?|tabs?|caps?|sachets?|pieces?|packs?|servings?)', s, re.I)
    if pm: toks.append(f"pack{pm.group(1)}")
    toks += re.findall(r'\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*(?:kg|g|ml|l|tabs|caps|capsules|gummies|servings|chews)?', s, re.I)
    toks += re.findall(r'(?<![x\d\.])\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b', s, re.I)
    toks += re.findall(r'\d+\s*(?:tab|tabs|tablet|tablets|cap|caps|capsule|capsules|gummy|gummies|'
                       r'serving|servings|chew|chews|sachet|sachets|stick|sticks|softgel|softgels|'
                       r'piece|pieces|bar|bars|can|cans|pack|packs|drop|drops)\b', s, re.I)
    return [t.strip().lower().replace(" ", "") for t in toks]

PACK = re.compile(r'(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:s\s*)?'
                  r'(?:kg|g|ml|l|bars?|tabs?|caps?|sachets?|pieces?|packs?|servings?)', re.I)
# count of discrete PIECES in a box (bars, caps, gummies...) — deliberately excludes "servings"
BOXCOUNT = re.compile(r'(\d+)\s*(?:tabs?|tablets?|caps?|capsules?|gummies?|gummy|chews?|sachets?|'
                      r'sticks?|softgels?|pieces?|bars?|packs?|cans?|shots?|gels?)\b', re.I)

def pack_count(s):
    m = PACK.search(s or "")
    return int(m.group(1)) if m else None

def box_count(s):
    """Number of discrete items in the pack (12x75g -> 12; '12 Bars' -> 12; '500g' -> None)."""
    p = pack_count(s)
    if p: return p
    m = BOXCOUNT.search(s or "")
    return int(m.group(1)) if m else None

COUNT_UNITS = {"tab","tabs","tablet","tablets","cap","caps","capsule","capsules","gummy","gummies",
               "chew","chews","serving","servings","stick","sticks","packet","packets","softgel","softgels",
               "piece","pieces","bar","bars","sachet","sachets","lozenge","lozenges"}
FORMS = [("gummy", r'gumm(?:y|ies)'), ("chew", r'\bchews?\b'), ("softgel", r'softgel'),
         ("tab", r'tablets?|\btabs?\b'), ("caps", r'capsules?|\bcaps\b'), ("sachet", r'sachets?'),
         ("stick", r'\bsticks?\b'), ("shot", r'\bshots?\b'), ("can", r'\bcans?\b'),
         ("gel", r'\bgel\b|\bgels\b'), ("liquid", r'liquid'), ("bar", r'\bbars?'), ("powder", r'\bpowders?\b')]

def form_of(s):
    t = (s or "").lower()
    for name, rx in FORMS:
        if re.search(rx, t): return name
    if re.search(r'\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b', t) and re.search(r'creatine|crea|monohydrate|mono|hcl|creapure', t):
        return "powder"
    return None

def forms_ok(a, b):
    fa, fb = form_of(a), form_of(b)
    if not (fa and fb and fa != fb): return True
    # caps <-> tab = same oral solid-dose unit (e.g. '180 Caps' vs '180 Tablets'); accept when counts match or unstated
    if {fa, fb} == {"caps", "tab"}:
        rx = r'(\d+)\s*(?:capsules?|\bcaps\b|tablets?|\btabs?\b)'
        ca = re.search(rx, a or "", re.I); cb = re.search(rx, b or "", re.I)
        if not ca or not cb or ca.group(1) == cb.group(1): return True
    return False

def to_grams(tok):
    # MULTIPLIER packs ("30x10g", "20 x 60 ml", "20x60g") -> total weight of the box
    mm = re.search(r'(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b', tok, re.I)
    if mm:
        n = int(mm.group(1)); per = float(mm.group(2)); u = mm.group(3).lower()
        per = per*1000 if u in ("kg", "l") else per
        return n*per
    m = re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b', tok, re.I)
    if m:
        n = float(m.group(1)); u = m.group(2).lower()
        return n*1000 if u in ("kg","l") else n
    o = re.search(r'(\d+(?:\.\d+)?)\s*(?:fl\s*)?oz\b', tok, re.I)   # iHerb imperial
    if o: return float(o.group(1))*28.3495
    p = re.search(r'(\d+(?:\.\d+)?)\s*lbs?\b', tok, re.I)
    if p: return float(p.group(1))*453.592
    return None

def parse_size(tok):
    g = to_grams(tok)
    if g is not None: return ('w', g)
    m = re.search(r'(\d+)\s*([a-z]+)', tok)
    if m and m.group(2) in COUNT_UNITS: return ('c', float(m.group(1)))
    return (None, None)

SERV = re.compile(r'(\d+)\s*(?:serv(?:ing)?s?|sachets?|packets?|stick(?:s| packs)?|scoops?)\b', re.I)
# feed nutrition label: 'Serving Size: 6.6g' / 'Serving Size: 4 gummies' -> per-serving grams
NUTR_SS = re.compile(r'serving\s*size\s*[:\-]?\s*([\d.]+)\s*(g|mg|ml)\b', re.I)
def servings(s):
    m = SERV.search(s or "")
    return int(m.group(1)) if m else None

def servings_compatible(feed, cand):
    """RECOVERY path for the dominant recall-loss: catalog expresses size in
    SERVINGS while the feed expresses GRAMS (same product). Safe only when EXACTLY
    ONE side carries servings; a servings-vs-servings difference is a real conflict."""
    ff, cf = servings(feed), servings(cand)
    if (ff is None) == (cf is None): return False     # both/neither -> not our path
    return True                                       # one side grams, other servings

def size_status(target, cand):
    """Compare expressed sizes. Returns one of:
      ok        -> same size (relative weight difference <= 2%)
      near      -> close size (2% < rel diff <= 12%); caller MUST demand stronger title overlap
      one-none  -> exactly one side expresses a size
      both-none -> neither side expresses a size
      conflict  -> sizes present but genuinely different (>12%), or unit/kind differs
    BUG3 fix: a tiny size difference (e.g. 1.8kg vs 1.89kg) is the SAME product, while
    1kg vs 4kg stays a conflict. 'near' is treated like 'ok' only behind a stricter gate.
    """
    tl, cl = (target or "").lower(), (cand or "").lower()
    # BARS: a 12x75g box must never price-match a single bar (and vice-versa) -> require equal box count
    if re.search(r'\bbars?\b', tl) or re.search(r'\bbars?\b', cl):
        bf, bc = box_count(target), box_count(cand)
        if bf and bc and bf == bc: return "ok"
        return "conflict"
    sta, stc = size_tokens(target), size_tokens(cand)
    if not sta and not stc: return "both-none"
    if not sta or not stc:   return "one-none"
    best = None
    for a in sta:
        for b in stc:
            ka, va = parse_size(a); kb, vb = parse_size(b)
            if ka is None or kb is None or ka != kb: continue
            if ka == 'w':
                rel = abs(va-vb)/max((va+vb)/2, 1e-9)
                st = "ok" if rel <= 0.02 else ("near" if rel <= 0.12 else "conflict")
            else:
                st = "ok" if va == vb else "conflict"
            if st == "ok": return "ok"      # best possible -> no need to look further
            if best != "ok": best = st
    return best or "conflict"

# ---- CATEGORY gate (product genre must not contradict) --------------------
# BUG-GUMMY: 'gummy/gummies' is a PRODUCT only when it is the head noun. In a flavour
# phrase ('Watermelon Gummy Candy', 'Gummy Hixxy Bear', 'Sour Gummy Worm') it is just a
# flavour and must NOT set the genre (else a Heavy Duty / Pre-Workout row is misread as a
# gummy product and its identical catalog entry is rejected by the STRICT genre check).
_GUMMY_COMPOUND = (r'(?:creatine|crea|creapure|monohydrate|mono|hcl|collagen|vitamin\w*|multivit\w*|'
                   r'biotin|omega|probiotic|magnesium|zinc|iron|fibre|fiber|beauty|hair|nail|skin|acv|vinegar|'
                   r'melatonin|turmeric|ashwagandha|bcaa|eaa|amino\w*|electrolyt\w*)')
def _gummy_is_product(t):
    for m in re.finditer(r'\bgumm(?:y|ies)\b', t):
        before, after = t[:m.start()], t[m.end():]
        if re.search(r'\d+\s*(?:vegan\s+)?$', before):            # '80 Gummies'
            return True
        if re.search(_GUMMY_COMPOUND + r'\s*\+?\s*$', before):     # 'Creatine Gummies'
            return True
        # head noun: only a size/count may follow ('Gummies 375g', 'Gummies', 'Gummies 60')
        if re.match(r'^\s*(?:\d+(?:\s*[x×]\s*\d+)?\s*(?:g|mg|kg|ml|l|servings?|serves?|ct)?\s*)?$', after):
            return True
    return False

def category(s):
    t = (s or "").lower()
    if re.search(r'\bbars?\b', t): return "bar"
    if re.search(r'\bdrink\b|\bcans?\b|\brtd\b|energy shot|\bshots?\b', t): return "drink"
    if re.search(r'\bstak\b|\bstack\b|multivit|multi[-\s]?vitamin|\bvitamin|omega|fish oil|\bzma\b|probiotic|greens|superfood|test booster', t): return "stack"
    # preworkout BEFORE gummies: 'Gummy Hixxy Bear' is a FLAVOUR of Dynamite Pre-Workout, not a gummy product
    if re.search(r'pre[-\s]?work\w*|\bpump\b|\bstim\b|all black everything|\babe\b|preworkout', t): return "preworkout"
    # explicit gummy product beats creatine ('Creatine Gummies' IS a gummy); but a flavour
    # phrase ('... Gummy Candy') must NOT — only the head noun sets the genre (BUG-GUMMY).
    if re.search(r'gumm', t) and ('preworkout' in t or _gummy_is_product(t)):
        return "gummies"
    if re.search(r'creatine|\bcrea\b|creapure', t): return "creatine"
    if re.search(r'hydrat(?:ion|ing)\b|electrolyt', t): return "hydration"
    if re.search(r'\bchews?\b', t): return "gummies"
    if re.search(r'\bmass\b|weight gain|gainer', t): return "gainer"
    if re.search(r'\bprotein\b|whey|isolate|casein|\bshake\b', t): return "protein"
    if re.search(r'amino|eaa|bcaa|glutamine|glycine|taurine|arginine|citrulline|tyrosine|carnitine|\balanin', t): return "amino"
    return "other"

# non-supplement merchandise/apparel -> NEVER a valid competitor price for a supplement
ACCESSORY = re.compile(r'\b(shaker|bottle|jug|flask|hoodie|hoody|sweatshirt|jumper|t[-\s]?shirt|\btee\b|'
                       r'\bvest\b|\bcap\b|\bhat\b|beanie|snapback|backpack|\bbag\b|lunch|duffle|'
                       r'strap|wrist|glove|gloves|\bbelt\b|sock|socks|towel|keyring|mug|\bsleeve\b|'
                       r'apparel|clothing|merch|poster|\bpen\b|book|sticker|lanyard|wristband|'
                       r'\bmixer\b|whisk|scoop|storage|container|funnel|pill\s*box|drops)\b')

# ---- BUG2: free-gift phrasing must not turn a real supplement into an accessory ----
# "ABE - 30 Servings - Special Offer - FREE Shaker" is a genuine ABE (the shaker is a gift);
# strip such gift/offer phrasing BEFORE the ACCESSORY test so a real accessory *named* as the
# product ("ABE Shaker 700ml", "Hoodie", "Bottle") is still rejected, but a free-gift mention is not.
FREE_GIFT = re.compile(r'\+?\s*\bfree\s+(shaker|bottle|jug|flask|scoop|mixer|whisk|bag|t-?shirt|'
                       r'\btee\b|cap\b|hat|beanie|keyring|mug|towel|strap|socks?|gloves?|gift)\b', re.I)
OFFER_NOISE = re.compile(r'\bspecial\s+offer\b|\bprice\s+drop\b|\bfree\s+gift\b|\bbonus\b', re.I)
GIFT_STRIP = (FREE_GIFT, OFFER_NOISE)

def strip_gifts(s):
    t = (s or "").lower()
    for rx in GIFT_STRIP:
        t = rx.sub(' ', t)
    return t

def is_supplement(s):
    """True unless the title names genuine merchandise/apparel.
    Free-gift/offer phrasing is stripped first (BUG2 fix)."""
    return not ACCESSORY.search(strip_gifts(s))

def category_ok(feed, cand):
    if not is_supplement(cand): return False         # shaker/hoodie/bottle/drops -> reject
    cf, cc = category(feed), category(cand)
    STRICT = ("gummies", "drink", "bar", "hydration")
    if cf in STRICT or cc in STRICT:                 # strict genres must agree on BOTH sides
        return cf == cc
    if cf == "other" or cc == "other": return True    # unknown genre -> no constraint
    return cf == cc                                   # else genres must agree

# ---- DISTINCTIVENESS gate (feed's product-line words must appear) ---------
FLAVOUR = set("""apple blackcurrant blackberry raspberry strawberry blueberry watermelon mango
lemon lime orange grape cherry peach pineapple coconut banana chocolate chocolatey cocoa vanilla
caramel toffee salted cookies cream mint spearmint peppermint cola cherry cola tropical citrus
melon kiwi passionfruit passion fruit sour candy bubblegum grapefruit pomegranate lychee pear
apricot cranberry elderflower ginger mocha coffee espresso salted caramel peanut butter""".split())
GENERIC_TOK = set("""creatine crea monohydrate mono micronised micronized powder pre workout
mass gainer gain weight protein whey isolate casein hydration hydrating electrolyte electrolytes
energy amino aminos eaa bcaa glutamine bar bars gummy gummies chew chews capsule capsules caps
tablet tablets tabs softgel softgels serving servings sachet sachets stick sticks liquid drink
shake shakes supplement supplements nutrition sports sport fitness labs health performance natural
science sciences research formula formulas original classic new ultra extreme xtreme everyday ready
vegan flavoured flavored flavour flavor unflavoured unflavored high stim non pump blend complex
matrix support daily max plus pro active advanced essential essentials complete total""".split()) | FLAVOUR

def distinctiveness_ok(feed, brand, cand):
    """For gummies/other long titles, require SOME shared non-flavour distinctive word,
    OR a strong overall title overlap. Flavour words alone never satisfy a genre with
    several flavours (avoids Gummies-Berry -> Monohydrate-Berry)."""
    bt = set(re.findall(r'[a-z0-9]+', (brand or "").lower()))
    ct = set(re.findall(r'[a-z0-9]+', (cand or "").lower()))
    ft = [t for t in re.findall(r'[a-z0-9]+', (feed or "").lower())
          if len(t) >= 3 and not re.search(r'\d', t) and t not in GENERIC_TOK and t not in bt]
    cts = {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in ct}
    if any(t in ct or (t[:-1] if len(t) > 3 and t.endswith("s") else t) in cts for t in ft):
        return True       # distinctive word shared (plural-normalised)
    if not ft: return True                          # nothing distinctive -> can't check
    # BUG-BARE: the candidate carries NO distinctive word of its own (a bare product title
    # such as 'Applied Nutrition Creatine Gummies 80 Gummies' / 'Warrior Creatine Bar 12 Bars'
    # / 'Alpha Neon Neon Dreams 225g'). Every extra word in the FEED title is flavour or
    # marketing, so demanding 0.55 Jaccard wrongly blocks the SAME product. The upstream
    # gates (brand + forms + category + exact size/count + compound) already pin identity,
    # so a softer overlap bar is safe here.
    ctd = [t for t in ct
           if len(t) >= 3 and not re.search(r'\d', t) and t not in GENERIC_TOK and t not in bt]
    if not ctd:
        return jaccard(feed, cand) >= 0.40
    return jaccard(feed, cand) >= 0.55              # else demand strong overlap

def distinct_weak(feed, brand, cand):
    """True when the feed title has NO distinctive word to anchor on -> stricter score."""
    bt = set(re.findall(r'[a-z0-9]+', (brand or "").lower()))
    ft = [t for t in re.findall(r'[a-z0-9]+', (feed or "").lower())
          if len(t) >= 3 and not re.search(r'\d', t) and t not in GENERIC_TOK and t not in bt]
    return len(ft) == 0

def jaccard(target, cand):
    ta, ca = norm(target), norm(cand)
    w1, w2 = set(ta.split()), set(ca.split())
    union = len(w1 | w2)
    j = (len(w1 & w2)/union) if union else 0.0
    tb = ta.split()[0] if ta.split() else ""
    if tb and tb in w2: j = min(1.0, j+0.10)
    return j

# ---- BUG4: servings<->gram equivalence needs TITLE-PREFIX similarity, not full jaccard ----
# Full-title jaccard is diluted by flavour + size words, so "HR Labs Basic 510g Super Fresh OJ"
# vs "HR Labs Basic 30 Servings" scores 0.475 and is wrongly blocked. We instead compare the
# leading *meaningful* product tokens (the product line: ignoring brand words, sizes/numbers,
# flavours and generic filler). Two guards keep the FPs out:
#   (a) the candidate must introduce NO new product token the feed lacks
#       -> "RYSE Loaded Creatine" never matches "Ryse Loaded Pre" ('pre' is a new token);
#   (b) grams(target)/servings(cand) must sit in a realistic 2g..25g per-serving band.
SIZE_TOK = re.compile(r'\d+(?:\.\d+)?\s*(?:kg|g|ml|l|oz|lbs?|servings?|serv\b|'
                      r'tabs?|tablets?|caps?|capsules?|gummies?|chews?|sachets?|sticks?|bars?)', re.I)

def meaningful_tokens(s):
    """Lowercase alnum tokens of a title that carry product identity:
    length >= 3, not numeric, not a flavour, not a generic filler/size word.
    Active-compound words (creatine, glycine, ...) are always kept — they distinguish
    'Loaded Creatine' from 'Loaded Pre'. Free-gift/offer phrasing is stripped first so a
    'FREE Shaker' mention adds no token."""
    out = []
    for t in re.findall(r'[a-z0-9]+', strip_gifts(s)):
        if len(t) < 3 or re.search(r'\d', t): continue
        if t in COMPOUND: out.append(t); continue
        if t in GENERIC_TOK or t in FLAVOUR: continue
        out.append(t)
    return out

# active ingredients / compound identity — never treated as filler
COMPOUND = {"creatine", "creapure", "crea", "monohydrate", "hcl", "glycine", "glutamine",
            "taurine", "carnitine", "citrulline", "arginine", "tyrosine", "betaine", "hmb",
            "alanin", "alanine", "collagen"}

def line_similar(target, cand, brand=""):
    """True when the two titles share their LEADING product-line phrase.
    Steps: drop brand words, then require
      (i) any active-compound word in the feed also appears in the candidate
          -> 'Loaded Creatine' never matches 'Loaded Pre';
      (ii) the candidate tokens are a subset of the target tokens (no new product word);
      (iii) the first <=3 meaningful tokens agree."""
    bt = set(re.findall(r'[a-z0-9]+', (brand or "").lower()))
    fa = [t for t in meaningful_tokens(target) if t not in bt]
    fb = [t for t in meaningful_tokens(cand) if t not in bt]
    if not fa or not fb: return False
    tcomp = set(fa) & COMPOUND
    if tcomp and not (tcomp & set(fb)): return False     # guard (i): compound must be shared
    if not set(fb).issubset(set(fa)): return False       # guard (ii): candidate adds nothing new
    n = min(3, len(fa), len(fb))
    return n >= 1 and fa[:n] == fb[:n]

def compound_ok(feed, cand):
    """False only when the candidate names an active compound the feed does NOT
    (i.e. a genuinely different product slipped through the other gates)."""
    cf = {t for t in meaningful_tokens(feed) if t in COMPOUND}
    cc = {t for t in meaningful_tokens(cand) if t in COMPOUND}
    return not (cc - cf)

def density_ok(target, cand):
    """Sanity-check grams(target)/servings(cand) lies in a realistic per-serving band (~2g..25g).
    Returns True (no block) unless BOTH sides carry the relevant quantity and the ratio is absurd."""
    tw = None
    for tok in size_tokens(target):
        g = to_grams(tok)
        if g and re.search(r'(?:kg|g|ml|l|\boz\b|\blbs?\b)', tok, re.I):
            tw = g; break
    cs = servings(cand)
    if tw is None or cs is None or cs <= 0: return True     # nothing to check -> don't block
    per = tw / cs
    return 2.0 <= per <= 25.0

CAMEL = {"ActiveSportsNutrition":"ActiveSportsNutrition","HollandAndBarrett":"HollandAndBarrett",
         "DolphinFitness":"DolphinFitness","IHerbUk":"IHerbUk","CellucorUk":"CellucorUk",
         "AppliedNutrition":"AppliedNutrition","ReflexNutrition":"ReflexNutrition",
         "10xAthletic":"10xAthletic","AnimalPak":"AnimalPak"}

def load_catalog():
    """Merge both catalog files and drop only TRUE exact duplicates.
    BUG1 fix: the old key was (source, url) — but a single URL legitimately carries many
    flavour variants (e.g. 15 ABE flavours share .../abe-all-black-everything-375g), so it
    silently discarded 2.5k valid candidates. Dedup on the FULL identity
    (source, url, name, price) instead: only byte-identical rows are removed."""
    seen, cat = set(), []
    for p in CATS:
        if not p.exists():
            log(f"WARN catalog missing: {p}")
            continue
        for c in json.loads(p.read_text()):
            k = (c.get("source"), c.get("url"), clean_name(c.get("name")), c.get("price"))
            if k in seen: continue
            seen.add(k)
            c["name"] = clean_name(c.get("name"))
            c["usd"] = round(float(c["price"])*FX_GBP_USD, 2) if c.get("price") not in (None, "") else None
            cat.append(c)
    return cat

def pop_key(name):
    """Identity key used to measure how WIDELY a product is stocked (most-common tie-break)."""
    return " ".join(norm(name).split()[:6])

_FLAVISH = set("""berry berries mixed fruit fruits punch blast ice icy blue red green cherry
apple grape mango orange peach lemon lime cola candy sweet sweets sour tropical strawberry
raspberry watermelon pineapple caramel cookie cookies cream brownie vanilla chocolate mint
cappuccino mocha banana salted caramel popcorn sherbet fizz bubblegum rainbow unflavoured
unflavored flavour flavor flavoured flavored original""".split())

def size_dup_ok(feed, cand, brand=""):
    """Same brand + EXACT size already established by the caller (st=="ok"). Accept when a
    shared distinctive NON-compound token exists (plural-normalised) - e.g. 'Cyclone'
    (MaxiNutrition Cyclone 1.26kg) or 'vitamin(s)'. Compound words excluded so a
    creatine-vs-creatine size coincidence can never satisfy this on its own."""
    bt = set(re.findall(r"[a-z0-9]+", (brand or "").lower()))
    def toks(s):
        return {t[:-1] if len(t) > 3 and t.endswith("s") else t
                for t in re.findall(r"[a-z0-9]+", (s or "").lower())
                if len(t) >= 4 and not re.search(r"\d", t) and t not in GENERIC_TOK
                and t not in bt and t not in COMPOUND and t not in FLAVOUR
                and t not in _FLAVISH}
    return bool(toks(feed) & toks(cand))

def candidate_picks(name, brand, target, cat):
    """All acceptable (score, why, catalog_entry) picks for one feed product.
    Extracted from main() so the regression harness and diffreport exercise the SAME gates."""
    picks = []
    sub = [c for c in cat
           if brand_ok(brand, c["name"], c["source"])
           and forms_ok(name, c["name"])
           and category_ok(name, c["name"])
           and distinctiveness_ok(name, brand, c["name"])]
    cand = []
    for c in sub:
        if size_status(target, c["name"]) != "conflict" or servings_compatible(target, c["name"]):
            j = jaccard(name, c["name"])
            # BUG5: a brand-tokenisation mismatch ("MaxiNutrition" vs "Maxi Nutrition") drops
            # jaccard below the 0.20 pre-filter even though brand+forms+category+distinctiveness
            # ALL pass and the size is EXACTLY equal. Admit such an exact-size pair when it also
            # shares a distinctive non-compound token; every downstream gate still applies.
            if j >= 0.20 or (size_status(target, c["name"]) == "ok"
                             and size_dup_ok(name, c["name"], brand)):
                cand.append((j, c))
    cand.sort(key=lambda x: -x[0])
    cand = cand[:6]
    for j, c in cand:
        st = size_status(target, c["name"])
        if st == "conflict" and servings_compatible(target, c["name"]):
            st = "servings-equiv"          # grams<->servings expression, same product
        s = min(1.0, j + 0.15) if st == "ok" else j
        thr = 0.42 if distinct_weak(name, brand, c["name"]) else 0.34
        if st == "ok" and (s >= thr or (size_dup_ok(name, c["name"], brand) and density_ok(target, c["name"]))):
            picks.append((s, "fuzzy+size", c))
        elif st == "near" and j >= 0.50:
            # BUG3: tiny size delta (e.g. 1.8kg vs 1.89kg) is the SAME product, but
            # demand a stricter title overlap so a different SKU cannot slip in.
            picks.append((min(1.0, j + 0.15), "fuzzy+size-near", c))
        elif st == "servings-equiv" and (
                j >= 0.55                                     # legacy strong title overlap
                or (line_similar(target, c["name"], brand)    # BUG4 product-line prefix
                    and density_ok(target, c["name"]))        # BUG4 realistic g/serving
                or (j >= 0.45 and density_ok(target, c["name"])
                    and compound_ok(target, c["name"]))):     # generic titles (no distinctive token)
            picks.append((j, "fuzzy+servings", c))
        elif st in ("one-none", "both-none") and s >= 0.50:
            picks.append((s, "fuzzy", c))
    # FAIL-CLOSED on ambiguous pack size: when the accepted servings-equivalent candidates
    # point to MORE THAN ONE pack size (e.g. 15/30/60 Servings for a 255g feed row with no
    # serving info), we cannot tell which pack the feed row is -> never guess the cheapest.
    if len({servings(c["name"]) for (_, why, c) in picks if why == "fuzzy+servings"}) > 1:
        picks = [p for p in picks if p[1] != "fuzzy+servings"]
    return picks

def feed_servings(r):
    """Implied servings count from the feed's OWN nutrition label:
       weight / declared serving size.  e.g. '396g' + 'Serving Size: 6.6g' -> 60.
    Returns None when the label is absent/garbled -> caller must NOT guess."""
    nut = r.get("NutritionalInformation") or ""
    m = NUTR_SS.search(nut)
    g = to_grams(r.get("TranslationName") or "")
    if not (m and g):
        return None
    ss = float(m.group(1))
    if m.group(2) == "mg":
        ss /= 1000.0
    if ss <= 0:
        return None
    return g / ss

def servings_confirmed_picks(r, cat):
    """Fail-closed resolver for the ONE case arithmetic can prove: the feed row itself
    declares a serving size, so implied_servings = weight / serving_size. A catalog entry
    of the SAME brand + SAME product line (jaccard>=0.40) whose EXPLICIT servings count
    equals implied_servings IS the same pack -> safe match (servings CONFIRMS the line,
    never replaces it: forbids C4-Original -> C4-Sport)."""
    implied = feed_servings(r)
    if not implied:
        return []
    name = r.get("TranslationName") or ""
    brand = r.get("Brand") or ""
    target = (name + " " + (r.get("Size") or "")).strip()
    out = []
    for c in cat:
        if ACCESSORY.search(c["name"]):
            continue
        cs = servings(c["name"])
        if not cs or abs(cs - implied) / implied > 0.05:
            continue
        if not brand_ok(brand, c["name"], c["source"]):
            continue
        if not (forms_ok(name, c["name"]) and category_ok(name, c["name"])
                and compound_ok(name, c["name"])):
            continue
        j = jaccard(target, c["name"])
        if j >= 0.40:
            out.append((max(j, 0.60), "fuzzy+servings-confirmed", c))
    if len({servings(c["name"]) for _, _, c in out}) > 1:   # never guess pack size
        return []
    return out

def resolve_row(r, cat, by_bc, pop):
    """Match a single feed row -> result dict. Barcode-exact wins; else gate the catalog."""
    name = r.get("TranslationName") or ""
    brand = r.get("Brand") or ""
    size = r.get("Size") or ""
    target = (name + " " + size).strip()
    bc = re.sub(r'\D', '', (r.get("Barcodes") or r.get("Barcode") or ""))
    picks = []
    if bc and bc in by_bc:
        for c in by_bc[bc]:
            picks.append((1.0, "barcode-exact", c))
    if not picks:
        picks = candidate_picks(name, brand, target, cat)
    if not picks:
        # servings-confirmed fallback: feed declares a serving size -> implied servings
        # must equal a same-line catalog entry's explicit servings count.
        picks = servings_confirmed_picks(r, cat)
    if not picks:
        return {"row": r, "comp": "", "price": "", "src": "", "score": 0.0,
                "why": "no-match", "prod": "", "url": "", "n": 0, "gbp": ""}
    top = max(p[0] for p in picks)
    grp = [(s, why, c) for s, why, c in picks if s >= top - 0.12]
    cheap = min(c["usd"] for _, _, c in grp)
    tied = [(s, why, c) for s, why, c in grp if abs(c["usd"] - cheap) < 0.01]
    # tie-break: cheapest USD; on equal price -> the MOST COMMON product (widest stock)
    s, why, c = max(tied, key=lambda x: (pop[pop_key(x[2]["name"])], x[0], x[2]["name"]))
    return {"row": r, "comp": CAMEL.get(c["source"], c["source"]),
            "price": f"{c['usd']:.2f}", "src": c["source"], "score": s, "why": why,
            "prod": c["name"], "url": c["url"], "n": len(picks), "gbp": c["price"]}

def main():
    cat = load_catalog()
    log(f"CATALOG merged {len(cat)}  by source {dict(Counter(c['source'] for c in cat))}")
    pop = Counter(pop_key(c["name"]) for c in cat)
    by_bc = defaultdict(list)
    for c in cat:
        b = re.sub(r'\D', '', c.get("barcode") or "")
        if b: by_bc[b].append(c)
    rows = list(csv.DictReader(open(FEED, encoding="utf-8-sig")))
    hdr = list(rows[0].keys())
    log(f"feed rows {len(rows)} cols {len(hdr)}")

    results = [resolve_row(r, cat, by_bc, pop) for r in rows]

    src_cnt = Counter(x["src"] for x in results if x["src"])
    hit = sum(1 for x in results if x["comp"])
    log(f"\nHIT {hit}/{len(results)} ({100*hit/len(results):.1f}%)  [USD]")
    log(f"by competitor {dict(src_cnt)}")
    log(f"by resolution {dict(Counter(x['why'] for x in results))}")

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=hdr + ["competitor", "competitorPrice"])
        w.writeheader()
        for x in results:
            rr = dict(x["row"]); rr["competitor"] = x["comp"]; rr["competitorPrice"] = x["price"]
            w.writerow({k: rr.get(k, "") for k in hdr + ["competitor", "competitorPrice"]})
    with open(DBG, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["ProductCode","TranslationName","Size","Brand","Barcode",
                                          "competitor","competitorPriceUSD","competitorPriceGBP","matchScore",
                                          "resolution","candidates","competitorProduct","competitorURL"])
        w.writeheader()
        for x in results:
            r = x["row"]
            w.writerow({"ProductCode": r.get("ProductCode"), "TranslationName": r.get("TranslationName"),
                        "Size": r.get("Size"), "Brand": r.get("Brand"),
                        "Barcode": r.get("Barcodes") or r.get("Barcode"),
                        "competitor": x["comp"], "competitorPriceUSD": x["price"],
                        "competitorPriceGBP": x["gbp"], "matchScore": f"{x['score']:.2f}",
                        "resolution": x["why"], "candidates": x["n"],
                        "competitorProduct": x["prod"], "competitorURL": x["url"]})
    # unmatched report: every row with no competitor (ProductCode+TranslationName+Size+Brand)
    with open(UMP, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["ProductCode", "TranslationName", "Size", "Brand"])
        w.writeheader()
        for x in results:
            if not x["comp"]:
                r = x["row"]
                w.writerow({"ProductCode": r.get("ProductCode"), "TranslationName": r.get("TranslationName"),
                            "Size": r.get("Size"), "Brand": r.get("Brand")})
    log(f"WROTE {OUT}\nWROTE {DBG}\nWROTE {UMP}")

if __name__ == "__main__":
    main()
