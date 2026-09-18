#!/usr/bin/env python3
"""
poster_template.py -- job card poster, modelled on @prosple.au
===============================================================
Builds a 1080x1080 Instagram post for ONE job: a white rounded "job card"
floating over a dimmed background, in the same structure Prosple uses --
logo + company, big bold title, a closing-date pill, location, pay,
labelled detail rows, and an "Apply on employer site" button.

WHAT'S REAL AND WHAT ISN'T
--------------------------
Every value on the card comes from the actual scraped listing. Nothing is
invented. Where a listing doesn't have a piece of information, that ROW IS
LEFT OFF the card entirely rather than filled with a guess -- so a job with
no stated salary simply has no pay line, and a job with no stated closing
date gets no urgency pill. The layout recalculates its height to suit.

The one exception is the "FIELD" row, which shows OUR OWN category for the
job (from all_jobs.py's 7 categories). It's deliberately labelled FIELD
rather than Prosple's "HIRING STUDENTS FROM", because the employer never
said it -- we worked it out.

BACKGROUNDS: drop any .jpg/.png photos into the backgrounds/ folder next to
this script and one gets picked per job (the same job always gets the same
one) and dimmed behind the card, like Prosple's lifestyle photos. With no
photos in there, a soft gradient is used instead.

LOGOS: drop a transparent PNG named after the company into logos/
(e.g. "ing.png" for ING) and it appears top-left of the card. Without one,
the company name alone is shown -- never a placeholder box.
"""

import glob
import json
import os
import re
from html.parser import HTMLParser

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------------------------------
# Canvas + palette (one navy accent throughout, like their cards)
# --------------------------------------------------------------------------
W = H = 1080

# One colour per category, so a post is recognisable before you have read a
# word of it. They are deliberately a family rather than four unrelated hues:
# every one sits at roughly the same darkness and muted saturation, so the
# feed looks designed instead of like a paint chart. Berry is the brand
# anchor and goes to Finance, which posts most often.
BERRY = (142, 47, 82)
BERRY_DEEP = (66, 20, 38)

PALETTES = {
    "Business, Commerce, Marketing & Finance":
        ((142, 47, 82), (66, 20, 38)),          # berry -- the brand colour

    "Technology, Data & AI":
        ((29, 92, 97), (12, 44, 48)),           # deep teal
    "Engineering":
        ((154, 74, 44), (72, 32, 18)),          # rust
}


# The photo is dimmed towards a neutral charcoal, NOT towards the category
# colour -- tinting the whole frame made every post look like a colour filter
# had been dropped on it. The category colour lives in the text and the
# button, where it reads as a design choice instead of a cast. TINT_STRENGTH
# is the last whisper of hue left in the photo; raise it if you ever want the
# older look back, but keep it low.
NEUTRAL_DIM = (26, 28, 32)
TINT_STRENGTH = 0.07


def palette_for(category):
    """(ink, deep) for a category. Ink is the text and button colour, deep is
    what the background photo is tinted towards. Anything unrecognised falls
    back to berry, so a new category still looks on-brand."""
    return PALETTES.get((category or "").strip(), (BERRY, BERRY_DEEP))


# Kept so the older single-poster script still runs unchanged.
NAVY = BERRY
NAVY_DEEP = BERRY_DEEP
CARD = (255, 255, 255)
GREY = (110, 122, 138)
GREY_LABEL = (140, 150, 163)
URGENT_BG = (253, 226, 226)
URGENT_FG = (200, 48, 48)
CALM_BG = (226, 236, 253)
CALM_FG = (37, 84, 168)
BG_TOP = (58, 74, 104)
BG_BOTTOM = (30, 42, 66)

CARD_MARGIN = 84
CARD_PAD = 56
CARD_RADIUS = 40

HERE = os.path.dirname(os.path.abspath(__file__))
LOGOS_DIR = os.path.join(HERE, "logos")
# "background pics" is the folder get_backgrounds.py fills. The older
# "backgrounds" name is still checked so anything already dropped in there
# keeps working.
BACKGROUND_DIRS = [os.path.join(HERE, "background pics"),
                   os.path.join(HERE, "backgrounds")]


def _find_font_dir():
    """DejaVu Sans, wherever it lives on this machine (see the note in the
    old version -- macOS has no /usr/share/fonts, so matplotlib's bundled
    copy is used instead)."""
    try:
        import matplotlib
        mpl_fonts = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        if os.path.exists(os.path.join(mpl_fonts, "DejaVuSans.ttf")):
            return mpl_fonts + os.sep
    except ImportError:
        pass
    linux_path = "/usr/share/fonts/truetype/dejavu/"
    if os.path.exists(os.path.join(linux_path, "DejaVuSans.ttf")):
        return linux_path
    raise SystemExit(
        "Couldn't find DejaVu Sans.\nFix: pip3 install --user matplotlib"
    )


