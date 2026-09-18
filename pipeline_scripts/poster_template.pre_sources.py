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
import math
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
BERRY = (176, 40, 88)
BERRY_DEEP = (66, 20, 38)

PALETTES = {
    "Business, Commerce, Marketing & Finance":
        ((176, 40, 88), (66, 20, 38)),          # berry -- the brand colour
    "Technology, Data & AI":
        ((13, 116, 128), (12, 44, 48)),         # teal
    "Engineering":
        ((190, 82, 40), (72, 32, 18)),          # rust
}

# What almost all the type on a card is actually set in. Not pure black --
# pure black on white is harsh at this size -- and not the accent either.
INK_DARK = (23, 33, 54)


# Short forms, for the cover pill and the FIELD row. The full names are
# correct but they are four words long and they do not fit anywhere.
SHORT_CATEGORY = {
    "Business, Commerce, Marketing & Finance": "Finance & business",
    "Technology, Data & AI": "Tech & data",
    "Engineering": "Engineering",
}


# The photo is dimmed towards a neutral charcoal, NOT towards the category
# colour -- tinting the whole frame made every post look like a colour filter
# had been dropped on it. The category colour lives in the text and the
# button, where it reads as a design choice instead of a cast. TINT_STRENGTH
# is the last whisper of hue left in the photo; raise it if you ever want the
# older look back, but keep it low.
NEUTRAL_DIM = (26, 28, 32)
TINT_STRENGTH = 0.03


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

# 84 put the card 84px from a 1080px edge, which is close enough to the
# frame that it stopped reading as an object sitting ON a photo and started
# reading as a white slide with a border. 132 gives it room to sit back.
CARD_MARGIN = 152
CARD_PAD = 58
# Rounder, to match the reference. At 1080 this is about the radius a phone
# UI uses, which is why it reads as an interface element rather than a box.
CARD_RADIUS = 62

HERE = os.path.dirname(os.path.abspath(__file__))
LOGOS_DIR = os.path.join(HERE, "logos")
# "background pics" is the folder get_backgrounds.py fills. The older
# "backgrounds" name is still checked so anything already dropped in there
# keeps working.
BACKGROUND_DIRS = [os.path.join(HERE, "background pics"),
                   os.path.join(HERE, "backgrounds")]


RESTYLED = True

# Weight axis values for the two roles the old code asked for by filename.
# 800 rather than 700 for bold: Nunito is lighter than DejaVu at the same
# nominal weight, and headlines were coming out limp.
_WEIGHTS = {"DejaVuSans-Bold.ttf": 800, "DejaVuSans.ttf": 500}
_NUNITO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fonts", "Nunito[wght].ttf")


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
_HAVE_NUNITO = os.path.exists(_NUNITO)
if not _HAVE_NUNITO:
    print("  ! fonts/Nunito[wght].ttf missing -- falling back to DejaVu.\n"
          "    The slides will build, they will just look like the old ones.")


def _font(name, size):
    """`name` is still a DejaVu filename because that is what the rest of the
    file asks for; it is read as a weight and served out of Nunito."""
    if _HAVE_NUNITO:
        f = ImageFont.truetype(_NUNITO, size)
        try:
            f.set_variation_by_axes([_WEIGHTS.get(name, 500)])
        except Exception:
            pass
        return f
    return ImageFont.truetype(FD + name, size)


F_COMPANY = _font("DejaVuSans.ttf", 33)
F_TITLE = _font("DejaVuSans-Bold.ttf", 60)
F_PILL = _font("DejaVuSans-Bold.ttf", 29)
F_BODY = _font("DejaVuSans.ttf", 34)
F_PAY = _font("DejaVuSans-Bold.ttf", 48)
F_PAY_UNIT = _font("DejaVuSans.ttf", 33)
F_LABEL = _font("DejaVuSans-Bold.ttf", 23)
F_VALUE = _font("DejaVuSans.ttf", 35)
F_BUTTON = _font("DejaVuSans-Bold.ttf", 34)


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


