#!/usr/bin/env python3
"""
build_site.py -- the public job board.

    python3 build_site.py            build and open it
    python3 build_site.py --quiet    build without opening a browser

Writes berry_internships.html next to this script: one self-contained page
with every internship currently worth showing, searchable and filterable in
the browser with no server behind it.

WHAT GETS ON THE PAGE, and what does not:

  * internships only -- graduate programmes are filtered out, the same as
    the carousels, because the account is called berry.internships.syd
  * posted within MAX_AGE_DAYS (14) -- older ads are usually filled
  * one of the four categories -- anything else is not what we cover
  * not closed -- check_live.py asks Seek about each listing by id and
    records the ones that are Expired or deleted. This is what makes a
    CommBank role that was here last week disappear this week. We never
    infer "gone" from a job's absence in the latest crawl: the crawl is
    capped, so a live job can be missing simply because it fell past the
    limit, and deleting on that basis would remove open roles.

So the honest order of operations for a weekly refresh is:

    python3 refresh.py                 does all three of the below, in order
      ../scrapers/seek.py              find new Seek listings
      ../scrapers/other_boards.py      find new LinkedIn/Indeed/Glassdoor ones
      python3 check_live.py            find out which old Seek ones have closed
      python3 build_site.py            rebuild the page
"""

import argparse
import html
import json
import os
import re
import sys
import webbrowser
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # the "job account " folder
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))   # repo root, for GitHub Actions

from all_jobs import (categorize, is_internship, job_track, job_age_days,
                      MAX_AGE_DAYS, load_dead_listings)              # noqa: E402
from build_carousels import (load_all_jobs, real_company,             # noqa: E402
                             employer_identity, _title_key)
from poster_template import (clean_pay, brand_domain, FAVICON,        # noqa: E402
                             _logo_for)

# How big the mark is baked in at. The cards draw it at 40px and the featured
# panel at 62px, so 96 covers a retina screen with a little room and nothing
# more -- every extra pixel here is bytes on a page that has to load on a
# phone on the train.
LOGO_PX = 96

_LOGO_CACHE = {}


def _brand_logo(company, logo_url=""):
    """
    The company's mark, baked into the page as a data URI.

    THIS IS THE FIX. The old version handed the browser a Google favicon URL
    and hoped. Three things were wrong with that:

      * it ignored logos/ entirely, so a mark you had dropped in by hand --
        the override that wins on every slide -- did nothing on the website
      * it ignored the cached logo the advertiser actually supplied, so an
        employer with a perfectly good Seek logo but no entry in
        brand_domains.json got an initials tile here while getting its real
        logo on the carousel
      * every visitor's browser had to reach Google, and a blocked or slow
        request left a broken image on a job board

    Now it asks poster_template the same question the slides ask, gets back
    a file, and embeds it. Same resolver, same order of preference, same
    manual overrides -- so the site and the posts can never disagree about
    what a company looks like, and find_logos.py improves both at once.
    """
    key = ((company or "").strip().lower(), logo_url or "")
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]

    uri = ""
    try:
        path = _logo_for(company, logo_url)
        if path and os.path.getsize(path) > 0:
            import base64
            from io import BytesIO
            from PIL import Image
            im = Image.open(path).convert("RGBA")
            im.thumbnail((LOGO_PX, LOGO_PX), Image.LANCZOS)
            buf = BytesIO()
            # WebP rather than PNG, and it is not a small difference: the same
            # 65 marks came to 390 KB as PNG and about a third of that as
            # WebP. Alpha survives, and every browser that can open this page
            # can read it.
            fmt, mime = "WEBP", "image/webp"
            try:
                im.save(buf, fmt, quality=82, method=6)
            except Exception:
                buf = BytesIO()
                fmt, mime = "PNG", "image/png"
                im.save(buf, fmt, optimize=True)
            uri = (f"data:{mime};base64,"
                   + base64.b64encode(buf.getvalue()).decode("ascii"))
    except Exception:
        # A logo is never worth failing a build over. No mark means the card
        # falls back to its initials tile, which is what it did before.
        uri = ""

    _LOGO_CACHE[key] = uri
    return uri

OUT = os.path.join(HERE, "berry_internships.html")

ACCOUNT = "berry.internships.syd"
INSTAGRAM = f"https://www.instagram.com/{ACCOUNT}/"

# Same four colours as the slides, so the site and the posts look related.
CATEGORY_COLOURS = {
    "Business, Commerce, Marketing & Finance": "#8e2f52",
    "Technology, Data & AI": "#1d5c61",
    "Engineering": "#9a4a2c",
}

# A listing this new gets a "New" flag.
NEW_WITHIN_DAYS = 3


def collect():
    """Every internship that belongs on the page, newest first."""
    dead = load_dead_listings()
    rows, dropped = [], {"grad": 0, "old": 0, "closed": 0, "uncategorised": 0,
                         "not internship": 0}

    for j in load_all_jobs():
        title = j.get("job_title") or ""
        desc = j.get("description_text") or ""

        if not is_internship(title, desc, j.get("work_type")):
            dropped["not internship"] += 1
            continue
        if job_track(title, desc, j.get("work_type")) == "Graduate Programs":
            dropped["grad"] += 1
            continue
        category = categorize(title, desc)
        if not category:
            dropped["uncategorised"] += 1
            continue
        age = job_age_days(j.get("posted_date"))
        if age is not None and age > MAX_AGE_DAYS:
            dropped["old"] += 1
            continue
        if str(j.get("job_id")) in dead:
            dropped["closed"] += 1
            continue

        rows.append({
            "id": str(j.get("job_id") or ""),
            "title": title,
            "company": real_company(j.get("company_name") or j.get("business_name")),
            # The verified list wins over whatever the board sent. If we know
            # for certain this is Commonwealth Bank, the card shows the real
            # Commonwealth Bank mark -- not whatever image the advertiser
            # happened to upload, which is often a campaign banner, a stock
            # photo or nothing at all. The scraped logo is the fallback, and
            # a name we cannot identify keeps its initials tile rather than
            # us guessing a domain.
            # logo_url is passed IN rather than used as a fallback after
            # the fact: _logo_for already knows to prefer a verified brand
            # mark over the advertiser's upload, and to fall back to it when
            # there is no verified domain. Doing it out here second-guessed
            # that and skipped the cache.
            "logo": _brand_logo(real_company(j.get("company_name")
                                             or j.get("business_name")),
                                j.get("logo_url") or ""),
            "location": (j.get("suburb") or j.get("area")
                         or j.get("region") or "Sydney NSW"),
            "pay": clean_pay(j.get("pay_range")) or "",
            "work_type": j.get("work_type") or "",
            "category": category,
            "url": j.get("url") or "",
            "age": age if age is not None else -1,
        })

    # Newest first; anything with no date sorts to the end rather than the top,
    # since an unknown date is not evidence of freshness.
    rows.sort(key=lambda r: (r["age"] if r["age"] >= 0 else 10_000))

    # ------------------------------------------------------------------
    # ONE CARD PER ROLE.
    #
    # The same job arrives from Seek, LinkedIn, Indeed and Glassdoor under
    # whatever name each board stored, so the page was showing Munich Re's
    # Summer Internship three times, Zurich's twice more, and so on -- 16 of
    # 97 cards were a job you had already scrolled past. Exactly the bug the
    # carousels had, and it is fixed here with exactly the same test:
    # brand domain plus the role title with the company name taken back out
    # of it, so "Munich Re" and "Munich Reinsurance" collapse.
    #
    # Rows are already newest-first, and within a duplicate group the one
    # that has a logo wins over the one that does not -- a listing is a
    # listing either way, so keep the copy that looks like something.
    # ------------------------------------------------------------------
    best, order = {}, []
    for r in rows:
        who = employer_identity({"company_name": r["company"]})
        key = (who, _title_key(r["title"], who))
        if key not in best:
            best[key] = r
            order.append(key)
        elif r.get("logo") and not best[key].get("logo"):
            best[key] = r
    deduped = [best[k] for k in order]
    dropped["duplicate"] = len(rows) - len(deduped)
    return deduped, dropped


