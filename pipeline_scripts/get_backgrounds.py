#!/usr/bin/env python3
"""
get_backgrounds.py
===================
Downloads background photos for the job posters into "background pics/".

WHY THIS IS A SCRIPT YOU RUN (and not something I just did for you)
------------------------------------------------------------------
Unsplash is blocked from the sandbox I work in, so I couldn't download the
photos myself -- but I could read the photo IDs off Unsplash's pages. Those
IDs are baked in below, and YOUR Mac has normal internet, so running this
fetches the real files in about 30 seconds.

LICENSING
---------
Every photo here is from Unsplash. The Unsplash License allows free
commercial use, including on a monetised Instagram account, with no
attribution required and no payment. That matters because these end up on
a public account -- grabbing images off Google Images instead would not be
safe to post.
    https://unsplash.com/license

WHAT YOU GET
------------
15 photos in the same vein as the Prosple posts you liked: desks, laptops,
libraries, cafes, notebooks, campus. Each is downloaded at 1200x1200,
centre-cropped square, ready for poster_template.py to blur and dim behind
the white card.

HOW TO RUN
----------
    cd ~/Desktop/"job account "/SeekSpider-main/pipeline_scripts
    python3 get_backgrounds.py

Re-running skips anything already downloaded, so it's safe to run again.
"""

import os
import ssl
import urllib.request

# Python installed from python.org doesn't use macOS's certificate store, so
# plain urllib HTTPS fails with CERTIFICATE_VERIFY_FAILED until you run
# "Install Certificates.command" by hand. requests bundles its own CA list
# (via certifi) and just works, so we use it when it's available -- which it
# is, since the scraper already needs it.
try:
    import requests
except ImportError:
    requests = None

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "background pics")

# Real Unsplash photo IDs, read off Unsplash's own search pages.
# name -> photo id
PHOTOS = {
    "desk_laptop_01":      "1554246247-6993b606e8b9",
    "desk_laptop_02":      "1616400619175-5beda3a17896",
    "desk_notebook_03":    "1588091210060-1ee4fab270ae",
    "desk_workspace_04":   "1504292004442-f285299403fa",
    "desk_setup_05":       "1601217817505-8e2cfe5b8419",
    "library_06":          "1520699049698-acd2fccb8cc8",
    "library_07":          "1547743052-3a5fec50cadf",
    "library_08":          "1546953304-5d96f43c2e94",
    "library_09":          "1524995997946-a1c2e315a42f",
    "cafe_laptop_10":      "1534201569625-ed4662d8be97",
    "cafe_laptop_11":      "1553484771-898ed465e931",
    "cafe_work_12":        "1592834827950-bf70bc7a8f4d",
    "notebook_coffee_13":  "1559163499-413811fb2344",
    "notebook_coffee_14":  "1473181488821-2d23949a045a",
    "campus_15":           "1570937943653-7de35201f04b",
}

# w/h/fit/crop ask Unsplash's image server for a square, centre-cropped,
# reasonably sized file rather than the full-resolution original.
URL = ("https://images.unsplash.com/photo-{pid}"
       "?w=1200&h=1200&fit=crop&crop=entropy&q=80&fm=jpg")

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Saving into: {OUT_DIR}\n")

    got, skipped, failed = 0, 0, 0
    for name, pid in PHOTOS.items():
        path = os.path.join(OUT_DIR, f"{name}.jpg")
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            print(f"  = {name}.jpg (already there)")
            skipped += 1
            continue
        try:
            url = URL.format(pid=pid)
            if requests is not None:
                resp = requests.get(url, headers=HEADERS, timeout=40)
                resp.raise_for_status()
                data = resp.content
            else:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=40,
                                            context=_SSL_CONTEXT) as r:
                    data = r.read()
            if len(data) < 10000:
                raise ValueError(f"suspiciously small ({len(data)} bytes)")
            with open(path, "wb") as f:
                f.write(data)
            print(f"  + {name}.jpg  ({len(data)//1024} KB)")
            got += 1
        except Exception as e:
            print(f"  ! {name} failed: {type(e).__name__}: {str(e)[:70]}")
            failed += 1

    print(f"\nDownloaded {got}, already had {skipped}, failed {failed}.")
    print(f"Total photos in folder: "
          f"{len([f for f in os.listdir(OUT_DIR) if f.lower().endswith(('.jpg','.jpeg','.png'))])}")
    print("\nThese are used automatically the next time you run:")
    print("    python3 build_posts.py --rebuild")


if __name__ == "__main__":
    main()
