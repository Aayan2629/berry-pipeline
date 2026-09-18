#!/usr/bin/env python3
"""
refresh.py -- the weekly run. One command, five steps, in order.

    python3 refresh.py              everything
    python3 refresh.py --fast       Seek only, skip the slow boards
    python3 refresh.py --no-check   skip the still-open check

    1. Seek            scrapers/seek.py           ~3 min
    2. LinkedIn etc.   scrapers/other_boards.py   ~5 min
    3. still open?     check_live.py          ~1 min
    4. THE WEBSITE     build_site.py          seconds
    5. the carousels   build_carousels.py     ~1 min

The website is built before the posts on purpose. Every caption ends with
"tap the link in our bio to apply", so the site has to be current before a
post that points at it goes out.

Nothing here publishes to Instagram. That stays a separate, deliberate step.
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


# Both scrapers now live in SeekSpider-main/scrapers/ -- one folder for
# "go and get the jobs", separate from the scripts that build things.
SCRAPERS = os.path.join(os.path.dirname(HERE), "scrapers")


def run(label, args, optional=False):
    print(f"\n{'=' * 62}\n  {label}\n{'=' * 62}")
    started = time.time()
    result = subprocess.run([sys.executable] + args, cwd=HERE)
    took = time.time() - started
    if result.returncode != 0:
        if optional:
            # One source failing is not a reason to abandon the run -- the
            # other source still has listings and the site is better stale in
            # one place than not rebuilt at all.
            print(f"\n  ! {label} failed. Carrying on with what we have.")
            return False
        sys.exit(f"\n  ! {label} failed. Stopping.")
    print(f"  ({took/60:.1f} min)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true",
                    help="Seek only -- skips LinkedIn, Indeed, Glassdoor")
    ap.add_argument("--no-check", action="store_true",
                    help="skip asking Seek which listings have closed")
    args = ap.parse_args()
    started = time.time()

    run("1/5  Seek", [os.path.join(SCRAPERS, "seek.py")])

    if args.fast:
        print("\n  (skipping LinkedIn/Indeed/Glassdoor -- --fast)")
    else:
        run("2/5  LinkedIn, Indeed, Glassdoor, Google",
            [os.path.join(SCRAPERS, "other_boards.py")],
            optional=True)

    if args.no_check:
        print("\n  (skipping the still-open check -- --no-check)")
    else:
        run("3/5  Which listings have closed?", ["check_live.py"], optional=True)

    run("4/5  The website", ["build_site.py", "--quiet"])
    run("5/5  The carousels", ["build_carousels.py", "--rebuild"])

    print(f"\n{'=' * 62}\n  DONE in {(time.time()-started)/60:.1f} minutes"
          f"\n{'=' * 62}\n")
    print("Look at it before anything goes out:")
    print("  python3 preview.py                        the posts")
    print("  open berry_internships.html               the website")
    print("\nThen, when you are happy:")
    print("  python3 publish_to_instagram.py           posts what is due today")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