# The page is one long template with @@TOKEN@@ placeholders rather than an
# f-string, because CSS and JavaScript are full of braces and escaping every
# one of them makes the whole thing unreadable and easy to break.
TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>berry &mdash; Sydney internships</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;800&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;700&display=swap">
<style>
  :root {
    --bg: #f7f3f1;
    --bg-2: #efe8e6;
    --card: #ffffff;
    --ink: #1c1518;
    --ink-2: #5c5258;
    --muted: #8a7f86;
    --line: #eadfe4;
    --line-soft: #f0e8eb;
    --berry: #c42d5e;
    --teal: #1a6c70;
    --rust: #b5522c;
    --ok: #1a7a4c;
    --r: 16px;
    --shadow: 0 1px 2px rgba(28,21,24,.04), 0 12px 32px -18px rgba(28,21,24,.18);
    --dur: .22s;
    --ease: cubic-bezier(.22,.8,.28,1);
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; overflow-x: clip; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font: 16px/1.5 "Inter Tight", -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  body::before {
    content: "";
    position: fixed; inset: 0; z-index: -1; pointer-events: none;
    background:
      radial-gradient(900px 420px at 12% -8%, rgba(196,45,94,.10), transparent 62%),
      radial-gradient(700px 360px at 100% 0%, rgba(26,108,112,.08), transparent 58%);
  }
  a { color: inherit; }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 0 24px; }
  ::selection { background: color-mix(in srgb, var(--berry) 28%, white); }
  :focus-visible { outline: 2px solid var(--berry); outline-offset: 3px; }

  .bar {
    position: sticky; top: 0; z-index: 30;
    background: color-mix(in srgb, var(--bg) 78%, transparent);
    -webkit-backdrop-filter: blur(18px) saturate(140%);
    backdrop-filter: blur(18px) saturate(140%);
    border-bottom: 1px solid var(--line);
  }
  .bar .wrap {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; padding-top: 14px; padding-bottom: 14px;
  }
  .brand { display: flex; align-items: center; gap: 10px; text-decoration: none; }
  .brand b { font: 800 18px/1 Archivo, sans-serif; letter-spacing: -.03em; }
  .mark { width: 30px; height: 30px; flex: none; color: var(--berry); overflow: visible; }
  .m-ghost { opacity: .28; }
  .ig {
    display: inline-flex; align-items: center; gap: 8px;
    text-decoration: none; font: 600 13.5px "Inter Tight", sans-serif;
    color: #fff; background: var(--berry); padding: 8px 15px; border-radius: 999px;
    transition: transform var(--dur) var(--ease), filter var(--dur) var(--ease);
  }
  .ig:hover { transform: translateY(-1px); filter: brightness(1.06); }
  .ig svg { width: 14px; height: 15px; fill: currentColor; }
  .ig::after { display: none; }

  /* Opening WebGL scene is off: it ate four screens before the jobs. */
  .berry, .drops, .rail { display: none !important; }

  .hero { padding: 56px 0 36px; }
  .kicker {
    font: 700 11px/1 "JetBrains Mono", monospace; letter-spacing: .2em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 18px;
  }
  h1 {
    margin: 0; font-family: Archivo, sans-serif; font-weight: 800;
    font-size: clamp(2.2rem, 6vw, 4.1rem); line-height: 1.02;
    letter-spacing: -.045em; text-wrap: balance;
  }
  h1 .n { color: var(--berry); font-variant-numeric: tabular-nums; }
  h1.big { display: flex; flex-wrap: wrap; align-items: center; gap: .12em .28em; }
  h1.big .ln { white-space: nowrap; }
  .pill {
    flex: none; display: block; width: .9em; height: .42em; border-radius: 999px;
    background: linear-gradient(120deg, #7ec8f2 0%, #c42d5e 100%);
  }
  .scanline {
    margin: 16px 0 0; font-family: "JetBrains Mono", monospace;
    font-size: .8rem; letter-spacing: .04em; color: var(--muted);
  }
  .scanline b { color: var(--ink-2); font-weight: 700; font-variant-numeric: tabular-nums; }
  .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 26px; }
  .stat {
    display: flex; align-items: baseline; gap: 8px;
    padding: 10px 14px; border: 1px solid var(--line); border-radius: 999px;
    background: var(--card); font-size: .84rem; color: var(--ink-2);
  }
  .stat b {
    font: 700 1.05rem/1 "JetBrains Mono", monospace;
    color: var(--c, var(--berry)); font-variant-numeric: tabular-nums;
  }

  .stage { height: auto; }
  .pin { position: static; height: auto; display: block; overflow: visible; padding: 8px 0 36px; }
  .pcard {
    position: relative; width: min(720px, 100%); margin: 0 auto; padding: 28px 28px 24px;
    border-radius: 20px; background: var(--card); border: 1px solid var(--line);
    box-shadow: var(--shadow);
  }
  .pcard .ptop { display: flex; gap: 14px; align-items: center; }
  .plogo {
    width: 56px; height: 56px; border-radius: 14px; flex: none; overflow: hidden;
    display: grid; place-items: center; background: #fff; border: 1px solid var(--line);
  }
  .plogo img { width: 100%; height: 100%; object-fit: contain; padding: 8px; }
  .plogo .initials { width: 100%; height: 100%; border-radius: 0; font-size: 18px; }
  .pcard h2 {
    margin: 0; font: 800 clamp(1.2rem, 2.8vw, 1.7rem)/1.2 Archivo, sans-serif;
    letter-spacing: -.03em;
  }
  .pcard .pco { color: var(--ink-2); margin-top: 4px; font-size: .95rem; }
  .ptags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 18px; }
  .ptag {
    border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 12px; font-size: .82rem; color: var(--ink-2); opacity: 1;
    background: var(--bg);
  }
  .ptag.pay {
    color: var(--ok); font: 700 12px "JetBrains Mono", monospace;
    border-color: color-mix(in srgb, var(--ok) 35%, transparent);
    background: color-mix(in srgb, var(--ok) 8%, white);
  }
  .applybig {
    display: inline-flex; align-items: center; gap: 10px; margin-top: 22px;
    text-decoration: none; color: #fff; background: var(--c, var(--berry));
    font: 700 15px "Inter Tight", sans-serif; padding: 12px 22px;
    border-radius: 999px; opacity: 1;
    transition: transform var(--dur) var(--ease), filter var(--dur) var(--ease);
  }
  .applybig:hover { transform: translateY(-1px); filter: brightness(1.05); }
  .applybig svg { width: 16px; height: 12px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; }
  .prail { display: none; }
  .ptxt {
    text-align: center; margin: 14px 0 0;
    font: 700 10px/1 "JetBrains Mono", monospace; letter-spacing: .22em;
    text-transform: uppercase; color: var(--muted);
  }
  @media (max-width: 720px) { .pcard { padding: 22px; } }

  .controls { padding: 8px 0 10px; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  .sw { position: relative; flex: 1 1 300px; min-width: 0; display: flex; }
  .sw input { flex: 1; padding-right: 70px; }
  .sw .clr {
    position: absolute; right: 38px; top: 50%; transform: translateY(-50%);
    width: 26px; height: 26px; border: 0; border-radius: 50%; cursor: pointer;
    background: var(--line); color: var(--ink); font: 600 14px/1 sans-serif;
    display: none; place-items: center; padding: 0;
  }
  .sw .clr:hover { background: var(--berry); color: #fff; }
  .sw.has .clr { display: grid; }
  .sw kbd {
    position: absolute; right: 11px; top: 50%; transform: translateY(-50%);
    font: 600 11px/1 "JetBrains Mono", monospace; color: var(--muted);
    border: 1px solid var(--line); border-radius: 6px; padding: 3px 6px;
    pointer-events: none; background: var(--bg);
  }
  .sw.has kbd, .sw:focus-within kbd { display: none; }
  @media (hover: none) { .sw kbd { display: none; } }
  input[type=search], select {
    font: 15px "Inter Tight", sans-serif; color: var(--ink); background: var(--card);
    border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
    transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  }
  input[type=search] { flex: 1 1 280px; min-width: 0; }
  input[type=search]:hover, select:hover { border-color: color-mix(in srgb, var(--berry) 40%, var(--line)); }
  input[type=search]:focus, select:focus {
    outline: none; border-color: var(--berry);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--berry) 18%, transparent);
  }
  input[type=search]::placeholder { color: var(--muted); }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  @media (max-width: 720px) {
    .chips {
      flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
      -webkit-overflow-scrolling: touch;
      margin-left: -24px; margin-right: -24px; padding: 2px 24px;
    }
    .chips::-webkit-scrollbar { display: none; }
    .chip { flex: none; }
    .sw { flex: 1 1 150px; }
    select { flex: 0 0 auto; }
  }
  .chip {
    display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
    font: 500 13.5px "Inter Tight", sans-serif; color: var(--ink-2);
    background: var(--card); border: 1px solid var(--line);
    border-radius: 999px; padding: 9px 14px; min-height: 42px;
    transition: color var(--dur) var(--ease), border-color var(--dur) var(--ease),
                background var(--dur) var(--ease);
  }
  .chip:hover { border-color: var(--c); color: var(--ink); }
  .tick { width: 15px; height: 15px; flex: none; display: block; }
  .tick svg { width: 100%; height: 100%; overflow: visible; }
  .tk-box {
    fill: var(--c); stroke: var(--c); stroke-width: 1.7;
    transform: scale(.55); transform-origin: 8px 8px;
    transition: transform .28s var(--ease), fill .2s var(--ease), rx .28s var(--ease);
  }
  .tk-mark {
    fill: none; stroke: var(--c); stroke-width: 2.1;
    stroke-linecap: round; stroke-linejoin: round;
    stroke-dasharray: 11; stroke-dashoffset: 11;
  }
  .tk-ring { display: none; }
  .chip[aria-pressed="true"] .tk-box { transform: scale(1); fill: transparent; rx: 4; }
  .chip[aria-pressed="true"] .tk-mark {
    stroke-dashoffset: 0; transition: stroke-dashoffset .25s var(--ease) .05s;
  }
  .chip b { font: 700 11px/1 "JetBrains Mono", monospace; color: var(--muted); }
  .chip.alt { --c: var(--berry); }
  .chipgap { width: 1px; align-self: stretch; margin: 6px 4px; background: var(--line); flex: none; }
  .chip[aria-pressed="true"] {
    color: var(--c); border-color: color-mix(in srgb, var(--c) 45%, var(--line));
    background: color-mix(in srgb, var(--c) 9%, white);
  }
  .chip[aria-pressed="true"] b { color: var(--c); }
  .summary {
    display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
    padding: 18px 0 12px;
  }
  .count { margin: 0; color: var(--ink-2); font: 400 13px/1.4 "JetBrains Mono", monospace; }
  .count s { color: var(--muted); text-decoration: none; }
  .clearall {
    background: none; border: 0; cursor: pointer; padding: 0;
    font: 600 13px "Inter Tight", sans-serif; color: var(--berry);
    border-bottom: 1px solid color-mix(in srgb, var(--berry) 40%, transparent);
  }
  .clearall[hidden] { display: none; }
  .tag.pay {
    color: var(--ok); border-color: color-mix(in srgb, var(--ok) 28%, transparent);
    background: color-mix(in srgb, var(--ok) 8%, white); font-weight: 600;
  }
  .src { font: 500 11px/1 "JetBrains Mono", monospace; color: var(--muted); letter-spacing: .04em; }
  .tlink { color: inherit; text-decoration: none; }
  .tlink::after { content: ""; position: absolute; inset: 0; z-index: 1; border-radius: var(--r); }
  .card:hover .tlink { text-decoration: underline; text-underline-offset: 3px; text-decoration-thickness: 1px; }
  .ship { z-index: 3; }
  .card .foot { position: relative; z-index: 2; }

  .grid {
    display: grid; gap: 14px;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    padding-bottom: 72px;
  }
  .card {
    position: relative; background: var(--card); border: 1px solid var(--line);
    border-radius: var(--r); padding: 18px 18px 16px;
    /* The browser skips layout and paint for cards that are off screen, which
       is what keeps a 200-card page scrolling smoothly. The intrinsic size is
       the measured average card (min 161, median 182, max 223), so the scrollbar
       barely moves; "auto" means the real height is remembered after first paint. */
    content-visibility: auto;
    contain-intrinsic-size: auto 188px;
    display: flex; flex-direction: column; gap: 12px;
    box-shadow: 0 1px 0 rgba(28,21,24,.03);
    transition: transform var(--dur) var(--ease), border-color var(--dur) var(--ease),
                box-shadow var(--dur) var(--ease);
  }
  .card::before {
    content: ""; position: absolute; left: 0; top: 16px; bottom: 16px;
    width: 3px; border-radius: 0 3px 3px 0; background: var(--c);
  }
  .card:hover {
    z-index: 4; transform: translateY(-3px); border-color: color-mix(in srgb, var(--c) 35%, var(--line));
    box-shadow: var(--shadow);
  }
  .top { display: flex; gap: 12px; align-items: flex-start; }
  .logo {
    width: 42px; height: 42px; border-radius: 10px; flex: none; object-fit: contain;
    background: #fff; border: 1px solid var(--line); padding: 5px;
  }
  .initials {
    width: 42px; height: 42px; border-radius: 10px; flex: none; display: grid;
    place-items: center; background: var(--c); color: #fff;
    font: 700 13px Archivo, sans-serif;
  }
  .card h2 { margin: 0; font: 600 15.5px/1.35 "Inter Tight", sans-serif; letter-spacing: -.01em; }
  .co { font-size: 13px; color: var(--muted); margin-top: 3px; }
  .meta { display: flex; flex-wrap: wrap; gap: 6px; }
  .tag {
    font: 400 12px/1.5 "Inter Tight", sans-serif; color: var(--ink-2);
    background: var(--bg); border: 1px solid var(--line);
    border-radius: 999px; padding: 4px 9px;
  }
  .tag.pay {
    color: var(--ok); border-color: color-mix(in srgb, var(--ok) 30%, transparent);
    background: color-mix(in srgb, var(--ok) 8%, white); font-weight: 600;
    font-family: "JetBrains Mono", monospace; font-size: 11.5px;
  }
  .new {
    font: 700 10px/1 "JetBrains Mono", monospace; letter-spacing: .08em;
    text-transform: uppercase; color: var(--ok);
    border: 1px solid color-mix(in srgb, var(--ok) 30%, transparent);
    border-radius: 999px; padding: 5px 8px;
    background: color-mix(in srgb, var(--ok) 8%, white);
  }
  .foot {
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    margin-top: auto; padding-top: 6px;
  }
  .age { font: 400 11.5px "JetBrains Mono", monospace; color: var(--muted); }
  .apply {
    position: relative; font: 600 13px "Inter Tight", sans-serif; text-decoration: none;
    color: var(--ink); border: 1px solid var(--line); border-radius: 999px;
    padding: 8px 14px; white-space: nowrap; background: var(--card);
    transition: background var(--dur) var(--ease), color var(--dur) var(--ease),
                border-color var(--dur) var(--ease);
  }
  .card:hover .apply { border-color: var(--c); color: var(--c); }
  .apply:hover, .apply:focus-visible {
    color: #fff; border-color: var(--c); background: var(--c);
  }
  .apply::before, .apply::after { display: none; }
  .ship { position: relative; display: inline-block; }
  .flight { display: none; }

  /* Only the first rows are hidden for the entrance. Hiding all 200+ meant
     every off-screen card sat at opacity 0 waiting its turn, which is what
     left grey gaps if you scrolled straight after a filter change. */
  .grid.reveal .card:nth-child(-n+16) { opacity: 0; transform: translateY(10px); }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    .grid.reveal .card:nth-child(-n+16) { opacity: 1; transform: none; }
    * { transition-duration: .01ms !important; }
  }

  .empty { padding: 64px 0 80px; color: var(--muted); text-align: center; }
  .empty b {
    display: block; color: var(--ink); font: 700 1.15rem/1.3 Archivo, sans-serif;
    margin-bottom: 8px;
  }
  .empty button {
    margin-top: 16px; cursor: pointer; color: #fff; background: var(--berry);
    border: 0; border-radius: 999px; font: 600 14px "Inter Tight", sans-serif;
    padding: 10px 18px;
  }
  footer {
    border-top: 1px solid var(--line); padding: 22px 0 52px;
    color: var(--muted); font-size: 13px;
  }
  footer a { color: var(--berry); text-decoration: none; }
  footer a:hover { text-decoration: underline; }
  main, footer { position: relative; z-index: 2; }
  .flick { font-variant-numeric: tabular-nums; }
  .c-0 { --c: var(--teal); }
  .c-1 { --c: var(--berry); }
  .c-2 { --c: var(--rust); }

