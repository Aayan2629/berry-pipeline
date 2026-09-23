#!/usr/bin/env python3
"""
get_category_photos.py -- 10 fresh photos per category (30 total) from Unsplash,
each sorted into its own folder so the covers match the category.

    python3 get_category_photos.py              10 per category
    python3 get_category_photos.py --per-cat 15 more

Where they go:
    background pics/tech/          Technology, Data & AI
    background pics/finance/       Business, Commerce, Marketing & Finance
    background pics/engineering/   Engineering

poster_template.py picks from the category folder first, and rotates: the
photo used longest ago always goes next, so nothing repeats until the whole
folder has been used.

Licence: Unsplash photos are free for commercial use, no attribution needed
(https://unsplash.com/license). This uses the same search more_backgrounds.py
uses -- it has to run on your Mac, the sandbox can't reach Unsplash.

QUALITY CHECK (plain maths, no AI): every download is opened with Pillow and
thrown away if it is
    * black and white   (average colour saturation too low)
    * too dark          (white text needs something to sit on)
    * too bright/blown  (white text disappears)
"""
import argparse, io, os, sys, time
from PIL import Image, ImageStat

# reuse the search + download helpers that already work in more_backgrounds.py
from more_backgrounds import search, _get, OUT

QUERIES = {
    "tech": ["laptop code screen desk", "developer workspace bright",
             "data dashboard screen", "tech office modern bright",
             "server room blue light", "coding laptop coffee"],
    "finance": ["sydney cbd office building", "modern office meeting room bright",
                "city skyline glass towers", "business desk documents bright",
                "coworking space sunny", "sydney harbour morning"],
    "engineering": ["engineering blueprint desk", "construction site crane sky",
                    "hard hat safety helmet", "bridge structure steel",
                    "workshop tools bench", "architecture model desk"],
}


def good_enough(blob):
    """True if the photo passes the brightness/colour check.
    ImageStat gives averages per channel -- like mean() in R."""
    img = Image.open(io.BytesIO(blob)).convert("RGB").resize((200, 200))
    brightness = ImageStat.Stat(img.convert("L")).mean[0]          # 0 black .. 255 white
    saturation = ImageStat.Stat(img.convert("HSV")).mean[1]        # 0 grey .. 255 vivid
    if saturation < 35:
        return False, f"black & white-ish (sat {saturation:.0f})"
    if brightness < 60:
        return False, f"too dark ({brightness:.0f})"
    if brightness > 215:
        return False, f"too bright ({brightness:.0f})"
    return True, f"ok (bright {brightness:.0f}, sat {saturation:.0f})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cat", type=int, default=10)
    args = ap.parse_args()

    for cat, queries in QUERIES.items():
        folder = os.path.join(OUT, cat)
        os.makedirs(folder, exist_ok=True)
        have = len([f for f in os.listdir(folder) if f.lower().endswith(".jpg")])
        print(f"\n== {cat}: {have} already")
        for q in queries:
            if have >= args.per_cat:
                break
            try:
                hits = search(q, 6)
            except Exception as e:
                print(f"  ! search '{q}' failed: {e}")
                continue
            for pid, url in hits:
                if have >= args.per_cat:
                    break
                dest = os.path.join(folder, f"unsplash_{pid}.jpg")
                if os.path.exists(dest):
                    continue
                try:
                    blob = _get(url)
                except Exception as e:
                    print(f"  ! {pid}: {e}")
                    continue
                ok, why = good_enough(blob)
                if not ok:
                    print(f"  - skip {pid}: {why}")
                    continue
                with open(dest, "wb") as f:
                    f.write(blob)
                have += 1
                print(f"  + {cat}/unsplash_{pid}.jpg  {why}   [{have}/{args.per_cat}]")
                time.sleep(0.5)          # be polite
    print("\nDone. Look through the folders and delete any you don't like --")
    print("rotation only ever uses what's in there.")


if __name__ == "__main__":
    sys.exit(main())