FD = _find_font_dir()
def _font(name, size):
    return ImageFont.truetype(FD + name, size)


F_COMPANY = _font("DejaVuSans.ttf", 30)
F_TITLE = _font("DejaVuSans-Bold.ttf", 55)
F_PILL = _font("DejaVuSans-Bold.ttf", 26)
F_BODY = _font("DejaVuSans.ttf", 31)
F_PAY = _font("DejaVuSans-Bold.ttf", 44)
F_PAY_UNIT = _font("DejaVuSans.ttf", 30)
F_LABEL = _font("DejaVuSans-Bold.ttf", 21)
F_VALUE = _font("DejaVuSans.ttf", 32)
F_BUTTON = _font("DejaVuSans-Bold.ttf", 32)


# --------------------------------------------------------------------------
# Pulling real facts out of the listing
# --------------------------------------------------------------------------
class _ListItemExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items, self._in_li, self._buf = [], False, []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._in_li, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "li" and self._in_li:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.items.append(text)
            self._in_li = False

    def handle_data(self, data):
        if self._in_li:
            self._buf.append(data)


# --------------------------------------------------------------------------
# Dates. Seek gives us NO start-date or closing-date field at all -- the only
# place those exist is inside the free-text description, written however the
# employer felt like writing it. These patterns cover the real phrasings seen
# in actual listings, e.g.:
#     "Applications will close Tuesday, the 8th of September."
#     "Our programme is scheduled to commence in late October 2026."
#     "applications close 30 September 2026"
# If nothing matches, the row is simply left off the card. Never guessed.
# --------------------------------------------------------------------------
_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec")

# A date-ish phrase: "8th of September", "30 September 2026", "late October
# 2026", "Feb 2026", "1/10/2026"
_DATE = (
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|(?:early|mid|late)\s+(?:" + _MONTHS + r")(?:\s+\d{4})?"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:" + _MONTHS + r")(?:\s+\d{4})?"
    r"|(?:" + _MONTHS + r")\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?"
    r"|(?:" + _MONTHS + r")\s+\d{4})"
)

# optional "Tuesday," / "on" / "the" noise between the cue word and the date
_GAP = r"(?:\s+(?:on|by|from|in|is|of|the|at)\b|\s*:|\s*,|\s+\w+day,?)*\s*"

CLOSING_PATTERNS = [
    r"applications?\s+(?:will\s+|shall\s+)?clos\w*" + _GAP + r"(" + _DATE + r")",
    r"closing\s+date" + _GAP + r"(" + _DATE + r")",
    r"applications?\s+due" + _GAP + r"(" + _DATE + r")",
    r"apply\s+by" + _GAP + r"(" + _DATE + r")",
    r"deadline" + _GAP + r"(" + _DATE + r")",
]

START_PATTERNS = [
    r"(?:scheduled\s+to\s+)?commenc\w*" + _GAP + r"(" + _DATE + r")",
    r"start\s+date" + _GAP + r"(" + _DATE + r")",
    r"(?:programme?|program|internship|role|position)\s+(?:will\s+)?(?:start|begin)\w*" + _GAP + r"(" + _DATE + r")",
    r"start\w*" + _GAP + r"(" + _DATE + r")",
    r"(" + _DATE + r")\s+(?:start|intake|commencement)",
]


def _search(patterns, text):
    if not text:
        return None
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            found = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
            # Tidy "8th of September" -> "8 September" so it fits the card
            found = re.sub(r"(\d{1,2})(?:st|nd|rd|th)\s+of\s+", r"\1 ", found)
            return found[:1].upper() + found[1:]
    return None


def find_closing_date(description_text):
    """Return a stated application closing date, or None. Never guesses."""
    return _search(CLOSING_PATTERNS, description_text)


def find_start_date(description_text):
    """Return a stated start/commencement date, or None. Never guesses."""
    return _search(START_PATTERNS, description_text)


def clean_pay(pay_range):
    """Seek's salaryLabel is free text. Keep it only if it actually looks
    like a pay figure -- '$190k - $200k p.a.' yes, 'Competitive' no, since
    a card row reading 'Competitive' next to a $ heading is just noise.

    Seek also tacks extras onto the end ('$190k - $200k p.a. + Super & 10%
    performance bonus'), which is far too long for one big headline line.
    Everything from the first ' + ' onward is dropped so the figure itself
    stays the focus -- the full text is still in the caption."""
    if not pay_range:
        return None
    text = str(pay_range).strip()
    if not re.search(r"\d", text):
        return None
    text = re.split(r"\s+\+\s+", text)[0].strip()
    return text