</style></head><body>

<!-- Scroll rail. Fixed to the side, the bead tracks how far down the page you
     are and leans into the direction you are moving. Pure decoration would not
     earn a fixed element on every screen; this one is also the page's only
     progress indicator, which is why it stays. -->
<!-- Floating capsules. Purely atmospheric, so they sit behind everything,
     ignore pointer events, and are generated in JS -- a viewer with no
     JavaScript gets a clean page rather than a broken decoration. -->
<!-- Gradient definitions for the paper planes. Every card's plane points at
     these by id, so the document holds one copy rather than one per card --
     and no duplicate ids, which is what inlining defs into a template that
     runs forty times would give you. -->
<svg width="0" height="0" aria-hidden="true" style="position:absolute">
  <defs>
    <linearGradient id="planeTrail" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="#7ec8f2"/><stop offset=".5" stop-color="#b4b6ef"/>
      <stop offset="1" stop-color="#f2a9e2"/>
    </linearGradient>
    <linearGradient id="planeTop" x1="0" y1="0" x2=".7" y2="1">
      <stop offset="0" stop-color="#f2a9e2"/><stop offset=".55" stop-color="#b4b6ef"/>
      <stop offset="1" stop-color="#7ec8f2"/>
    </linearGradient>
    <linearGradient id="planeLow" x1="0" y1="0" x2=".6" y2="1">
      <stop offset="0" stop-color="#8fd0f5"/><stop offset="1" stop-color="#6f7fd6"/>
    </linearGradient>
    <linearGradient id="planeFold" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4b3f7a"/><stop offset="1" stop-color="#2d2550"/>
    </linearGradient>
  </defs>
</svg>

<div class="drops" id="drops" aria-hidden="true"></div>

<div class="bar"><div class="wrap">
  <a class="brand" href="#top" aria-label="berry, Sydney internships">
    <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
      <g fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round">
        <polygon class="m-ghost" points=""></polygon>
        <polygon class="m-lead"  points=""></polygon>
      </g>
    </svg><b>berry</b></a>
  <a class="ig" href="@@IG@@" target="_blank" rel="noopener">
    <svg viewBox="0 0 24 24"><path d="M12 2.2c3.2 0 3.6 0 4.9.07 1.2.05 1.8.25 2.2.42.6.22 1 .48 1.4.9.4.4.7.8.9 1.4.2.4.4 1 .4 2.2.1 1.3.1 1.7.1 4.9s0 3.6-.1 4.9c0 1.2-.2 1.8-.4 2.2-.2.6-.5 1-.9 1.4-.4.4-.8.7-1.4.9-.4.2-1 .4-2.2.4-1.3.1-1.7.1-4.9.1s-3.6 0-4.9-.1c-1.2 0-1.8-.2-2.2-.4-.6-.2-1-.5-1.4-.9-.4-.4-.7-.8-.9-1.4-.2-.4-.4-1-.4-2.2C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.9c0-1.2.2-1.8.4-2.2.2-.6.5-1 .9-1.4.4-.4.8-.7 1.4-.9.4-.2 1-.4 2.2-.4C8.4 2.2 8.8 2.2 12 2.2Zm0 1.8c-3.1 0-3.5 0-4.8.07-1 .05-1.6.22-1.9.36-.5.18-.8.4-1.1.7-.3.3-.5.6-.7 1.1-.1.3-.3.9-.4 1.9C3 9.5 3 9.9 3 13s0 3.5.1 4.8c.1 1 .3 1.6.4 1.9.2.5.4.8.7 1.1.3.3.6.5 1.1.7.3.1.9.3 1.9.4 1.3.06 1.7.07 4.8.07s3.5 0 4.8-.07c1-.1 1.6-.3 1.9-.4.5-.2.8-.4 1.1-.7.3-.3.5-.6.7-1.1.1-.3.3-.9.4-1.9.06-1.3.07-1.7.07-4.8s0-3.5-.07-4.8c-.1-1-.3-1.6-.4-1.9-.2-.5-.4-.8-.7-1.1-.3-.3-.6-.5-1.1-.7-.3-.1-.9-.3-1.9-.36C15.5 4 15.1 4 12 4Zm0 3.1a4.9 4.9 0 1 1 0 9.8 4.9 4.9 0 0 1 0-9.8Zm0 8a3.1 3.1 0 1 0 0-6.2 3.1 3.1 0 0 0 0 6.2Zm6.2-8.2a1.15 1.15 0 1 1-2.3 0 1.15 1.15 0 0 1 2.3 0Z"/></svg>
    @@HANDLE@@
  </a>
</div></div>