def closing_label(closing):
    """('Closing in 3 days', True) when it is close, else ('Closing 9 October
    2026', False). Returns the plain date unchanged if it cannot be parsed,
    so an odd date format degrades to what it always showed rather than to
    something wrong."""
    from datetime import date, datetime
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(closing.strip(), fmt).date()
            break
        except ValueError:
            continue
    else:
        return f"Closing {closing}", False

    days = (d - date.today()).days
    if days < 0:
        return f"Closing {closing}", False
    if days == 0:
        return "Closing today", True
    if days == 1:
        return "Closing tomorrow", True
    if days <= 7:
        return f"Closing in {days} days", True
    return f"Closing {closing}", False


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


def _background(job_id, deep=NAVY_DEEP, dim=0.20, blur=1.2):
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
            # Lift the photo BEFORE dimming it. These stock desk shots are
            # shot moody and warm, and simply dimming them less just gave a
            # brighter version of the same murk -- the fix is to open them
            # up first and then take only as much light back out as the
            # white card actually needs.
            from PIL import ImageEnhance
            photo = ImageEnhance.Brightness(photo).enhance(1.20)
            photo = ImageEnhance.Contrast(photo).enhance(1.10)
            photo = ImageEnhance.Color(photo).enhance(1.12)
            photo = photo.filter(ImageFilter.GaussianBlur(blur))
            photo = Image.blend(photo, Image.new("RGB", (W, H), NEUTRAL_DIM), dim)
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
        [card_x0 + 4, card_y0 + 20, card_x1 + 4, card_y1 + 20],
        radius=CARD_RADIUS, fill=(0, 0, 0, 92))
    img = Image.alpha_composite(img.convert("RGBA"),
                                shadow.filter(ImageFilter.GaussianBlur(34))).convert("RGB")
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
                draw.text((x, y), line, font=F_TITLE, fill=INK_DARK)
                y += 66
            y -= h  # y advanced inside the loop; the block adds it back below

        elif kind == "pill":
            label, urgent = closing_label(closing)
            tw = draw.textlength(label, font=F_PILL)
            pill_w = tw + 40 + 34
            bg, fg = (URGENT_BG, URGENT_FG) if urgent else (CALM_BG, CALM_FG)
            draw.rounded_rectangle([x, y, x + pill_w, y + 50], radius=25, fill=bg)
            _clock_icon(draw, x + 20, y + 15, fg)
            draw.text((x + 54, y + 12), label, font=F_PILL, fill=fg)

        elif kind == "location":
            _pin_icon(draw, x + 2, y + 4, INK_DARK)
            loc = _wrap(draw, location, F_BODY, inner_w - 44, 1)[0]
            draw.text((x + 40, y + 2), loc, font=F_BODY, fill=INK_DARK)

        elif kind == "pay":
            pay_font = _fit_font(draw, pay, inner_w)
            draw.text((x, y), pay, font=pay_font, fill=INK_DARK)

        elif kind == "startdate":
            draw.text((x, y), "START DATE", font=F_LABEL, fill=GREY_LABEL)
            value = _wrap(draw, starts, F_VALUE, inner_w, 1)[0]
            draw.text((x, y + 30), value, font=F_VALUE, fill=INK_DARK)

        elif kind == "worktype":
            draw.text((x, y), "WORK TYPE", font=F_LABEL, fill=GREY_LABEL)
            draw.text((x, y + 30), work_type, font=F_VALUE, fill=INK_DARK)

        elif kind == "field":
            draw.text((x, y), "FIELD", font=F_LABEL, fill=GREY_LABEL)
            value = SHORT_CATEGORY.get(field.strip(), field)
            value = _wrap(draw, value, F_VALUE, inner_w, 1)[0]
            draw.text((x, y + 30), value, font=F_VALUE, fill=INK_DARK)

        elif kind == "button":
            draw.rounded_rectangle([x, y, card_x1 - CARD_PAD, y + 92],
                                   radius=30, fill=ink)
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


