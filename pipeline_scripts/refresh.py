#!/usr/bin/env python3
"""
refresh.py -- the weekly run. One command, five steps, in order.

    python3 refresh.py              everything
    python3 refresh.py --fast       Seek only, skip the slow boards
    python3 refresh.py --no-check   skip the still-open checks

    1. Seek              scrapers/seek.py              ~3 min
    2. LinkedIn etc.     scrapers/other_boards.py      ~5 min
    3. Seek closed?      check_live.py                 ~1 min
    4. others closed?    check_other_boards_live.py    ~3 min
    5. THE WEBSITE       build_site.py                 seconds
    6. put it live       deploy_site.py                seconds
    7. the carousels     build_carousels.py            ~1 min

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

    # FIRST, before anything decides what to build. If you posted from your
    # phone, the queue still thinks that carousel is due and its listings are
    # still unmarked, so build_carousels.py would happily put the same six
    # jobs back on a slide. Asking Instagram first is what stops that.
    # Optional: no internet, or an expired token, must not stop a scrape.
    run("1/7  What is already on Instagram?", ["ig_sync.py"], optional=True)

    run("2/7  Seek", [os.path.join(SCRAPERS, "seek.py")])

    if args.fast:
        print("\n  (skipping LinkedIn/Indeed/Glassdoor -- --fast)")
    else:
        run("3/7  LinkedIn, Indeed, Glassdoor, Google",
            [os.path.join(SCRAPERS, "other_boards.py")],
            optional=True)

    if args.no_check:
        print("\n  (skipping the still-open checks -- --no-check)")
    else:
        run("4/7  Which Seek listings have closed?", ["check_live.py"], optional=True)
        # LinkedIn/Indeed/Glassdoor/Google never had a liveness check at all --
        # Seek's API can't answer for them (see check_other_boards_live.py's
        # own docstring), so without this they only ever aged off after
        # MAX_AGE_DAYS, however long ago the employer actually closed
        # applications.
        run("4b/7 Which LinkedIn/Indeed/etc have closed?",
            ["check_other_boards_live.py"], optional=True)

    run("5/7  The website", ["build_site.py", "--quiet"])
    # Optional on purpose: no NETLIFY_TOKEN yet means this prints how to set
    # one up and the run carries on. A missing deploy should not stop the
    # carousels from being built.
    # The website now goes live through Cloudflare Pages, as its own step in
    # .github/workflows/berry.yml, so this no longer spends Netlify credits.
    # Set USE_NETLIFY=1 to deploy to Netlify again (os.environ is like getenv
    # in C: read a setting from the environment).
    if os.environ.get("USE_NETLIFY") == "1":
        run("6/7  Put the website live (Netlify)", ["deploy_site.py"], optional=True)
    else:
        print("\n  6/7  website goes live via Cloudflare (GitHub step), not Netlify")
    run("7/7  The carousels", ["build_carousels.py", "--rebuild"])

    print(f"\n{'=' * 62}\n  DONE in {(time.time()-started)/60:.1f} minutes"
          f"\n{'=' * 62}\n")
    print("Look at it before anything goes out:")
    print("  python3 preview.py                        the posts")
    print("  open berry_internships.html               the website")
    print("\nThen, when you are happy:")
    print("  python3 publish_to_instagram.py           posts what is due today")

    # Every command in the folder, printed at the bottom of the run so you
    # never have to go and remember which script does what. One list, kept in
    # commands.py -- see COMMANDS.md for the same thing as a file.
    try:
        import commands
        commands.tail()
    except Exception:
        # A cheat sheet failing must never make a good refresh look failed.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