<main id="top">

  <!-- The opening. Everything in it is drawn by JavaScript; with none, the
       section collapses and the words below are simply there. -->
  <section class="berry" id="berry" aria-label="berry">
    <div class="berrypin">
      <canvas id="berrycanvas" aria-hidden="true"></canvas>
      <div class="btitle">
        <span class="bl kick" data-at="0.04">Sydney &middot; updated @@UPDATED@@</span>
        <span class="bl big"  data-at="0.56"><span class="n">@@TOTAL@@</span> internships</span>
        <span class="bl sml"  data-at="0.72">open right now &mdash; every one of them
          checked against the source this week</span>
      </div>
      <p class="bhint" id="bhint">Scroll<i></i></p>
    </div>
  </section>
  <section class="hero"><div class="wrap">
    <div class="kicker">Sydney &middot; updated @@UPDATED@@</div>
    <h1 class="big">
      <span class="ln"><span class="n" id="bignum">@@TOTAL@@</span> internships</span>
      <span class="pill" id="heropill" aria-hidden="true"></span>
      <span class="ln">open right now</span>
    </h1>
    <p class="scanline"><b class="flick" id="scanned">@@SCANNED@@</b>
       listings scanned this week to find them</p>
    <div class="stats">@@STATS@@</div>
  </div></section>

  <!-- One role, pulled out and given the whole screen. Which role it is
       comes from the data, not from a hard-coded example -- see pick_featured. -->
  <section class="stage" id="stage" aria-label="Featured role">
    <div class="pin">
      <div class="prail c-@@FEATIDX@@" id="prail"><i></i></div>
      <article class="pcard c-@@FEATIDX@@" id="pcard">
        <div class="ptop">
          <span class="plogo" id="plogo">@@FEATLOGO@@</span>
          <div>
            <h2>@@FEATTITLE@@</h2>
            <div class="pco">@@FEATCO@@</div>
          </div>
        </div>
        <div class="ptags">@@FEATTAGS@@</div>
        <span class="ship big">
          <a class="applybig" id="papply" href="@@FEATURL@@" target="_blank" rel="noopener">
            @@FEATCTA@@
            <svg viewBox="0 0 18 14" aria-hidden="true"><path d="M1 7h15M11 1l6 6-6 6"/></svg>
          </a>
          <span class="flight" aria-hidden="true">
            <svg class="trail" viewBox="0 0 420 140">
              <path class="t1" pathLength="100" d="@@BIGFLIGHT@@"/>
              <path class="t2" pathLength="100" d="@@BIGFLIGHT@@"/>
            </svg>
            <svg class="plane big" viewBox="0 0 100 70">
              <path d="M3 5 L98 36 L44 41 Z"   fill="url(#planeTop)"/>
              <path d="M44 41 L98 36 L57 57 Z" fill="url(#planeFold)"/>
              <path d="M8 63 L98 36 L40 44 Z"  fill="url(#planeLow)"/>
            </svg>
          </span>
        </span>
      </article>
      <p class="ptxt" id="ptxt">Featured role</p>
    </div>
  </section>

  <div class="wrap">
    <div class="controls">
      <div class="row">
        <div class="sw" id="sw">
          <input type="search" id="q" placeholder="Search role, company or suburb"
                 aria-label="Search internships" autocomplete="off">
          <button class="clr" id="clrq" type="button" aria-label="Clear search">&times;</button>
          <kbd>/</kbd>
        </div>
        <select id="sort" aria-label="Sort">
          <option value="new">Newest first</option>
          <option value="company">Company A&ndash;Z</option>
          <option value="title">Role A&ndash;Z</option>
          <option value="paid">Pay listed first</option>
        </select>
      </div>
      <div class="chips" id="chips">@@CHIPS@@<span class="chipgap" aria-hidden="true"></span>
        <button class="chip alt" data-flag="paid">
          <span class="tick" aria-hidden="true"><svg viewBox="0 0 16 16">
            <circle class="tk-ring" cx="8" cy="8" r="7"/>
            <rect class="tk-box" x="1.5" y="1.5" width="13" height="13" rx="6.5"/>
            <path class="tk-mark" d="M4.4 8.3 L6.9 10.8 L11.6 5.4"/>
          </svg></span>Pay listed<b id="npaid"></b></button>
        <button class="chip alt" data-flag="new">
          <span class="tick" aria-hidden="true"><svg viewBox="0 0 16 16">
            <circle class="tk-ring" cx="8" cy="8" r="7"/>
            <rect class="tk-box" x="1.5" y="1.5" width="13" height="13" rx="6.5"/>
            <path class="tk-mark" d="M4.4 8.3 L6.9 10.8 L11.6 5.4"/>
          </svg></span>New this week<b id="nnew"></b></button>
      </div>
    </div>
    <div class="summary">
      <p class="count" id="count" role="status" aria-live="polite"></p>
      <button class="clearall" id="clearall" type="button" hidden>Clear all</button>
    </div>
    <div class="grid" id="grid"></div>
    <div class="empty" id="empty" hidden>
      <b>Nothing matches that</b>
      Try a broader word, or drop a filter.
      <div><button type="button" id="emptyclear">Clear all filters</button></div>
    </div>
  </div>
</main>

<footer><div class="wrap">
  Every role links straight to its original listing &middot;
  new ones posted to <a href="@@IG@@" target="_blank" rel="noopener">@@HANDLE@@</a>
</div></footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.13.0/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.13.0/ScrollTrigger.min.js"></script>
<script>
const JOBS = @@JOBS@@;
const SCANNED = @@SCANNED@@;
const CAT_INDEX = @@CATINDEX@@;
const NEW_WITHIN = @@NEWWITHIN@@;
const active = new Set();
const grid = document.getElementById("grid");
const FLIGHT = "M14 108 C 52 100, 84 82, 106 58 S 140 26, 160 8";
const countEl = document.getElementById("count");
const empty = document.getElementById("empty");
const sw = document.getElementById("sw");
const clearAll = document.getElementById("clearall");
const q = document.getElementById("q");
const sortBy = document.getElementById("sort");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function initials(name) {
  const noise = new Set(["pty","ltd","limited","inc","group","australia","the",
    "co","corp","company","holdings","services","summer","winter","intern",
    "internship","program","programme","graduate","vacation","cadetship"]);
  let w = String(name||"").split(/[^A-Za-z0-9]+/).filter(Boolean).filter(x=>!/^\\d+$/.test(x));
  const m = w.filter(x=>!noise.has(x.toLowerCase()));
  w = m.length ? m : w;
  if (!w.length) return "?";
  if (w.length === 1) {
    const s = w[0];
    for (let i=1;i<s.length;i++) if (s[i] === s[i].toUpperCase() && /[A-Z]/.test(s[i]))
      return (s[0]+s[i]).toUpperCase();
    return s.slice(0,2).toUpperCase();
  }
  return (w[0][0]+w[1][0]).toUpperCase();
}

/* Where the Apply link actually goes, read off the link itself rather than
   stored as a field -- one less thing that can disagree with reality. */
function srcOf(url) {
  try {
    const h = new URL(url).hostname.replace(/^www\./, "");
    const name = h.includes("seek") ? "Seek"
               : h.includes("linkedin") ? "LinkedIn"
               : h.includes("indeed") ? "Indeed"
               : h.split(".")[0];
    return ` <span class="src">&middot; ${esc(name)}</span>`;
  } catch (e) { return ""; }
}

const ageLabel = d => d < 0 ? "" : d === 0 ? "Posted today"
  : d === 1 ? "Posted yesterday" : `Posted ${d} days ago`;

function card(j) {
  const i = CAT_INDEX[j.category] ?? 0;
  const badge = j.logo
    ? `<img class="logo" src="${esc(j.logo)}" alt="" loading="lazy"
         onerror="this.outerHTML='<span class=\'initials\'>${esc(initials(j.company))}</span>'">`
    : `<span class="initials">${esc(initials(j.company))}</span>`;
  const tags = [];
  if (j.pay) tags.push(`<span class="tag pay">${esc(j.pay)}</span>`);
  if (j.work_type) tags.push(`<span class="tag">${esc(j.work_type)}</span>`);
  tags.push(`<span class="tag">${esc(j.location)}</span>`);
  if (j.age >= 0 && j.age <= NEW_WITHIN) tags.push(`<span class="new">New</span>`);
  return `<article class="card c-${i}">
    <div class="top">${badge}<div>
      <h2><a class="tlink" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></h2>
      <div class="co">${esc(j.company || j.category)}</div></div></div>
    <div class="meta">${tags.join("")}</div>
    <div class="foot"><span class="age">${ageLabel(j.age)}${srcOf(j.url)}</span>
      <span class="ship">
        <a class="apply" href="${esc(j.url)}" target="_blank" rel="noopener">Apply</a>
        <span class="flight" aria-hidden="true">
          <svg class="trail" viewBox="0 0 170 120">
            <path class="t1" pathLength="100" d="${FLIGHT}"/>
            <path class="t2" pathLength="100" d="${FLIGHT}"/>
          </svg>
          <svg class="plane" viewBox="0 0 100 70">
            <path d="M3 5 L98 36 L44 41 Z"   fill="url(#planeTop)"/>
            <path d="M44 41 L98 36 L57 57 Z" fill="url(#planeFold)"/>
            <path d="M8 63 L98 36 L40 44 Z"  fill="url(#planeLow)"/>
          </svg>
        </span>
      </span>
    </div></article>`;
}

/* ---- the cursor bloom -------------------------------------------------------
   The bloom's position is two custom properties the CSS reads, so JavaScript
   never touches a style that costs layout -- it writes two numbers and the
   compositor does the rest.

   The listener sits on the grid rather than on each button. Cards are thrown
   away and rebuilt on every filter change, so per-button listeners would have
   to be re-attached each time; one listener on the container that never gets
   replaced cannot go stale.
--------------------------------------------------------------------------- */
if (!reduced) {
  grid.addEventListener("pointermove", e => {
    const btn = e.target.closest(".apply");
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    btn.style.setProperty("--mx", ((e.clientX - r.left) / r.width * 100) + "%");
    btn.style.setProperty("--my", ((e.clientY - r.top) / r.height * 100) + "%");
  }, {passive: true});
}

/* A short stagger on the cards. It exists to show that filtering actually
   re-ran, not for decoration, so it is fast and it never delays reading:
   the cards are already in the DOM and visible unless this runs. */
function stagger() {
  if (reduced || !grid.animate) return;
  grid.classList.add("reveal");
  // Only the cards you can actually see are worth animating. Handing the
  // browser 200+ Web Animations at once costs far more than the effect is
  // worth, and every one of them holds its card invisible until it runs.
  const cards = [...grid.children].slice(0, 16);
  cards.forEach((el, i) => {
    el.animate(
      [{opacity:0, transform:"translateY(14px)"}, {opacity:1, transform:"none"}],
      {duration:420, delay:Math.min(i,14)*32, easing:"cubic-bezier(.22,.8,.28,1)", fill:"both"}
    );
  });
  setTimeout(()=>grid.classList.remove("reveal"), 900);
}

const flags = {paid: false, new: false};