def _camera_chrome(img, draw):
    """The phone-camera furniture along the bottom, and the framing grid.

    This is the whole idea of the new cover. A cover slide that is just big
    type over a dimmed photo looks like a template; the same photo inside a
    camera viewfinder looks like something someone shot on their phone this
    morning, which is what stops a thumb. It costs nothing and it is not
    pretending to be anything -- nobody thinks a carousel cover is a live
    camera feed.
    """
    # rule-of-thirds grid, faint
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for i in (1, 2):
        g.line([(W * i / 3, 0), (W * i / 3, H)], fill=(255, 255, 255, 46), width=2)
        g.line([(0, H * i / 3), (W, H * i / 3)], fill=(255, 255, 255, 46), width=2)
    img.alpha_composite(grid)

    # the mode strip. PHOTO is the selected one, so it is the yellow one and
    # it sits dead centre, exactly as the real thing does.
    modes = ["SLO-MO", "VIDEO", "PHOTO", "SQUARE", "STICKER"]
    f_mode = _font("DejaVuSans-Bold.ttf", 27)
    widths = [draw.textlength(m, font=f_mode) for m in modes]
    gap = 44
    total = sum(widths) + gap * (len(modes) - 1)
    # centre the strip on PHOTO rather than on the whole row, so the selected
    # mode is centred in frame however long the words either side are.
    before = sum(widths[:2]) + gap * 2 + widths[2] / 2
    mx = W / 2 - before
    for m, wdt in zip(modes, widths):
        on = (m == "PHOTO")
        draw.text((mx, H - 208), m, font=f_mode,
                  fill=(247, 200, 60) if on else (232, 234, 238))
        mx += wdt + gap

    # shutter: a white ring with a filled disc inside it
    cx, cy, r = W / 2, H - 108, 46
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=6)
    draw.ellipse([cx - r + 13, cy - r + 13, cx + r - 13, cy + r - 13],
                 fill=(255, 255, 255))

    # the last-photo thumbnail on the left and the flip button on the right
    draw.rounded_rectangle([84, cy - 40, 164, cy + 40], radius=14,
                           outline=(255, 255, 255, 150), width=3)
    fx, fy, fr = W - 124, cy, 26
    draw.arc([fx - fr, fy - fr, fx + fr, fy + fr], 40, 300,
             fill=(255, 255, 255), width=5)


def _bubble(draw, cx, y, text, font):
    """An iMessage-grey speech bubble, centred on cx, with its tail bottom
    left. Returns the bottom edge."""
    tw = draw.textlength(text, font=font)
    pad_x, h = 40, 84
    x0, x1 = cx - (tw + pad_x * 2) / 2, cx + (tw + pad_x * 2) / 2
    draw.rounded_rectangle([x0, y, x1, y + h], radius=h / 2, fill=(233, 233, 235))
    # the tail: a small circle and a triangle, which is how the real one is
    # actually drawn and why it never looks like a bolted-on arrow
    draw.ellipse([x0 - 14, y + h - 30, x0 + 12, y + h - 4], fill=(233, 233, 235))
    draw.ellipse([x0 - 24, y + h - 18, x0 - 8, y + h - 2], fill=(233, 233, 235))
    draw.text((x0 + pad_x, y + (h - font.size * 1.25) / 2), text,
              font=font, fill=(28, 28, 30))
    return y + h