def _fit_font(draw, text, max_w, sizes=(44, 39, 34, 30)):
    """Pick the largest of these font sizes that actually fits the width,
    so a long salary string shrinks instead of running off the card."""
    for size in sizes:
        fnt = _font("DejaVuSans-Bold.ttf", size)
        if draw.textlength(text, font=fnt) <= max_w:
            return fnt
    return _font("DejaVuSans-Bold.ttf", sizes[-1])


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
def _wrap(draw, text, fnt, max_w, max_lines=None):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "...", font=fnt) > max_w:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "..."
    return lines



# ---------------------------------------------------------------------------
# Well-known employers whose logo Seek did not supply
# ---------------------------------------------------------------------------
# Only about half of Seek's listings carry a logo -- the advertiser has to pay
# for branding. Apple, SAP and CommBank often turn up without one, and an "AP"
# tile next to an Apple internship looks like the pipeline failed rather than
# like a design choice.
#
# We do NOT solve that by guessing a domain from a company name. "Holden
# Bolster Avenir Pty Ltd" could be anything, and one wrong logo on a job post
# costs the account its credibility. Instead brand_domains.json is a
# hand-checked list: a name goes in it only when there is exactly one company
# it could possibly mean. Everything else keeps its initials tile, which is
# honest.
#
# The slide only needs 58 pixels of logo, so a 128px favicon is more than
# enough resolution -- which is why this works at all.
BRANDS_FILE = os.path.join(HERE, "brand_domains.json")
FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
_BRANDS = None
_BRAND_KEYS = None

# Words that are not part of anybody's name. Employers write themselves down a
# dozen different ways -- "Commonwealth Bank of Australia", "CommBank Group",
# "2026/27 CommBank Summer Intern Program" -- and an exact-match list only ever
# catches whichever spelling happened to be typed into the JSON. Stripping this
# noise first is what lets one entry cover all of them.
_NOISE = {
    # legal and structural
    "pty", "ltd", "ltd.", "limited", "inc", "inc.", "llc", "plc", "co", "co.",
    "corp", "corp.", "corporation", "company", "group", "holdings", "the",
    # geography that is never the distinguishing part of the name
    "australia", "australian", "aus", "au", "nz", "anzac", "asia", "pacific",
    "apac", "global", "international", "worldwide", "sydney", "nsw",
    # words that come from the ad, not from the employer
    "summer", "winter", "intern", "interns", "internship", "internships",
    "graduate", "graduates", "grad", "program", "programme", "cadetship",
    "vacation", "undergraduate", "student", "students", "campus", "careers",
    "recruitment", "talent", "hiring", "and", "&",
    # generic business words: stripping these is what lets "Amazon Web
    # Services" and "KPMG Consulting" land on the right brand
    "services", "service", "consulting", "advisory", "solutions", "web",
}