function render(animate) {
  const term = q.value.trim().toLowerCase();
  let rows = JOBS.filter(j =>
    (active.size === 0 || active.has(j.category)) &&
    (!flags.paid || !!j.pay) &&
    (!flags.new  || (j.age >= 0 && j.age <= NEW_WITHIN)) &&
    (!term || (j.title+" "+j.company+" "+j.location+" "+j.category)
      .toLowerCase().includes(term)));
  const by = sortBy.value;
  if (by === "company") rows.sort((a,b)=>(a.company||"~").localeCompare(b.company||"~"));
  else if (by === "title") rows.sort((a,b)=>a.title.localeCompare(b.title));
  else if (by === "paid") rows.sort((a,b)=>(b.pay?1:0)-(a.pay?1:0) || a.age-b.age);
  else rows.sort((a,b)=>(a.age<0?1e4:a.age)-(b.age<0?1e4:b.age));

  grid.innerHTML = rows.map(card).join("");
  empty.hidden = rows.length > 0;

  // The count is a live region, so a screen reader hears the list change
  // rather than silently getting a different page under it.
  countEl.innerHTML = rows.length === JOBS.length
    ? `${rows.length} roles`
    : `${rows.length} <s>of ${JOBS.length}</s> roles`;
  clearAll.hidden = !isFiltered();
  writeUrl();
  if (animate) stagger();
}

function isFiltered() {
  return active.size > 0 || flags.paid || flags.new || q.value.trim() !== "";
}

/* Filters live in the address bar, so a filtered view survives a reload and
   can be sent to someone. Written with replaceState rather than pushState:
   typing a search term should not fill up the back button. */
function writeUrl() {
  const p = new URLSearchParams();
  if (q.value.trim()) p.set("q", q.value.trim());
  if (active.size) p.set("cat", [...active].join("|"));
  if (flags.paid) p.set("paid", "1");
  if (flags.new) p.set("new", "1");
  if (sortBy.value !== "new") p.set("sort", sortBy.value);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
}

function readUrl() {
  const p = new URLSearchParams(location.search);
  if (p.get("q")) q.value = p.get("q");
  (p.get("cat") || "").split("|").filter(Boolean).forEach(c => active.add(c));
  flags.paid = p.get("paid") === "1";
  flags.new  = p.get("new") === "1";
  if (p.get("sort")) sortBy.value = p.get("sort");
}

function clearEverything() {
  active.clear();
  flags.paid = flags.new = false;
  q.value = "";
  syncControls();
  render(true);
}

/* One place that puts the controls back in step with the state, so the URL,
   the Clear all button and a chip click all go through the same path. */
function syncControls() {
  document.querySelectorAll(".chip").forEach(c => {
    const on = c.dataset.flag ? flags[c.dataset.flag] : active.has(c.dataset.cat);
    c.setAttribute("aria-pressed", String(!!on));
  });
  sw.classList.toggle("has", q.value.trim() !== "");
}

/* ---- the berry mark ----
   Eight points at alternating radii. Pull the inner radius in and it is a
   spark; push it out and it rounds into a berry. Animating one number
   between those two states is the whole morph -- no path data to interpolate
   and nothing to go wrong when the two shapes disagree about point count. */
const MARK_POINTS = 8, MARK_C = 32, MARK_R = 26;

function markPoints(inner) {
  const p = [];
  for (let i = 0; i < MARK_POINTS * 2; i++) {
    const a = (Math.PI * i) / MARK_POINTS - Math.PI / 2;
    const r = i % 2 ? MARK_R * inner : MARK_R;
    p.push((MARK_C + Math.cos(a) * r).toFixed(1) + "," +
           (MARK_C + Math.sin(a) * r).toFixed(1));
  }
  return p.join(" ");
}

(function animateMark() {
  const lead = document.querySelector(".m-lead");
  const ghost = document.querySelector(".m-ghost");
  if (!lead) return;
  const SPARK = 0.36, BERRY = 0.84;
  if (reduced) {
    lead.setAttribute("points", markPoints(SPARK));
    ghost.setAttribute("points", markPoints(SPARK));
    return;
  }
  const start = performance.now(), period = 5200;
  const ease = t => t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
  const at = ms => {
    // a slow there-and-back, so it never snaps
    const t = ((ms % period) / period) * 2;
    return SPARK + (BERRY - SPARK) * ease(t > 1 ? 2 - t : t);
  };
  const frame = now => {
    const ms = now - start;
    lead.setAttribute("points", markPoints(at(ms)));
    ghost.setAttribute("points", markPoints(at(ms - 340)));   // trails behind
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
})();


/* ---- atmosphere: floating capsules ----------------------------------------
   Generated rather than written into the markup, so the count adapts to the
   viewport and a viewer without JavaScript gets a clean page instead of a
   decoration frozen mid-air.

   Each capsule carries its own speed. Scrolling moves them by that multiple
   of the scroll distance, which is all parallax is -- the illusion of depth
   comes from the spread of speeds, not from any one of them.
--------------------------------------------------------------------------- */
function atmosphere() {
  const host = document.getElementById("drops");
  if (!host || reduced) return;

  // The capsules are the only atmosphere on the page now, so there are a lot
  // more of them than when they shared the screen with something else.
  const n = Math.round(gsap.utils.clamp(28, 70, innerWidth / 24));
  const drops = [];
  for (let i = 0; i < n; i++) {
    const el = document.createElement("span");
    const w = gsap.utils.random(7, 24, 1);
    el.className = "drop";
    Object.assign(el.style, {
      width: w + "px",
      height: gsap.utils.random(w * 2.2, w * 7, 1) + "px",
      left: gsap.utils.random(-3, 101, .1) + "vw",
      top: "0px",
      opacity: gsap.utils.random(.4, .95, .01),
    });
    host.appendChild(el);
    // A little rotation stops the field reading as a bar chart. Set through
    // GSAP rather than the style attribute so the scroll parallax below can
    // add a translation without wiping it out.
    gsap.set(el, {rotation: gsap.utils.random(-14, 14, 1)});
    drops.push({
      el,
      speed: gsap.utils.random(0.25, 1.9),
      base: gsap.utils.random(-200, innerHeight + 200),
    });
  }

  if (!window.ScrollTrigger) return;

  // Each capsule is placed by wrapping its position into a band that runs from
  // just above the viewport to just below it. Without the wrap they would all
  // drift off the top within the first screen of scrolling and the rest of the
  // page would be bare -- with it, the field never runs out.
  const setters = drops.map(d => gsap.quickSetter(d.el, "y", "px"));
  const place = scrolled => {
    const top = -220, bottom = innerHeight + 220;
    drops.forEach((d, i) =>
      setters[i](gsap.utils.wrap(top, bottom, d.base - scrolled * d.speed * 0.35)));
  };
  place(0);
  ScrollTrigger.create({start: 0, end: "max", onUpdate: self => place(self.scroll())});
  addEventListener("resize", () => place(scrollY));
}

/* ---- the headline capsule --------------------------------------------------
   The shape between the two halves of the headline opens and closes as the
   hero scrolls past: the timeline is scrubbed, so it is the scroll position
   that decides how far open it is, not a clock. Because the capsule is a flex
   item, widening it pushes the words apart and the whole line re-lays out --
   which is the point. It never closes to nothing, so at any scroll position
   there is still a shape sitting there rather than a gap.
--------------------------------------------------------------------------- */
function heroPill() {
  const pill = document.getElementById("heropill");
  if (!pill) return;
  if (reduced || !window.gsap || !window.ScrollTrigger) return;

  gsap.timeline({
    scrollTrigger: {
      trigger: ".hero",
      start: "top top",
      end: "bottom top",
      scrub: 0.55,
    },
  })
  .fromTo(pill, {width: "1.2em"}, {width: "6.4em", ease: "power2.inOut", duration: 1})
  .to(pill, {width: "1.2em", ease: "power2.inOut", duration: 1});
}

/* ---- the number that flickers into place -----------------------------------
   Digits cycle at random, settling left to right, so the figure resolves the
   way a mechanical counter would rather than simply counting up. The final
   value is the run's real scan count -- never a number chosen to look good.
--------------------------------------------------------------------------- */
function flickTo(el, value, ms) {
  if (!el) return;
  const target = String(value);
  if (reduced) { el.textContent = target; return; }

  const start = performance.now();
  const settleAt = target.split("").map((_, i) =>
    ms * (0.35 + 0.65 * ((i + 1) / target.length)));

  const frame = now => {
    const t = now - start;
    el.textContent = target.split("").map((ch, i) =>
      t >= settleAt[i] ? ch : String(Math.floor(Math.random() * 10))
    ).join("");
    if (t < ms) requestAnimationFrame(frame);
    else el.textContent = target;
  };
  requestAnimationFrame(frame);
}

/* Restarts a CSS animation that may already have run on this element. Removing
   the class is not enough on its own -- the browser batches style changes, so
   without reading a layout property in between it never notices the class was
   gone and the animation does not replay on the second click. */
function replay(el, cls, ms) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), ms);
}

document.getElementById("chips").addEventListener("click", e => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  let on;
  if (chip.dataset.flag) {          // Pay listed / New this week
    on = flags[chip.dataset.flag];
    flags[chip.dataset.flag] = !on;
  } else {                          // a category
    const cat = chip.dataset.cat;
    on = active.has(cat);
    on ? active.delete(cat) : active.add(cat);
  }
  chip.setAttribute("aria-pressed", String(!on));

  if (!reduced) {
    replay(chip, "pop", 460);
    if (!on) {
      // Ticking a category on: the stamp ring lands and the count reshuffles,
      // the same flicker the headline figures use, so the page has one idea
      // about what a number doing something looks like.
      replay(chip, "stamp", 560);
      const b = chip.querySelector("b");
      flickTo(b, b.textContent, 420);
    }
  }
  render(true);
});
/* The counts on the two extra chips, worked out from the data rather than
   written down, so they can never drift from what the filters actually do. */
document.getElementById("npaid").textContent =
  JOBS.filter(j => j.pay).length;
document.getElementById("nnew").textContent =
  JOBS.filter(j => j.age >= 0 && j.age <= NEW_WITHIN).length;

q.addEventListener("input", () => { syncControls(); render(false); });
sortBy.addEventListener("change", () => render(true));
document.getElementById("clrq").addEventListener("click", () => {
  q.value = ""; syncControls(); render(true); q.focus();
});
clearAll.addEventListener("click", clearEverything);
document.getElementById("emptyclear").addEventListener("click", clearEverything);

/* "/" jumps to the search box and Escape gets you out of it -- the two
   shortcuts people already expect from every search field on the web. */
addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "/" && !typing) { e.preventDefault(); q.focus(); q.select(); }
  else if (e.key === "Escape" && document.activeElement === q) {
    q.value = ""; syncControls(); render(true); q.blur();
  }
});

readUrl();
syncControls();
render(true);
flickTo(document.getElementById("bignum"), JOBS.length, 1000);
flickTo(document.getElementById("scanned"), SCANNED, 1400);

/* ---- the opening scene ------------------------------------------------------
   A berry with a lit fuse, drawn in WebGL. Scroll burns the fuse down the stem,
   the bunch goes up, and the headline arrives with the blast.

   Two things worth knowing about how it is wired:

   - It renders ONLY while the section is on screen. A WebGL loop running behind
     forty job cards for the rest of the page is a flat battery for nothing, so
     an IntersectionObserver stops the loop the moment the section leaves.
   - Scroll progress is smoothed toward its target rather than read raw, which
     is what stops the flame juddering on a trackpad.
--------------------------------------------------------------------------- */
function berryScene() {
  const section = document.getElementById("berry");
  if (!section) return;
  const canvas = document.getElementById("berrycanvas");
  const lines = [...section.querySelectorAll(".bl")];
  const hint = document.getElementById("bhint");

  const showAll = () => {
    section.classList.add("flat");
    lines.forEach(l => l.classList.add("on"));
  };
  if (reduced || !window.THREE) { showAll(); return; }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({canvas, antialias: true});
  } catch (e) { showAll(); return; }          // no WebGL on this machine
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

  const bg = 0x100c11;                        // the page's own background
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(bg);
  scene.fog = new THREE.Fog(bg, 14, 26);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 11);

  const fit = () => {
    const w = section.clientWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  fit();
  addEventListener("resize", fit);

  scene.add(new THREE.AmbientLight(0x404040, .55));
  const key = new THREE.DirectionalLight(0xfff2e0, 1.1); key.position.set(4, 6, 6);
  const rim = new THREE.DirectionalLight(0xff5c8a, .8);  rim.position.set(-5, -2, 4);
  const glow = new THREE.PointLight(0xff5c8a, 2, 20);    glow.position.set(0, -4.5, 1);
  scene.add(key, rim, glow);

  // seeded, so the bunch is the same shape on every load rather than a
  // different arrangement each time someone opens the page
  const rng = seed => () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  const R = rng(1337);
  const cl = (v, a, b) => Math.min(b, Math.max(a, v));
  const ez = t => t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

  function softTex(inner, outer) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const x = c.getContext("2d");
    const g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, inner); g.addColorStop(.35, outer);
    g.addColorStop(1, "rgba(0,0,0,0)");
    x.fillStyle = g; x.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  const skin = new THREE.MeshStandardMaterial({color: 0x2a1f33, roughness: .25, metalness: .1, transparent: true});
  const shardMat = new THREE.MeshStandardMaterial({color: 0x241d2c, roughness: .3, metalness: .15, transparent: true});
  const shardGlow = new THREE.MeshStandardMaterial({color: 0xff5c8a, emissive: 0xff5c8a, emissiveIntensity: 1.4, roughness: .4, transparent: true});

  /* the bunch */
  const GR = .52, grapePos = [[0, 1.1, 0]];
  [{y: .35, r: 1.15, n: 7}, {y: -.45, r: 1.35, n: 9},
   {y: -1.25, r: 1.0, n: 7}, {y: -1.95, r: .6, n: 4}].forEach((t, ti) => {
    for (let i = 0; i < t.n; i++) {
      const a = i / t.n * Math.PI * 2 + ti * .45;
      grapePos.push([Math.cos(a) * t.r + (R() - .5) * .08,
                     t.y * .95 + (R() - .5) * .1,
                     Math.sin(a) * t.r * .75 + (R() - .5) * .08]);
    }
  });
  grapePos.push([0, -2.65, 0]);

  const grapes = [];
  const coneGeo = new THREE.ConeGeometry(.15, .32, 4);
  const tetraGeo = new THREE.TetrahedronGeometry(.16);
  grapePos.forEach(p => {
    const g = new THREE.Group(); g.position.set(...p); scene.add(g);
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(GR, 24, 18), skin.clone());
    g.add(sphere);
    const shards = [];
    for (let i = 0, n = 5 + (R() * 3 | 0); i < n; i++) {
      const m = new THREE.Mesh(R() > .75 ? coneGeo : tetraGeo,
                               (R() > .8 ? shardGlow : shardMat).clone());
      const dir = new THREE.Vector3(R() - .5, R() - .5, R() - .5).normalize();
      m.position.copy(dir.clone().multiplyScalar(.4));
      m.lookAt(dir.clone().multiplyScalar(3));
      m.scale.setScalar(0);
      m.userData = {dir: dir.clone().add(new THREE.Vector3((R() - .5) * .6, (R() - .5) * .6, (R() - .5) * .3)).normalize(),
                    far: 4 + R() * 7,
                    rotAxis: new THREE.Vector3(R() - .5, R() - .5, R() - .5).normalize(),
                    rotSpd: (R() - .5) * 8};
      g.add(m); shards.push(m);
    }
    grapes.push({g, sphere, shards,
      burstDir: new THREE.Vector3(p[0] * 1.2, p[1] * .8 + .6, p[2] * 1.2).normalize().multiplyScalar(.9 + R() * 1.6),
      stagger: R() * .22, ox: p[0], oy: p[1], oz: p[2]});
  });

  /* the stem, which is also the fuse */
  const SEG = 26, TOP = 2.75, BOT = 0.55;
  const fuseGroup = new THREE.Group(); scene.add(fuseGroup);
  const segH = (TOP - BOT) / SEG;
  const stemX = y => Math.sin((y - BOT) / (TOP - BOT) * Math.PI) * .22;
  const stemZ = y => Math.cos((y - BOT) / (TOP - BOT) * Math.PI * 2) * .1;

  const woodPieces = [];
  function wood(geo, x, y, z, rz) {
    const mat = new THREE.MeshStandardMaterial({color: 0x5a4a35, roughness: .95, transparent: true});
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y, z);
    if (rz) m.rotation.z = rz;
    fuseGroup.add(m);
    woodPieces.push({m, mat, home: new THREE.Vector3(x, y, z)});
    return m;
  }
  const fuseSegs = [];
  for (let i = 0; i < SEG; i++) {
    const y = TOP - (i + .5) * segH, t = i / SEG;
    const rr = .085 * (1 - t * .35) * (1 + (R() - .5) * .12);
    const m = wood(new THREE.CylinderGeometry(rr * .92, rr, segH * 1.08, 9),
                   stemX(y), y, stemZ(y),
                   -(stemX(y + segH / 2) - stemX(y - segH / 2)) / segH);
    if (i % 3 === 0) m.material.color.setHex(0x443724);
    fuseSegs.push({y, charred: false, piece: woodPieces[woodPieces.length - 1]});
  }
  wood(new THREE.CylinderGeometry(.05, .1, .3, 8), stemX(BOT), BOT - .1, stemZ(BOT), 0);

  /* flame, sparks, ash */
  const fmat = o => new THREE.SpriteMaterial({map: softTex(...o),
    blending: THREE.AdditiveBlending, depthWrite: false, transparent: true});
  const fOuter = new THREE.Sprite(fmat(["rgba(255,120,20,.9)", "rgba(255,60,0,.4)"]));
  const fMid = new THREE.Sprite(fmat(["rgba(255,210,80,.95)", "rgba(255,120,20,.5)"]));
  const fCore = new THREE.Sprite(fmat(["rgba(255,255,230,1)", "rgba(255,200,90,.7)"]));
  fuseGroup.add(fOuter, fMid, fCore);
  const burnLight = new THREE.PointLight(0xff7030, 0, 7); fuseGroup.add(burnLight);

  const sparks = [], sparkGeo = new THREE.SphereGeometry(.02, 5, 4);
  const sparkMat = new THREE.MeshBasicMaterial({color: 0xffb060, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false});
  for (let i = 0; i < 26; i++) {
    const m = new THREE.Mesh(sparkGeo, sparkMat.clone());
    m.visible = false; fuseGroup.add(m); sparks.push(m);
  }
  const ashMat = new THREE.MeshStandardMaterial({color: 0x171310, roughness: 1, transparent: true});
  const ash = [], ashGeo = new THREE.TetrahedronGeometry(.045);
  for (let i = 0; i < 40; i++) {
    const m = new THREE.Mesh(ashGeo, ashMat.clone());
    m.visible = false; fuseGroup.add(m); ash.push(m);
  }

  /* leaves: painted on a canvas, so their colour never depends on the lighting */
  const leafGroup = new THREE.Group();
  const ATT_Y = 2.35;
  leafGroup.position.set(stemX(ATT_Y), ATT_Y, stemZ(ATT_Y));
  leafGroup.rotation.set(.12, -.4, .1);
  scene.add(leafGroup);
  const leafMat = new THREE.MeshBasicMaterial({transparent: true, side: THREE.DoubleSide, depthWrite: false});

  (function paintLeaf() {
    const S = 512, c = document.createElement("canvas"); c.width = c.height = S;
    const x = c.getContext("2d"), LEN = 478, WID = 132;
    x.save(); x.translate(S / 2, 498);
    const N = 96;
    const hw = t => WID * Math.pow(Math.sin(Math.PI * Math.pow(t, .80)), 1.22) * (1 - .22 * t);
    const edge = [];
    for (let i = 0; i <= N; i++) { const t = i / N, k = (i % 2) ? 1.045 : .988; edge.push([-hw(t) * k, -t * LEN]); }
    for (let i = N; i >= 0; i--) { const t = i / N, k = (i % 2) ? 1.045 : .988; edge.push([hw(t) * k, -t * LEN]); }
    const trace = () => { x.beginPath(); x.moveTo(edge[0][0], edge[0][1]);
      edge.forEach(p => x.lineTo(p[0], p[1])); x.closePath(); };
    trace();
    const g = x.createLinearGradient(0, 0, 0, -LEN);
    g.addColorStop(0, "#6f9c34"); g.addColorStop(.35, "#8bb944");
    g.addColorStop(.72, "#a3cc55"); g.addColorStop(1, "#c0dd77");
    x.fillStyle = g; x.fill();
    x.save(); x.clip();
    const sh = x.createLinearGradient(-WID, 0, WID, 0);
    sh.addColorStop(0, "rgba(40,70,20,.30)"); sh.addColorStop(.45, "rgba(40,70,20,0)");
    sh.addColorStop(.80, "rgba(255,255,220,.10)"); sh.addColorStop(1, "rgba(255,255,220,.20)");
    x.fillStyle = sh; x.fillRect(-WID * 1.3, -LEN - 10, WID * 2.6, LEN + 30);
    x.lineCap = "round";
    for (let i = 1; i <= 10; i++) {
      const t = i / 11, y = -t * LEN, w = hw(t);
      x.lineWidth = 3.2 * (1 - t * .55);
      x.strokeStyle = "rgba(206,228,132,.75)";
      [-1, 1].forEach(sd => { x.beginPath(); x.moveTo(0, y + 26);
        x.quadraticCurveTo(sd * w * .45, y - 6, sd * w * .93, y - 30 * (1 - t * .4)); x.stroke(); });
    }
    x.lineWidth = 9; x.strokeStyle = "rgba(214,234,144,.90)";
    x.beginPath(); x.moveTo(0, 4); x.quadraticCurveTo(-2, -LEN * .5, 0, -LEN + 6); x.stroke();
    x.lineWidth = 4; x.strokeStyle = "rgba(238,248,190,.75)";
    x.beginPath(); x.moveTo(0, 4); x.quadraticCurveTo(-2, -LEN * .5, 0, -LEN + 6); x.stroke();
    const gl = x.createRadialGradient(-WID * .30, -LEN * .62, 10, -WID * .30, -LEN * .62, WID * 1.5);
    gl.addColorStop(0, "rgba(255,255,235,.22)"); gl.addColorStop(1, "rgba(255,255,235,0)");
    x.fillStyle = gl; x.fillRect(-WID * 1.3, -LEN - 10, WID * 2.6, LEN + 30);
    x.restore();
    trace(); x.lineWidth = 3; x.strokeStyle = "rgba(64,102,28,.55)"; x.stroke();
    x.restore();
    leafMat.map = new THREE.CanvasTexture(c);
  })();

  function leaf(len, tiltX, tiltZ, z) {
    const g = new THREE.Group();
    const geo = new THREE.PlaneGeometry(len * .78, len);
    geo.translate(0, len / 2, 0);
    const m = new THREE.Mesh(geo, leafMat);
    m.rotation.x = tiltX; g.add(m);
    g.rotation.z = tiltZ; g.position.z = z;
    return g;
  }
  leafGroup.add(leaf(2.2, -.25, 0.0, .05), leaf(1.9, -.15, 1.05, .12),
                leaf(1.6, -.3, -0.75, -.08), leaf(1.8, .45, 2.5, .02));

  /* the blast */
  const boomAt = new THREE.Vector3(0, -0.8, 0);
  const sprite = o => { const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: softTex(...o),
      blending: THREE.AdditiveBlending, depthWrite: false, transparent: true}));
    sp.scale.setScalar(0); sp.position.copy(boomAt); scene.add(sp); return sp; };
  const flash = sprite(["rgba(255,255,240,1)", "rgba(255,92,138,.55)"]);
  const pressure = sprite(["rgba(255,92,138,.5)", "rgba(120,20,60,.25)"]);
  const embers = [], emberGeo = new THREE.TetrahedronGeometry(.07);
  for (let i = 0; i < 50; i++) {
    const m = new THREE.Mesh(emberGeo, new THREE.MeshBasicMaterial({
      color: R() > .5 ? 0xff5c8a : 0xffa8c6, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false}));
    m.visible = false;
    m.userData = {dir: new THREE.Vector3(R() - .5, R() - .5, R() - .5).normalize(),
      spd: 4 + R() * 7, life: 0, max: .6 + R() * .5,
      rotAxis: new THREE.Vector3(R() - .5, R() - .5, R() - .5).normalize()};
    scene.add(m); embers.push(m);
  }
  const boomLight = new THREE.PointLight(0xff5c8a, 0, 25);
  boomLight.position.copy(boomAt); scene.add(boomLight);

  const core = new THREE.Mesh(new THREE.SphereGeometry(.35, 24, 18),
    new THREE.MeshStandardMaterial({color: 0xff5c8a, emissive: 0xff5c8a,
      emissiveIntensity: 2.5, roughness: .3}));
  core.scale.setScalar(0); scene.add(core);
  const coreLight = new THREE.PointLight(0xff5c8a, 0, 15); scene.add(coreLight);

  /* ---- the loop ---- */
  const BURN_A = .15, BURN_B = .50;
  let cur = 0, running = false, raf = 0;

  new IntersectionObserver(es => {
    const on = es[0].isIntersecting;
    if (on && !running) { running = true; raf = requestAnimationFrame(frame); }
    else if (!on && running) { running = false; cancelAnimationFrame(raf); }
  }, {rootMargin: "100px"}).observe(section);

  function frame(ms) {
    if (!running) return;
    const time = ms * .001;
    const r = section.getBoundingClientRect();
    const target = cl(-r.top / (r.height - innerHeight), 0, 1);
    cur += (target - cur) * .08;                  // smoothed, or the flame judders
    const p = cur, floatY = Math.sin(time * .8) * .1;

    lines.forEach(l => l.classList.toggle("on", p >= +l.dataset.at));
    if (hint) hint.style.opacity = p > .06 ? 0 : .75;

    /* fuse */
    const burn = ez(cl((p - BURN_A) / (BURN_B - BURN_A), 0, 1));
    const lit = burn > 0 && burn < 1;
    const by = TOP - burn * (TOP - BOT), bx = stemX(by), bz = stemZ(by);
    fOuter.visible = fMid.visible = fCore.visible = lit;
    if (lit) {
      const j = () => (Math.random() - .5) * .08, fl = Math.min(.22, burn * .22);
      fOuter.position.set(bx + j(), by + .12 + fl * .4, bz + j());
      fMid.position.copy(fOuter.position); fCore.position.copy(fOuter.position);
      fOuter.scale.setScalar(.9 + fl * 3 + Math.sin(time * 22) * .12);
      fMid.scale.setScalar(.55 + fl * 2 + Math.sin(time * 31) * .08);
      fCore.scale.setScalar(.28 + fl * 1.2 + Math.sin(time * 44) * .05);
      burnLight.position.set(bx, by + .15, bz);
      burnLight.intensity = 3 + Math.sin(time * 27) * .8;
      if (Math.random() < .5) {
        let n = 3;
        for (const sp of sparks) {
          if (n <= 0) break;
          if (sp.visible) continue;
          n--; sp.visible = true;
          sp.position.set(bx + (R() - .5) * .1, by + (R() - .5) * .1, bz + (R() - .5) * .1);
          sp.userData = {vx: (R() - .5) * 1.4, vy: 1 + R() * 1.6, vz: (R() - .5) * 1.4,
                         life: 0, max: .4 + R() * .5};
        }
      }
    } else burnLight.intensity = 0;

    fuseSegs.forEach(sg => {
      if (by < sg.y && !sg.charred) {
        sg.charred = true;
        sg.piece.mat.color.setHex(0x171310);
        sg.piece.mat.roughness = 1;
        if (Math.random() < .5) {
          const a = ash.find(x => !x.visible);
          if (a) { a.visible = true;
            a.position.set(stemX(sg.y) + (R() - .5) * .1, sg.y, stemZ(sg.y) + (R() - .5) * .1);
            a.userData = {vy: -.5 - R(), vx: (R() - .5) * .6, t: 0, rot: (R() - .5) * 6}; }
        }
      }
      if (sg.charred && lit && sg.y < by + .25) {
        sg.piece.mat.emissive = new THREE.Color(0xff4400);
        sg.piece.mat.emissiveIntensity = Math.random() * .35;
      }
    });

    sparks.forEach(sp => {
      if (!sp.visible) return;
      const u = sp.userData; u.life += .016;
      sp.position.x += u.vx * .016; sp.position.y += u.vy * .016; sp.position.z += u.vz * .016;
      u.vy -= 2.5 * .016;
      sp.material.opacity = 1 - u.life / u.max;
      if (u.life > u.max) sp.visible = false;
    });
    ash.forEach(a => {
      if (!a.visible) return;
      const u = a.userData; u.t += .016;
      a.position.y += u.vy * .016; a.position.x += u.vx * .016;
      a.rotation.x += u.rot * .02;
      if (u.t > 1.6) a.visible = false;
    });

    /* the blast */
    const bp = cl((p - .5) / .2, 0, 1);
    if (bp > 0 && bp < 1) {
      const fp = cl(bp / .3, 0, 1);
      flash.material.opacity = (1 - fp) * .95;
      flash.scale.setScalar(.5 + ez(fp) * 8);
      pressure.material.opacity = (1 - bp) * .5;
      pressure.scale.setScalar(1 + ez(bp) * 9);
      if (bp < .05 && Math.random() < .8) {
        const m = embers.find(e => !e.visible);
        if (m) { m.visible = true; m.position.copy(boomAt); m.userData.life = 0; }
      }
      boomLight.intensity = (1 - bp) * 14;
    } else {
      flash.material.opacity = 0; pressure.material.opacity = 0; boomLight.intensity = 0;
    }
    embers.forEach(e => {
      if (!e.visible) return;
      const u = e.userData; u.life += .016;
      const d = ez(cl(u.life / u.max, 0, 1));
      e.position.copy(boomAt).addScaledVector(u.dir, u.spd * d);
      e.rotateOnAxis(u.rotAxis, .2);
      e.material.opacity = 1 - d;
      if (d >= 1) e.visible = false;
    });

    /* the stem comes apart */
    if (p > .5) {
      const dg = cl((p - .5) / .28, 0, 1);
      woodPieces.forEach((wp, i) => {
        if (p > .82) { wp.m.visible = false; return; }
        const local = ez(cl((dg - i * .012) / .6, 0, 1));
        if (local <= 0) return;
        if (!wp.m.userData.broken && local > .02) {
          wp.m.userData.broken = true;
          wp.fallDir = new THREE.Vector3((R() - .5) * 2.4, -.4 - R() * 1.2, (R() - .5) * 2.4).normalize();
          wp.fallSpin = new THREE.Vector3(R() - .5, R() - .5, R() - .5).normalize();
          wp.fallSpd = (R() - .5) * 6;
        }
        if (wp.fallDir) {
          wp.m.position.copy(wp.home).addScaledVector(wp.fallDir, local * 3);
          wp.m.rotateOnAxis(wp.fallSpin, wp.fallSpd * local * .1);
        }
        wp.mat.opacity = 1 - local;
        wp.m.visible = local < 1;
      });
    }

    /* leaves go with the stick */
    const lf = cl((p - .45) / .34, 0, 1);
    leafMat.opacity = 1 - ez(lf);
    if (p > .82) leafGroup.visible = false;
    else {
      leafGroup.visible = leafMat.opacity > .02;
      leafGroup.rotation.z = .1 + ez(lf) * .6;
      leafGroup.position.y = ATT_Y - ez(lf) * .3;
    }

    /* the bunch bursts */
    grapes.forEach(gr => {
      const gt = ez(cl((p - .5 - gr.stagger) / .28, 0, 1));
      const seam = cl((p - .45 - gr.stagger) / .05, 0, 1);
      gr.sphere.scale.setScalar((1 + seam * .08) * (1 - gt));
      gr.sphere.material.opacity = 1 - gt;
      gr.sphere.visible = gt < 1;
      gr.g.position.set(gr.ox + gr.burstDir.x * gt,
                        gr.oy + gr.burstDir.y * gt + floatY * (1 - gt),
                        gr.oz + gr.burstDir.z * gt);
      gr.shards.forEach(m => {
        const st = ez(cl(gt * 1.4 - .15, 0, 1));
        m.scale.setScalar(st < 0 ? 0 : Math.min(1, st * 3) * (1 - st * .3));
        const d = m.userData;
        m.position.copy(d.dir).multiplyScalar(.4 + d.far * st);
        m.rotateOnAxis(d.rotAxis, d.rotSpd * st * .05);
        m.material.opacity = 1 - cl((st - .85) / .15, 0, 1);
      });
    });

    /* what is left */
    const ct = ez(cl((p - .86) / .12, 0, 1));
    core.scale.setScalar(ct * (1 + Math.sin(time * 3) * .05));
    core.position.y = floatY;
    coreLight.intensity = ct * 3;

    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }
}

