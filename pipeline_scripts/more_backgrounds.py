#!/usr/bin/env python3
"""
more_backgrounds.py -- pull fresh, brighter photos into "background pics/".

    python3 more_backgrounds.py                       the default searches
    python3 more_backgrounds.py "sunlit cafe laptop"  your own search
    python3 more_backgrounds.py --per 8               how many per search
    python3 more_backgrounds.py --list                what you already have

WHY THIS EXISTS SEPARATELY FROM get_backgrounds.py

get_backgrounds.py downloads a fixed list of fifteen photo IDs I read off
Unsplash by hand. It works, but the list can never grow, and half of those
fifteen are shot moody -- one of them is black and white, which is why some
covers come out grey no matter what the code does to them.

This one SEARCHES instead, so you can go and get whatever you actually want.

IT HAS TO RUN ON YOUR MAC. Unsplash is blocked from the sandbox I work in,
which is also why I could not just pick better photos for you myself.

LICENSING

Everything here comes from Unsplash. The Unsplash License allows free
commercial use, including on a monetised account, with no attribution and no
payment. Photos off Google Images are not safe to post and this deliberately
cannot fetch them.
    https://unsplash.com/license

A NOTE ON WHAT TO SEARCH FOR

The slides put a white card over the middle of the photo, so what reads is
the top and bottom edges. Photos that work: bright, one clear subject, plenty
of empty surface. Photos that do not: busy, dark, or with a face in the
middle. "sunlit" and "bright" in the query do most of the work.
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "background pics")

# Deliberately biased towards light: the old set was mostly evening desks.
# 16 queries x the default --per (6) = ~96 in one bare run -- enough variety
# that the carousels stop visibly repeating the same handful of photos.
DEFAULT_QUERIES = [
    # The house look: bright, warm, uncluttered. Slides sit a tint of 0.14
    # over these and then put text on top, so anything busy or high-contrast
    # fights the words. Prefer soft light, plain surfaces, shallow depth.

    # --- desks and workspaces -------------------------------------------
    "bright sunlit desk laptop",
    "minimal white desk notebook",
    "plant desk workspace minimal",
    "desk flowers laptop bright",
    "laptop coffee cup wooden table",
    "clean desk morning sunlight",
    "wooden desk soft shadow",
    "workspace linen neutral tones",
    "minimal home office beige",
    "desk lamp warm light minimal",

    # --- study, library, campus -----------------------------------------
    "university campus sunny",
    "student notebook coffee bright",
    "cozy library reading nook",
    "bookshelf study room bright",
    "open notebook pen desk sunlight",
    "campus courtyard sunny day",
    "library window natural light",
    "study desk books warm light",
    "lecture hall empty bright",
    "campus architecture sunlight",

    # --- cafes ------------------------------------------------------------
    "cafe table laptop morning light",
    "coffee shop laptop working",
    "coffee cup marble table",
    "cafe window seat morning",
    "latte flatlay neutral",

    # --- offices and coworking -------------------------------------------
    "modern office window daylight",
    "coworking space bright window",
    "glass office building sky",
    "office lobby minimal light",
    "meeting room bright empty",

    # --- city and architecture -------------------------------------------
    "sydney harbour morning",
    "sydney skyline sunrise",
    "city skyline soft haze",
    "modern architecture minimal facade",
    "glass tower blue sky",
    "concrete architecture soft light",
    "city street morning light",
    "bridge architecture minimal",

    # --- texture and surface ----------------------------------------------
    "paper texture cream minimal",
    "linen fabric texture neutral",
    "concrete wall soft texture",
    "marble texture white subtle",
    "plaster wall warm neutral",
    "kraft paper texture plain",

    # --- light, gradient, abstract ---------------------------------------
    "soft gradient pastel blur",
    "warm light leak abstract",
    "sunlight through curtain",
    "soft shadow on wall",
    "golden hour light wall",
    "blurred bokeh warm tones",
    "abstract pastel minimal",
    "colour gradient smooth peach",

    # --- calm nature -------------------------------------------------------
    "clear sky soft clouds",
    "pastel sunset sky minimal",
    "calm ocean horizon soft",
    "eucalyptus leaves soft light",
    "minimal landscape muted",
    "sand texture soft light",

    # --- stationery and flatlay --------------------------------------------
    "notebook pen coffee flatlay",
    "stationery flatlay minimal neutral",
    "planner desk flatlay bright",
    "pen paper clean flatlay",
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    # python.org's Python does not use macOS's certificate store, so plain
    # urllib HTTPS fails until "Install Certificates.command" has been run.
    # Falling back to an unverified context for a read-only image search is
    # a fair trade for it working on a fresh machine.
    try:
        return urllib.request.urlopen(req, timeout=25).read()
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=25, context=ctx).read()


def search(query, per):
    """Unsplash's own site search. No API key, because it is the endpoint the
    website itself calls. That also means it is undocumented and could change
    without warning -- if it ever starts returning nothing, the fallback is to
    drop photos into "background pics/" by hand, which works just as well."""
    url = ("https://unsplash.com/napi/search/photos?query="
           + urllib.parse.quote(query) + f"&per_page={per}&orientation=squarish")
    data = json.loads(_get(url))
    out = []
    for r in data.get("results", []):
        raw = (r.get("urls") or {}).get("raw")
        if raw:
            # 1200px square, centre-cropped by Unsplash's own resizer, which
            # is exactly what poster_template.py wants.
            out.append((r["id"], raw + "&w=1200&h=1200&fit=crop&q=80&fm=jpg"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="*", help="what to search for")
    ap.add_argument("--per", type=int, default=6, help="photos per search")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    if args.list:
        names = sorted(f for f in os.listdir(OUT)
                       if f.lower().endswith((".jpg", ".jpeg", ".png")))
        print(f"{len(names)} photos in background pics/")
        for n in names:
            print("  " + n)
        return 0

    queries = args.queries or DEFAULT_QUERIES
    got = skipped = 0
    for q in queries:
        print(f"\n{q}")
        try:
            hits = search(q, args.per)
        except Exception as e:
            print(f"  ! search failed: {e}")
            print("    If this keeps happening, just drag photos you like into")
            print(f"    {OUT}  -- any jpg or png works, nothing else to do.")
            continue
        if not hits:
            print("  (nothing came back)")
        for pid, url in hits:
            dest = os.path.join(OUT, f"unsplash_{pid}.jpg")
            if os.path.exists(dest):
                skipped += 1
                continue
            try:
                blob = _get(url)
                with open(dest, "wb") as f:
                    f.write(blob)
                got += 1
                print(f"  + unsplash_{pid}.jpg  ({len(blob)//1000} KB)")
            except Exception as e:
                print(f"  ! {pid}: {e}")
            time.sleep(0.4)  # be polite to an unofficial, unkeyed endpoint

    print(f"\n{got} new, {skipped} already had.")
    if got:
        print("\nNow rebuild so the new photos actually get used:")
        print("  python3 build_carousels.py --rebuild")
    return 0


if __name__ == "__main__":
    sys.exit(main())