def _norm_tokens(name):
    """Lower-case word tokens with punctuation, years and noise words removed."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (name or "").casefold())
    out = []
    for t in cleaned.split():
        if t in _NOISE:
            continue
        if t.isdigit() or re.fullmatch(r"\d[\d/]*", t):   # 2026, 2026/27
            continue
        out.append(t)
    return out


def _load_brands():
    global _BRANDS, _BRAND_KEYS
    if _BRANDS is not None:
        return
    try:
        with open(BRANDS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    _BRANDS = {k.strip().casefold(): v for k, v in raw.items()
               if not k.startswith("_") and v}
    # Longest names first, so "Commonwealth Bank of Australia" is considered
    # before the bare "Commonwealth Bank" and both before "CBA".
    _BRAND_KEYS = sorted(
        ((tuple(_norm_tokens(k)), v) for k, v in raw.items()
         if not k.startswith("_") and v and _norm_tokens(k)),
        key=lambda kv: -len(kv[0]))


def brand_domain(name):
    """The verified domain for this employer, or "" if we cannot be sure.

    Exact match first. Failing that, the brand's words have to appear inside
    the employer's words in order -- and after the noise above is stripped,
    at most one word of the employer may be left over. That last rule is the
    whole safety net: "Commonwealth Bank of Australia" leaves only "of" and
    matches, while "Apple Valley Childcare" leaves "valley" and "childcare"
    and keeps its initials tile. A wrong logo is far more expensive than a
    missing one, so anything even slightly ambiguous gets nothing.
    """
    _load_brands()
    exact = _BRANDS.get((name or "").strip().casefold(), "")
    if exact:
        return exact

    words = _norm_tokens(name)
    if not words:
        return ""

    best, best_len = [], 0
    for key, domain in _BRAND_KEYS:
        n = len(key)
        # A one-word brand has to be the whole employer name once the noise is
        # gone. Allowing it a leftover word matched "Vitaco Health" to NSW
        # Health, which is exactly the kind of wrong logo this list exists to
        # avoid. Multi-word brands are specific enough to survive one leftover,
        # which is what carries "Commonwealth Bank of Australia".
        if n > len(words) or len(words) - n > 1:
            continue
        at = [i for i in range(len(words) - n + 1) if words[i:i + n] == list(key)]
        if not at:
            continue
        # A one-word brand with a leftover word has to LEAD the name. "ANZ
        # Banking" is ANZ; "Vitaco Health" is not NSW Health. Brands lead the
        # names they appear in -- descriptors follow them.
        if n == 1 and len(words) > n and at[0] != 0:
            continue
        if True:
            if n > best_len:
                best, best_len = [domain], n
            elif n == best_len:
                best.append(domain)

    # Two different brands matching equally well means we do not actually
    # know which one it is. Say nothing rather than guess.
    if len(set(best)) == 1:
        return best[0]
    return ""


def _logo_for(business_name, logo_url=None):
    """
    Find this company's logo.

    Seek hands us the advertiser's real logo URL in the listing data, so the
    first time we see a company we download it and keep it. After that it's
    cached on disk and never fetched again.

    That replaces the old approach entirely -- which was "hope someone put
    a PNG in logos/ named after the company". There's no reliable free way
    to map an arbitrary company name to its logo, but we don't have to:
    Seek already knows, and tells us.

    A manually added file still wins, so you can override a bad logo by
    dropping a better one in logos/.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (business_name or "").lower()).strip("_")
    if not slug:
        return None

    manual = os.path.join(LOGOS_DIR, f"{slug}.png")
    if os.path.exists(manual):
        return manual

    # A name on the verified list beats whatever the job board sent. Seek's
    # image is whatever the advertiser uploaded -- often a campaign banner, a
    # stock photo, or nothing -- so if we know for certain this employer is
    # Commonwealth Bank, the slide gets the real Commonwealth Bank mark.
    #
    # The two caches are kept in separate files on purpose. Writing the brand
    # mark into the "_seek" name means the brand cache never exists and every
    # run refetches it -- and a stale "_seek" marker, the zero-byte kind that
    # records "this advertiser has no logo", would block the brand mark
    # forever.
    brand_cached = os.path.join(LOGOS_DIR, f"{slug}_brand.png")
    cached = os.path.join(LOGOS_DIR, f"{slug}_seek.png")
    domain = brand_domain(business_name)

    if domain:
        if os.path.exists(brand_cached) and os.path.getsize(brand_cached) > 0:
            return brand_cached
        os.makedirs(LOGOS_DIR, exist_ok=True)
        try:
            import requests
            from io import BytesIO
            r = requests.get(FAVICON.format(domain=domain), timeout=20)
            if r.status_code == 200 and len(r.content) >= 200:
                Image.open(BytesIO(r.content)).convert("RGBA").save(brand_cached, "PNG")
                print(f"      brand logo: {business_name} <- {domain}")
                return brand_cached
            print(f"      no brand logo for {business_name} ({domain})")
        except Exception as e:
            print(f"      couldn't fetch brand logo for {business_name} "
                  f"({type(e).__name__}) -- will retry next run")
        # Fall through rather than return: an unreachable favicon is no reason
        # to throw away the advertiser's own logo if we already have it.

    if os.path.exists(cached):
        return cached if os.path.getsize(cached) > 0 else None
    if not logo_url:
        return None

    os.makedirs(LOGOS_DIR, exist_ok=True)
    try:
        import requests
        r = requests.get(logo_url, timeout=20)
        if r.status_code != 200:
            # A 404 means this advertiser genuinely has no logo -- remember
            # that. Anything else might just be Seek having a moment.
            if r.status_code == 404:
                open(cached, "wb").close()
            print(f"      no logo for {business_name} (HTTP {r.status_code})")
            return None
        from io import BytesIO
        img = Image.open(BytesIO(r.content)).convert("RGBA")
        img.save(cached, "PNG")
        print(f"      fetched logo: {business_name}")
        return cached
    except Exception as e:
        # Deliberately NO marker file here. Network errors, timeouts and
        # proxy failures are about the machine, not the company -- writing
        # a "never retry" marker for those would blacklist a company
        # permanently because of one bad minute of wifi.
        print(f"      couldn't fetch logo for {business_name} "
              f"({type(e).__name__}) -- will retry next run")
        return None