/* ---- the featured role -----------------------------------------------------
   One scrubbed timeline: scroll position is the playhead, so scrolling back up
   takes the card apart in reverse. Everything is opacity and transform, which
   the compositor handles on its own -- a 200vh scrub that touched layout would
   stutter on a phone.

   With no GSAP, or for anyone who asked for less motion, .flat collapses the
   whole section to a single screen with the card already assembled, rather
   than leaving 200vh of nothing.
--------------------------------------------------------------------------- */
function featured() {
  const stage = document.getElementById("stage");
  if (!stage) return;
  stage.classList.add("flat");
  const t = document.getElementById("ptxt");
  if (t) t.textContent = "Featured role";
  return;
  if (reduced || !window.gsap || !window.ScrollTrigger) {
    stage.classList.add("flat");
    const t2 = document.getElementById("ptxt");
    if (t2) t2.remove();
    return;
  }

  const tl = gsap.timeline({
    scrollTrigger: {trigger: stage, start: "top top", end: "bottom bottom",
                    scrub: .5},
  });
  tl.from("#plogo",   {scale: .2, opacity: 0, rotate: -25, duration: .5})
    .from("#pcard h2",{y: 40, opacity: 0, duration: .5}, "-=0.25")
    .from("#pcard .pco",{y: 20, opacity: 0, duration: .4}, "-=0.35")
    // fromTo, not to-plus-a-set: a set written after the timeline is a race
    // with the timeline's first render, and whichever wins decides whether
    // the tags move at all. Stating both ends removes the question.
    .fromTo(".ptag",   {x: -24, opacity: 0},
                       {x: 0, opacity: 1, duration: .42,
                        stagger: .09, ease: "power2.out"}, "-=0.2")
    .fromTo("#papply", {scale: .6, opacity: 0},
                       {scale: 1, opacity: 1, duration: .5}, "-=0.15")
    // hold: the assembled card gets the last third of the scroll to itself,
    // otherwise it finishes on the final pixel and is gone before it reads
    .to({}, {duration: .5});

  // the rail fills across the whole section, independent of the beats above
  gsap.timeline({scrollTrigger: {trigger: stage, start: "top top",
                                 end: "bottom bottom", scrub: .5}})
      .to("#prail", {opacity: 1, duration: .1})
      .fromTo("#prail i", {scaleY: 0}, {scaleY: 1, duration: 1, ease: "none"}, 0);

  // a slight tilt and float, so the card reads as an object rather than a div
  const card = document.getElementById("pcard"), txt = document.getElementById("ptxt");
  ScrollTrigger.create({
    trigger: stage, start: "top top", end: "bottom bottom",
    onUpdate: self => {
      const p = self.progress;
      card.style.transform =
        `perspective(900px) rotateX(${(1 - p) * 4}deg) ` +
        `translateY(${Math.sin(p * Math.PI) * -14}px)`;
      txt.textContent = p > .97 ? "Tap to apply"
                                : `Featured role — ${Math.round(p * 100)}%`;
    },
  });
}
featured();