def build_cover(category, count, out_dir, account_handle="[your account handle]",
                filename="slide_01_cover.jpg", seed="cover", n_grad=0):
    """
    Slide 1 of a carousel: the pitch, shot through a phone viewfinder.

    Nothing on it is invented -- the count is the number of real listings in
    the carousel behind it, and the category is ours.
    """
    os.makedirs(out_dir, exist_ok=True)

    ink, deep = palette_for(category)
    # A cover is all photo, so it gets far less dimming than a job slide and
    # no blur at all. The type is protected by the scrims below instead,
    # which darken only the two bands the type sits in.
    img = _background(seed, deep, dim=0.10, blur=0).convert("RGBA")

    # top and bottom scrims, so the headline and the chrome have something to
    # sit on without flattening the middle of the picture
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for row in range(300):
        sd.line([(0, row), (W, row)], fill=(0, 0, 0, int(120 * (1 - row / 300))))
    for row in range(360):
        sd.line([(0, H - 1 - row), (W, H - 1 - row)],
                fill=(0, 0, 0, int(165 * (1 - row / 360))))
    img.alpha_composite(scrim)
    draw = ImageDraw.Draw(img)

    # ---- the headline ------------------------------------------------------
    # The category goes in a small pill above rather than into the headline.
    # "Finance & business internships in Sydney" is three lines of medium
    # type; "Internships in Sydney" is two lines of huge type, and huge type
    # is the only kind that survives being a thumbnail in a feed. The pill
    # still tells you which carousel this is.
    headline = "Internships in Sydney"
    for size in (132, 118, 104, 92):
        f_big = _font("DejaVuSans-Bold.ttf", size)
        lines = _wrap(draw, headline, f_big, W - 130)
        if len(lines) <= 2:
            break
    line_h = int(size * 1.14)
    block_h = len(lines) * line_h
    y = (H - block_h) / 2 - 40

    # The pill is placed OFF the headline rather than at a fixed height. At a
    # fixed 300 it sat exactly where a two-line headline starts and the two
    # printed on top of each other.
    short = SHORT_CATEGORY.get((category or "").strip(), category or "")
    if short:
        f_eb = _font("DejaVuSans-Bold.ttf", 30)
        label = short.upper()
        tw = draw.textlength(label, font=f_eb)
        pw, ph = tw + 52, 60
        ex, ey = (W - pw) / 2, y - ph - 44
        draw.rounded_rectangle([ex, ey, ex + pw, ey + ph], radius=ph / 2,
                               outline=(255, 255, 255, 230), width=3)
        draw.text((ex + 26, ey + 13), label, font=f_eb, fill=(255, 255, 255))

    # A soft shadow under the type rather than a box behind it: the point of
    # the cover is the photograph, and a panel would cover it up.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shd = ImageDraw.Draw(shadow)
    yy = y
    for line in lines:
        lw = draw.textlength(line, font=f_big)
        shd.text(((W - lw) / 2, yy + 6), line, font=f_big, fill=(0, 0, 0, 130))
        yy += line_h
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))
    draw = ImageDraw.Draw(img)

    yy = y
    for line in lines:
        lw = draw.textlength(line, font=f_big)
        draw.text(((W - lw) / 2, yy), line, font=f_big, fill=(255, 255, 255))
        yy += line_h

    # ---- the bubble --------------------------------------------------------
    n_intern = count - n_grad
    if n_grad and n_intern:
        msg = f"{n_intern} internships + {n_grad} grad roles"
    elif n_grad:
        msg = f"{n_grad} grad roles, open now"
    else:
        msg = f"{count} open right now" if count != 1 else "1 open right now"
    _bubble(draw, W / 2, yy + 56, msg, _font("DejaVuSans.ttf", 38))

    # ---- chrome ------------------------------------------------------------
    _camera_chrome(img, draw)

    handle = f"@{account_handle}"
    f_h = _font("DejaVuSans-Bold.ttf", 28)
    hw = draw.textlength(handle, font=f_h)
    draw.text(((W - hw) / 2, 62), handle, font=f_h, fill=(255, 255, 255, 225))

    path = os.path.join(out_dir, filename)
    _save(img.convert("RGB"), path)
    return path


# The last slide of every carousel. Change these and every future carousel
# follows -- they are the whole ask, so they live here rather than buried in
# the drawing code.
CTA_WORD = "ACCESS"
CTA_LEAD = "Comment"
CTA_TAIL = "and I'll send you every internship in Sydney"

# Your profile, as it appears on the card. The follower count is deliberately
# NOT on here. It would be out of date the day after a rebuild, and a slide
# that advertises how few followers you have is working against you -- the
# card exists to show people who to follow and where to go, and both of those
# are on it.
PROFILE = {
    "handle": "berry.internships.syd",
    "name": "Berry Internships",
    "bio": ["we find the internships so you don't have to",
            "Sydney only  \u00b7  uni students only"],
    "link": "internberry.netlify.app",
}

# The light palette, lifted from your site's own :root light theme, so this
# slide looks like the website it is sending people to.
LIGHT_BG = (247, 244, 248)
LIGHT_CARD = (255, 255, 255)
LIGHT_INK = (26, 18, 28)
LIGHT_DIM = (124, 111, 129)
LIGHT_LINE = (227, 217, 226)
LINK_BLUE = (0, 85, 204)


def _mark_polygon(inner=0.84, c=32, r=26, n=8):
    """The points of your berry mark. Same maths as the site: one polygon
    whose inner radius is the only thing that moves."""
    pts = []
    for i in range(n * 2):
        a = math.pi * i / n - math.pi / 2
        rr = r * inner if i % 2 else r
        pts.append((c + math.cos(a) * rr, c + math.sin(a) * rr))
    return pts