def _background(job_id, deep=NAVY_DEEP):
    """A dimmed photo from backgrounds/ if any exist, else a gradient.
    Same job always gets the same photo so re-runs look identical."""
    photos = []
    for folder in BACKGROUND_DIRS:
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
            photos.extend(glob.glob(os.path.join(folder, ext)))
    photos = sorted(set(photos))
    if photos:
        pick = photos[sum(ord(c) for c in str(job_id)) % len(photos)]
        try:
            photo = Image.open(pick).convert("RGB")
            # cover-crop to a square, then dim so white text/card pops
            scale = max(W / photo.width, H / photo.height)
            photo = photo.resize((round(photo.width * scale), round(photo.height * scale)))
            left, top = (photo.width - W) // 2, (photo.height - H) // 2
            photo = photo.crop((left, top, left + W, top + H))
            photo = photo.filter(ImageFilter.GaussianBlur(2))
            photo = Image.blend(photo, Image.new("RGB", (W, H), NEUTRAL_DIM), 0.45)
            return Image.blend(photo, Image.new("RGB", (W, H), deep),
                               TINT_STRENGTH)
        except Exception:
            pass

    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for row in range(H):
        t = row / (H - 1)
        d.line([(0, row), (W, row)], fill=tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        ))
    return img


def _pin_icon(draw, x, y, colour, size=22):
    """Small map-pin, drawn by hand (DejaVu has no emoji)."""
    r = size // 2
    draw.ellipse([x, y, x + size, y + size], outline=colour, width=3)
    draw.ellipse([x + r - 3, y + r - 3, x + r + 3, y + r + 3], fill=colour)
    draw.polygon([(x + r - 5, y + size - 3), (x + r + 5, y + size - 3),
                  (x + r, y + size + 7)], fill=colour)


def _clock_icon(draw, x, y, colour, size=20):
    draw.ellipse([x, y, x + size, y + size], outline=colour, width=3)
    cx, cy = x + size / 2, y + size / 2
    draw.line([(cx, cy), (cx, cy - size * 0.28)], fill=colour, width=3)
    draw.line([(cx, cy), (cx + size * 0.24, cy)], fill=colour, width=3)


# --------------------------------------------------------------------------
# The card
# --------------------------------------------------------------------------

def _save(img, path):
    """
    Save as JPEG when the filename says so.

    Instagram REJECTS PNG for feed posts -- JPEG only. Everything here used
    to save .png, which meant every publish call would have failed. Quality
    92 is visually indistinguishable from lossless on flat colour and type,
    and keeps files small enough to upload quickly.
    """
    if path.lower().endswith((".jpg", ".jpeg")):
        img.convert("RGB").save(path, "JPEG", quality=92, optimize=True,
                                subsampling=0)
    else:
        img.save(path)




def _initials(name):
    """
    Up to two letters for a company with no logo.

    Two kinds of noise have to go first. Legal suffixes, so "Holden Bolster
    Avenir Pty Ltd" gives HB rather than HP. And programme wording, because
    when Seek's advertiser is an agency the only company name we have is
    inside the ad's own title -- "2026/27 CommBank Summer Intern Program" was
    coming out as "22", the first two characters of the year.
    """
    noise = {
        # legal / corporate
        "pty", "ltd", "limited", "inc", "group", "australia", "the", "co",
        "corp", "company", "holdings", "services", "and",
        # programme wording
        "summer", "winter", "intern", "interns", "internship", "program",
        "programme", "graduate", "vacation", "cadetship", "cadet", "student",
        "undergraduate", "placement", "academy", "experience",
    }
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]
    # A bare number is never an initial -- it is a year or an intake.
    words = [w for w in words if not w.isdigit()]
    meaningful = [w for w in words if w.lower() not in noise] or words
    if not meaningful:
        return "?"
    if len(meaningful) == 1:
        w = meaningful[0]
        # CommBank -> CB, Bankwest -> BA. An internal capital is the company's
        # own way of showing where the second word starts.
        for i, ch in enumerate(w[1:], start=1):
            if ch.isupper():
                return (w[0] + ch).upper()
        return w[:2].upper()
    return (meaningful[0][0] + meaningful[1][0]).upper()