</script>
</body></html>"""


def pick_featured(rows, index):
    """The role that gets the whole screen.

    Newest first, but only among employers we can actually put a real logo
    against -- a full-width card with an initials tile for a company nobody
    has heard of is worse than no card at all. Falls back to anything with a
    logo, then to the newest listing, so it always returns something.
    """
    if not rows:
        return None
    branded = [r for r in rows if r.get("company") and r.get("logo")]
    pick = (branded or [r for r in rows if r.get("logo")] or rows)[0]
    return pick


def featured_tokens(pick, index):
    """The handful of @@FEAT...@@ values the card is built from."""
    if not pick:
        return {"@@FEATIDX@@": "0", "@@FEATLOGO@@": "", "@@FEATTITLE@@": "",
                "@@FEATCO@@": "", "@@FEATTAGS@@": "", "@@FEATURL@@": "#",
                "@@FEATCTA@@": "View the listing"}
    e = html.escape
    company = pick.get("company") or pick["category"]
    logo = (f'<img src="{e(pick["logo"])}" alt="" loading="lazy">'
            if pick.get("logo")
            else f'<span class="initials">{e(_initials(company))}</span>')

    age = pick.get("age", -1)
    posted = ("Posted today" if age == 0 else
              "Posted yesterday" if age == 1 else
              f"Posted {age} days ago" if age > 1 else "")
    where = "Seek" if "seek" in (pick.get("url") or "") else \
            "LinkedIn" if "linkedin" in (pick.get("url") or "") else ""
    tags = []
    if pick.get("pay"):
        tags.append(f'<span class="ptag pay">{e(pick["pay"])}</span>')
    if pick.get("work_type"):
        tags.append(f'<span class="ptag">{e(pick["work_type"])}</span>')
    tags.append(f'<span class="ptag">{e(pick["category"])}</span>')
    if posted:
        tags.append(f'<span class="ptag">{e(posted)}'
                    f'{" &middot; via " + where if where else ""}</span>')

    return {
        "@@FEATIDX@@": str(index.get(pick["category"], 0)),
        "@@FEATLOGO@@": logo,
        "@@FEATTITLE@@": e(pick["title"]),
        "@@FEATCO@@": e(company) + " &middot; " + e(pick.get("location", "Sydney NSW")),
        "@@FEATTAGS@@": "".join(tags),
        "@@FEATURL@@": e(pick.get("url") or "#"),
        "@@FEATCTA@@": f"View on {where}" if where else "View the listing",
    }


def _initials(name):
    """Same two letters the cards use, for the one case the featured card
    has no logo to show."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "")
             if w and not w.isdigit()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def build(rows, dropped=None):
    cats = sorted({r["category"] for r in rows})
    counts = {c: sum(1 for r in rows if r["category"] == c) for c in cats}
    index = {c: i for i, c in enumerate(cats)}

    chips = "".join(
        f'<button class="chip c-{index[c]}" data-cat="{html.escape(c)}">'
        '<span class="tick" aria-hidden="true"><svg viewBox="0 0 16 16">'
        '<circle class="tk-ring" cx="8" cy="8" r="7"/>'
        '<rect class="tk-box" x="1.5" y="1.5" width="13" height="13" rx="6.5"/>'
        '<path class="tk-mark" d="M4.4 8.3 L6.9 10.8 L11.6 5.4"/>'
        '</svg></span>'
        f'{html.escape(c)}<b>{counts[c]}</b></button>' for c in cats)
    stats = "".join(
        f'<div class="stat c-{index[c]}"><b>{counts[c]}</b>{html.escape(c)}</div>'
        for c in cats)

    dropped = dropped or {}
    scanned = len(rows) + sum(dropped.values())

    out = TEMPLATE
    for token, value in {
        "@@IG@@": INSTAGRAM,
        "@@HANDLE@@": "@" + ACCOUNT,
        "@@UPDATED@@": datetime.now().strftime("%-d %b %Y"),
        "@@TOTAL@@": str(len(rows)),
        "@@STATS@@": stats,
        "@@CHIPS@@": chips,
        "@@JOBS@@": json.dumps(rows, ensure_ascii=False),
        "@@CATINDEX@@": json.dumps(index, ensure_ascii=False),
        "@@NEWWITHIN@@": str(NEW_WITHIN_DAYS),
        "@@SCANNED@@": str(scanned),
        "@@BIGFLIGHT@@": "M18 120 C 96 114, 176 98, 250 74 S 356 34, 398 14",
        **featured_tokens(pick_featured(rows, index), index),
    }.items():
        out = out.replace(token, value)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="write the file without opening a browser")
    args = ap.parse_args()

    rows, dropped = collect()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build(rows, dropped))

    print(f"{len(rows)} internship(s) on the site")
    for why, n in dropped.items():
        if n:
            print(f"  left off: {n} {why}")
    if not load_dead_listings():
        print("\n  note: check_live.py hasn't run, so no listing has been "
              "confirmed closed yet.\n        Run it to drop the ones that "
              "have been filled.")
    print(f"\nWrote: {OUT}")
    if not args.quiet:
        webbrowser.open("file://" + OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