def _draw_avatar(img, cx, cy, size, ink):
    """Your profile picture: the mark, filled, on white, inside a ring --
    which is what it actually looks like on the app."""
    d = ImageDraw.Draw(img)
    r = size / 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255),
              outline=LIGHT_LINE, width=3)
    # the mark itself, scaled from its 64-unit box into the circle
    scale = size * 0.62 / 64
    pts = [(cx + (x - 32) * scale, cy + (y - 32) * scale)
           for x, y in _mark_polygon()]
    d.polygon(pts, fill=ink)


def _line_with_accent(draw, x, y, parts, font, base, accent):
    """Draw one line where some words are a different colour. parts is a list
    of (text, is_accent). Returns the x it finished at."""
    for text, hot in parts:
        draw.text((x, y), text, font=font, fill=accent if hot else base)
        x += draw.textlength(text, font=font)
    return x


def endcard_profile(category, out_dir, account_handle="[your account handle]",
                  filename="slide_99_end.jpg", seed="end"):
    """
    The last slide: the ask, over a mock of your own profile.

    Two ideas from two posts that already work. The ask is the one that is
    just a word in big type -- it is unmissable and it tells someone exactly
    what to type. The profile card is the one that shows the account itself,
    which is the bit the word-only version is missing: someone who has just
    read six job slides needs to know WHO to follow, and a name in a caption
    is not the same as seeing the profile they are about to land on.

    Light, not a photo. Every other slide in the carousel sits on a
    photograph, so the last one changing to clean white is what makes it
    read as the end rather than as one more card.
    """
    os.makedirs(out_dir, exist_ok=True)
    ink, _deep = palette_for(category)

    img = Image.new("RGB", (W, H), LIGHT_BG)
    draw = ImageDraw.Draw(img)

    x = 96
    content_w = W - 2 * x

    # ---- the ask -----------------------------------------------------------
    # Sized to fit rather than assumed: CTA_TAIL is editable, and a longer
    # line should shrink the type instead of running off the slide.
    for size in (72, 66, 60, 54):
        f = _font("DejaVuSans-Bold.ttf", size)
        words = f"{CTA_LEAD} {CTA_WORD} {CTA_TAIL}".split()
        lines, cur = [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if draw.textlength(trial, font=f) <= content_w:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        if len(lines) <= 3:
            break

    y = 108
    line_h = int(size * 1.28)
    for line in lines:
        # Split the line so CTA_WORD comes out in the category colour. It is
        # the one word anybody has to actually read.
        parts, buf = [], ""
        for wd in line.split():
            if wd == CTA_WORD:
                if buf:
                    parts.append((buf + " ", False))
                    buf = ""
                parts.append((wd + " ", True))
            else:
                buf += wd + " "
        if buf:
            parts.append((buf, False))
        _line_with_accent(draw, x, y, parts, f, LIGHT_INK, ink)
        y += line_h

    # ---- the profile card --------------------------------------------------
    card_y0 = y + 40
    card_y1 = H - 150
    draw.rounded_rectangle([x, card_y0, W - x, card_y1], radius=44,
                           fill=LIGHT_CARD, outline=LIGHT_LINE, width=2)

    pad = 52
    av = 132
    av_cx, av_cy = x + pad + av / 2, card_y0 + pad + av / 2
    _draw_avatar(img, av_cx, av_cy, av, ink)
    draw = ImageDraw.Draw(img)

    tx = x + pad + av + 34
    f_handle = _font("DejaVuSans-Bold.ttf", 44)
    f_name = _font("DejaVuSans.ttf", 33)
    draw.text((tx, av_cy - 46), "@" + PROFILE["handle"], font=f_handle,
              fill=LIGHT_INK)
    draw.text((tx, av_cy + 8), PROFILE["name"], font=f_name, fill=LIGHT_DIM)

    by = card_y0 + pad + av + 42
    f_bio = _font("DejaVuSans.ttf", 34)
    for row in PROFILE["bio"]:
        draw.text((x + pad, by), row, font=f_bio, fill=LIGHT_INK)
        by += 50

    # the link row, in the blue Instagram actually renders links in
    by += 16
    f_link = _font("DejaVuSans-Bold.ttf", 36)
    lx = x + pad
    # a small chain-link glyph, drawn rather than fetched
    draw.arc([lx, by + 6, lx + 26, by + 32], 200, 20, fill=LINK_BLUE, width=5)
    draw.arc([lx + 14, by + 6, lx + 40, by + 32], 20, 200, fill=LINK_BLUE, width=5)
    draw.text((lx + 54, by), PROFILE["link"], font=f_link, fill=LINK_BLUE)

    path = os.path.join(out_dir, filename)
    _save(img, path)
    return path


def endcard_bar(category, out_dir, account_handle="[your account handle]",
                filename="slide_99_end.jpg", seed="end"):
    """
    The other ask: the word, huge, over the photo, with the comment field
    drawn underneath it with the word already typed in.

    The reference you sent for this one is a word on a plain yellow square,
    which is unmissable and does nothing else. The comment field is what
    stops it being only that -- telling someone to comment ACCESS and showing
    them the box they are about to type it into are different asks, and the
    second one is followed without thinking.
    """
    os.makedirs(out_dir, exist_ok=True)
    ink, deep = palette_for(category)

    img = _background(seed, deep, dim=0.34, blur=1.0).convert("RGBA")
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 60))
    img.alpha_composite(scrim)
    draw = ImageDraw.Draw(img)

    f_small = _font("DejaVuSans-Bold.ttf", 54)
    f_big = _font("DejaVuSans-Bold.ttf", 148)

    y = 250
    tw = draw.textlength(CTA_LEAD.lower(), font=f_small)
    draw.text(((W - tw) / 2, y), CTA_LEAD.lower(), font=f_small,
              fill=(226, 220, 232))

    y += 86
    tw = draw.textlength(CTA_WORD, font=f_big)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text(((W - tw) / 2, y + 8), CTA_WORD, font=f_big,
                            fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    draw = ImageDraw.Draw(img)
    draw.text(((W - tw) / 2, y), CTA_WORD, font=f_big, fill=(255, 255, 255))

    y += 190
    f_line = _font("DejaVuSans.ttf", 40)
    line = CTA_TAIL if len(CTA_TAIL) < 46 else "and I'll send you the full list"
    tw = draw.textlength(line, font=f_line)
    draw.text(((W - tw) / 2, y), line, font=f_line, fill=(214, 208, 220))

    bar_x0, bar_x1 = 108, W - 108
    bar_y, bar_h = 748, 108
    draw.rounded_rectangle([bar_x0, bar_y, bar_x1, bar_y + bar_h],
                           radius=bar_h / 2, fill=(255, 255, 255))
    av_r = 34
    av_cx, av_cy = bar_x0 + 34 + av_r, bar_y + bar_h / 2
    _draw_avatar(img, av_cx, av_cy, av_r * 2, ink)
    draw = ImageDraw.Draw(img)

    f_typed = _font("DejaVuSans.ttf", 42)
    draw.text((av_cx + av_r + 26, bar_y + 30), CTA_WORD.lower(),
              font=f_typed, fill=(28, 28, 30))
    f_post = _font("DejaVuSans-Bold.ttf", 38)
    pw = draw.textlength("Post", font=f_post)
    draw.text((bar_x1 - 40 - pw, bar_y + 33), "Post", font=f_post,
              fill=(0, 149, 246))

    handle = f"@{account_handle}"
    f_h = _font("DejaVuSans-Bold.ttf", 29)
    hw = draw.textlength(handle, font=f_h)
    draw.text(((W - hw) / 2, H - 96), handle, font=f_h, fill=(226, 220, 232))

    path = os.path.join(out_dir, filename)
    _save(img.convert("RGB"), path)
    return path


ENDCARDS = [endcard_profile, endcard_bar]


def build_endcard(category, out_dir, account_handle="[your account handle]",
                  filename="slide_99_end.jpg", seed="end"):
    """Pick one of the two and draw it.

    Chosen from the carousel's own name rather than at random, so a category
    keeps the same ending every time you rebuild -- a genuinely random pick
    would change the last slide of a carousel that is already sitting in the
    queue waiting to be posted, which is not a surprise you want.
    """
    which = ENDCARDS[sum(ord(c) for c in str(seed)) % len(ENDCARDS)]
    return which(category, out_dir, account_handle=account_handle,
                 filename=filename, seed=seed)