def _draw_initials_badge(img, draw, x, y, size, name, ink):
    """
    A rounded tile with the company's initials, used when Seek has no logo.

    Only advertisers who pay for branding get a logo in Seek's data -- about
    half of any given batch -- so on the rest the card used to open with a
    line of grey text and a lot of empty space. We will not source a logo
    elsewhere by guessing a company's domain from its name: put the wrong
    logo on a post once and the account stops being trustworthy. A tile in
    the category's own colour is honest about having no logo while still
    looking deliberate.
    """
    draw.rounded_rectangle([x, y, x + size, y + size], radius=14, fill=ink)
    text = _initials(name)
    f = _font("DejaVuSans-Bold.ttf", 30 if len(text) > 1 else 34)
    tw = draw.textlength(text, font=f)
    bbox = f.getbbox(text)
    draw.text((x + (size - tw) / 2, y + (size - (bbox[3] - bbox[1])) / 2 - bbox[1]),
              text, font=f, fill=(255, 255, 255))


def split_programme_title(title, business):
    """
    Return (headline, programme_line).

    Big employers post one ad per stream under a single long programme name:

        2026/27 CommBank Summer Intern Program: Product Management - Accounting
        2026/27 CommBank Summer Intern Program: Product Management - Economics

    Rendered whole, those wrap past the card and both truncate to
    "...Product Management -", so four genuinely different roles look like the
    same slide repeated. Splitting on the colon puts the part that differs in
    the headline and the shared programme name on the small line above, which
    is also where the employer name goes when we have one -- and for these ads
    we do not, because they are posted by SEEK Grad rather than the employer.

    Nothing is invented here: both halves are the advertiser's own words.
    """
    title = (title or "").strip()
    if ":" in title:
        before, after = title.split(":", 1)
        before, after = before.strip(), after.strip()
        # Only worth splitting when the prefix is a real programme name and
        # what follows can stand on its own as a role.
        if len(before) >= 18 and len(after) >= 6:
            return after, (business or before)
    return title, business


def build_poster(job, out_dir, account_handle="[your account handle]",
                 category=None, filename="poster.jpg", write_caption=True,
                 bg_seed=None):
    os.makedirs(out_dir, exist_ok=True)

    title = job.get("job_title") or "Job Opportunity"
    # companyName is the actual employer; business_name is whoever owns the
    # Seek account, which is how a dozen listings ended up branded "SEEK Grad".
    # "SEEK Grad" and friends are agency accounts, not the employer --
    # see NOT_EMPLOYERS in build_carousels.py. Show the logo alone rather
    # than a company name we would have to invent.
    business = job.get("company_name") or job.get("business_name") or ""
    if business.strip().casefold() in {"seek grad", "seek", "seek limited"}:
            business = ""
    title, business = split_programme_title(title, business)
    location = job.get("suburb") or job.get("area") or job.get("region") or ""
    work_type = job.get("work_type") or ""
    pay = clean_pay(job.get("pay_range"))
    closing = find_closing_date(job.get("description_text"))
    starts = find_start_date(job.get("description_text"))
    field = category or job.get("job_type") or ""
    if field.strip().lower() == "other":
        field = "Technology & IT"

    ink, deep = palette_for(category)
    # bg_seed lets a whole carousel share one photo. Without it each job
    # picks its own, which is right for a standalone poster but makes a
    # six-slide carousel look like six unrelated posts.
    img = _background(bg_seed or job.get("job_id"), deep)
    draw = ImageDraw.Draw(img)

    inner_w = W - 2 * CARD_MARGIN - 2 * CARD_PAD
    logo_path = _logo_for(business, job.get("logo_url"))

    # ---- measure everything first so the card can be sized to its content
    title_lines = _wrap(draw, title, F_TITLE, inner_w, max_lines=3)
    blocks = []                              # (kind, height)
    blocks.append(("header", 58))
    blocks.append(("gap", 30))
    blocks.append(("title", len(title_lines) * 66))
    if closing:
        blocks += [("gap", 26), ("pill", 50)]
    if location:
        blocks += [("gap", 26), ("location", 38)]
    if pay:
        blocks += [("gap", 24), ("pay", 52)]
    if starts:
        blocks += [("gap", 26), ("startdate", 62)]
    if work_type:
        blocks += [("gap", 22), ("worktype", 62)]
    if field:
        blocks += [("gap", 22), ("field", 62)]
    blocks += [("gap", 38), ("button", 92)]

    card_h = 2 * CARD_PAD + sum(h for _, h in blocks)
    card_x0, card_x1 = CARD_MARGIN, W - CARD_MARGIN
    card_y0 = max(60, (H - card_h) // 2)
    card_y1 = card_y0 + card_h

    # soft shadow, then the card itself
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [card_x0 + 6, card_y0 + 14, card_x1 + 6, card_y1 + 14],
        radius=CARD_RADIUS, fill=(0, 0, 0, 70))
    img = Image.alpha_composite(img.convert("RGBA"),
                                shadow.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1],
                           radius=CARD_RADIUS, fill=CARD)

    x = card_x0 + CARD_PAD
    y = card_y0 + CARD_PAD

    for kind, h in blocks:
        if kind == "gap":
            y += h
            continue

        if kind == "header":
            text_x = x
            is_wordmark = False
            if logo_path:
                try:
                    logo = Image.open(logo_path).convert("RGBA")
                    # Scale to fit BOTH a target height and a max width --
                    # cropping to a fixed width chopped the end off wide
                    # wordmarks (ING came out reading "INC").
                    max_h, max_w = 58, 300
                    scale = min(max_h / logo.height, max_w / logo.width)
                    logo = logo.resize((max(1, round(logo.width * scale)),
                                        max(1, round(logo.height * scale))))
                    # A wide logo is a wordmark -- it already spells the
                    # company name, so don't print the name next to it.
                    is_wordmark = logo.width > logo.height * 2.2
                    img.paste(logo, (x, y + (max_h - logo.height) // 2), logo)
                    text_x = x + logo.width + 20
                except Exception:
                    logo_path = None
            if not logo_path and business:
                # No logo from Seek -- draw the initials tile instead of
                # leaving the card to open with a bare line of text.
                _draw_initials_badge(img, draw, x, y, 58, business, ink)
                text_x = x + 58 + 20
            if business and not is_wordmark:
                name = _wrap(draw, business, F_COMPANY, card_x1 - CARD_PAD - text_x, 1)[0]
                draw.text((text_x, y + 16), name, font=F_COMPANY, fill=GREY)

        elif kind == "title":
            for line in title_lines:
                draw.text((x, y), line, font=F_TITLE, fill=ink)
                y += 66
            y -= h  # y advanced inside the loop; the block adds it back below

        elif kind == "pill":
            label = f"Closing {closing}"
            tw = draw.textlength(label, font=F_PILL)
            pill_w = tw + 40 + 34
            bg, fg = CALM_BG, CALM_FG
            draw.rounded_rectangle([x, y, x + pill_w, y + 50], radius=25, fill=bg)
            _clock_icon(draw, x + 20, y + 15, fg)
            draw.text((x + 54, y + 12), label, font=F_PILL, fill=fg)

        elif kind == "location":
            _pin_icon(draw, x + 2, y + 4, ink)
            loc = _wrap(draw, location, F_BODY, inner_w - 44, 1)[0]
            draw.text((x + 40, y + 2), loc, font=F_BODY, fill=ink)

        elif kind == "pay":
            pay_font = _fit_font(draw, pay, inner_w)
            draw.text((x, y), pay, font=pay_font, fill=ink)

        elif kind == "startdate":
            draw.text((x, y), "START DATE", font=F_LABEL, fill=GREY_LABEL)
            value = _wrap(draw, starts, F_VALUE, inner_w, 1)[0]
            draw.text((x, y + 30), value, font=F_VALUE, fill=ink)

        elif kind == "worktype":
            draw.text((x, y), "WORK TYPE", font=F_LABEL, fill=GREY_LABEL)
            draw.text((x, y + 30), work_type, font=F_VALUE, fill=ink)

        elif kind == "field":
            draw.text((x, y), "FIELD", font=F_LABEL, fill=GREY_LABEL)
            value = _wrap(draw, field, F_VALUE, inner_w, 1)[0]
            draw.text((x, y + 30), value, font=F_VALUE, fill=ink)

        elif kind == "button":
            draw.rounded_rectangle([x, y, card_x1 - CARD_PAD, y + 92],
                                   radius=22, fill=ink)
            label = "Apply on employer site"
            tw = draw.textlength(label, font=F_BUTTON)
            bx = x + ((card_x1 - CARD_PAD - x) - tw - 34) / 2
            draw.text((bx, y + 28), label, font=F_BUTTON, fill=CARD)
            ax, ay = bx + tw + 18, y + 38
            draw.line([(ax, ay + 14), (ax + 14, ay)], fill=CARD, width=3)
            draw.line([(ax + 3, ay), (ax + 14, ay)], fill=CARD, width=3)
            draw.line([(ax + 14, ay), (ax + 14, ay + 11)], fill=CARD, width=3)

        y += h

    # handle at the bottom, over the background
    handle = f"@{account_handle}"
    hw = draw.textlength(handle, font=F_PILL)
    draw.text(((W - hw) / 2, H - 62), handle, font=F_PILL, fill=(235, 238, 245))

    poster_path = os.path.join(out_dir, filename)
    _save(img, poster_path)

    if not write_caption:
        return poster_path

    # ---- caption, built from the same real values ----
    lines = [f"{title} — {business}" if business else title, ""]
    if location:
        lines.append(f"Location: {location}")
    if work_type:
        lines.append(f"Work type: {work_type}")
    if pay:
        lines.append(f"Pay: {pay}")
    if starts:
        lines.append(f"Starts: {starts}")
    if closing:
        lines.append(f"Applications close: {closing}")
    lines.append("")

    parser = _ListItemExtractor()
    facts = []
    if job.get("description_html"):
        try:
            parser.feed(job["description_html"])
            facts = [li for li in parser.items if 15 <= len(li) <= 140][:3]
        except Exception:
            facts = []
    if facts:
        lines.append("What they're after:")
        lines += [f"— {f}" for f in facts]
        lines.append("")

    lines.append("Apply via link in bio.")
    lines.append("via Seek")
    lines.append("")
    tags = ["#internship", "#sydneyinternships", "#studentjobs"]
    if field:
        tags.append("#" + re.sub(r"[^a-z0-9]", "", field.lower())[:22])
    lines.append(" ".join(tags))

    with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return poster_path


def build_cover(category, count, out_dir, account_handle="[your account handle]",
                filename="slide_01_cover.jpg", seed="cover", n_grad=0):
    """
    Slide 1 of a carousel: the category name over a dimmed photo, no job on
    it. Same background treatment and palette as the job cards so the whole
    carousel reads as one post.
    """
    os.makedirs(out_dir, exist_ok=True)

    ink, deep = palette_for(category)
    img = _background(seed, deep)
    # A cover carries only text, so it can take a heavier dim than the job
    # cards (which sit under a white card that does the contrast work).
    img = Image.blend(img, Image.new("RGB", (W, H), NEUTRAL_DIM), 0.35)
    img = Image.blend(img, Image.new("RGB", (W, H), deep), TINT_STRENGTH)
    draw = ImageDraw.Draw(img)

    x = 96
    content_w = W - 2 * x

    # small label pills at the top
    pill_y = 150
    pills = (("SYDNEY", "INTERNSHIPS & GRADS") if n_grad
             else ("SYDNEY", "INTERNSHIPS"))
    for label in pills:
        f = F_PILL
        tw = draw.textlength(label, font=f)
        pw = tw + 44
        draw.rounded_rectangle([x, pill_y, x + pw, pill_y + 52], radius=26,
                               outline=(255, 255, 255), width=2)
        draw.text((x + 22, pill_y + 13), label, font=f, fill=(255, 255, 255))
        x += pw + 16
    x = 96

    # the category name, as big as it can be while still fitting 4 lines
    for size in (104, 92, 82, 72, 64):
        f_big = _font("DejaVuSans-Bold.ttf", size)
        lines = _wrap(draw, category, f_big, content_w)
        if len(lines) <= 4:
            break
    line_h = int(size * 1.16)
    block_h = len(lines) * line_h
    y = (H - block_h) // 2 - 20
    for line in lines:
        draw.text((x, y), line, font=f_big, fill=(255, 255, 255))
        y += line_h

    # how many roles, and a swipe hint
    y += 26
    # Engineering carousels may carry graduate programmes alongside
    # internships, so the cover states the mix rather than a vague "9 roles".
    n_intern = count - n_grad
    if n_grad and n_intern:
        sub = (f"{n_intern} internship{'s' if n_intern != 1 else ''}"
               f"  \u00b7  {n_grad} graduate role{'s' if n_grad != 1 else ''}")
    elif n_grad:
        sub = f"{n_grad} graduate role{'s' if n_grad != 1 else ''}"
    else:
        sub = f"{count} internship{'s' if count != 1 else ''}"
    draw.text((x, y), sub, font=_font("DejaVuSans.ttf", 40), fill=(214, 222, 240))

    swipe = "swipe for all of them  \u2192"
    f_sw = _font("DejaVuSans-Bold.ttf", 32)
    draw.text((x, H - 190), swipe, font=f_sw, fill=(255, 255, 255))

    handle = f"@{account_handle}"
    hw = draw.textlength(handle, font=F_PILL)
    draw.text(((W - hw) / 2, H - 62), handle, font=F_PILL, fill=(235, 238, 245))

    path = os.path.join(out_dir, filename)
    _save(img, path)
    return path
