#!/usr/bin/env python3
"""
commands.py -- every command in this folder, in one place.

    python3 commands.py              print the lot
    python3 commands.py logo         only the ones mentioning "logo"
    python3 commands.py --md         rewrite COMMANDS.md from this list
    python3 commands.py --short      the handful you need most days

WHY THIS IS A PYTHON FILE AND NOT JUST A TEXT FILE

Because a text file goes stale. There are sixteen scripts in here and each
one has its own flags, so a hand-written cheat sheet is wrong within a week
and then you stop trusting it, which is worse than not having one.

This is the single list. COMMANDS.md is GENERATED from it, and refresh.py
and dashboard.py print from it at the end of a run. So there is one place to
edit, and the three places you might read it can never disagree.

IF YOU ADD A SCRIPT

Add a line to SECTIONS below, then run:

    python3 commands.py --md

and the markdown file catches up on its own.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD_FILE = os.path.join(HERE, "COMMANDS.md")

# The folder has a real trailing space in its name, so it has to be quoted or
# the shell splits it into two arguments and cd fails with "No such file".
CD = 'cd ~/Desktop/"job account "/SeekSpider-main/pipeline_scripts'

# Marked "short" appear in the compact block at the end of a run. Everything
# else only shows up in the full list, so the common path stays readable.
# (command, what it does, short?)
SECTIONS = [
    ("EVERY DAY",
     "The two you actually run.",
     [
         ("python3 refresh.py",
          "the whole pipeline: sync, scrape, check closed, site, deploy, carousels", True),
         ("python3 dashboard.py",
          "open the dashboard and see what is due", True),
     ]),

    ("POSTING",
     "Nothing here posts without asking you first.",
     [
         ("python3 publish_to_instagram.py",
          "post whatever is due today", True),
         ("python3 publish_to_instagram.py technology-data-ai-part1",
          "post one carousel by name", False),
         ("python3 publish_to_instagram.py --dry-run",
          "go through the whole thing but publish nothing", True),
         ("python3 publish_to_instagram.py --schedule",
          "what goes out on which day", False),
         ("python3 preview.py",
          "look at every queued carousel as real slides before it goes out", True),
         ("python3 publish_reel.py ~/Desktop/'job account '/'Claude outputs'/berry_ad_reel.mp4",
          "post one video as a reel (caption goes in a .txt of the same name)", False),
     ]),

    ("WHAT IS ACTUALLY ON INSTAGRAM",
     "The local files only know about posts that went out through the\n"
     "  publisher. Post from your phone and they drift. This is the fix.",
     [
         ("python3 ig_sync.py --list",
          "the last posts on the account, straight from Instagram", True),
         ("python3 ig_sync.py",
          "file anything you posted from your phone: history, used listings, queue", True),
         ("python3 ig_sync.py --dry-run",
          "show what it would change, change nothing", False),
     ]),

    ("THE WEBSITE",
     "build writes the file, deploy puts it live. They are separate on\n"
     "  purpose, so you can look at it before the world does.",
     [
         ("python3 build_site.py",
          "rebuild berry_internships.html from the scraped listings", True),
         ("python3 deploy_site.py --check",
          "what is live vs what is on your disk", True),
         ("python3 deploy_site.py",
          "push the file live to internberry.netlify.app", True),
         ("python3 deploy_site.py --site-id",
          "print the Netlify site id", False),
     ]),

    ("THE CAROUSELS",
     "",
     [
         ("python3 build_carousels.py",
          "build carousels for anything new", True),
         ("python3 build_carousels.py --rebuild",
          "rebuild everything in the queue, which is what you want after a\n"
          "      style change", True),
         ("python3 build_carousels.py --list",
          "the category names", False),
         ('python3 build_carousels.py --category "tech"',
          "just one category", False),
         ("python3 build_carousels.py --per-carousel 5",
          "how many roles per post (1 to 9)", False),
     ]),

    ("LOGOS",
     "A wrong logo is worse than an initials tile, so nothing here guesses\n"
     "  without checking. Answers are saved forever.",
     [
         ("python3 missing_logos.py",
          "which employers still have no logo, most common first", True),
         ("python3 find_logos.py",
          "go and find domains for the ones that are missing", True),
         ('python3 find_logos.py --category commerce',
          "just that category", False),
         ('python3 find_logos.py --accept "Arup"',
          "yes, that candidate is them", True),
         ('python3 find_logos.py --set "ADP Consulting" adpconsulting.com',
          "no, it is this one instead", True),
         ('python3 find_logos.py --reject "Nine"',
          "leave it as an initials tile and stop asking", False),
     ]),

    ("BACKGROUND PHOTOS",
     "Unsplash only. Photos off Google Images are not safe to post.",
     [
         ("python3 more_backgrounds.py",
          "pull fresh bright photos into background pics/", False),
         ('python3 more_backgrounds.py "sunlit cafe laptop"',
          "search for something specific", False),
         ("python3 more_backgrounds.py --list",
          "what you already have", False),
     ]),

    ("WHEN SOMETHING LOOKS WRONG",
     "",
     [
         ("python3 check_live.py",
          "ask Seek which listings have actually closed", False),
         ("python3 refresh.py --fast",
          "skip the slow scrapers", False),
         ("python3 refresh.py --no-check",
          "skip the closed-listing check", False),
         ("python3 commands.py",
          "this list", True),
     ]),
]


def _matches(needle, cmd, what):
    return needle in cmd.lower() or needle in what.lower()


def print_all(needle=None, short_only=False, out=None):
    """The full list, grouped, with the folder to cd into at the top."""
    out = out or sys.stdout
    w = out.write

    w("\n" + "=" * 70 + "\n  COMMANDS\n" + "=" * 70 + "\n")
    w(f"\n  {CD}\n")

    shown = 0
    for title, note, rows in SECTIONS:
        rows = [r for r in rows if not short_only or r[2]]
        if needle:
            rows = [r for r in rows if _matches(needle, r[0], r[1])]
        if not rows:
            continue
        w(f"\n  {title}\n")
        if note and not short_only:
            w(f"  {note}\n")
        for cmd, what, _ in rows:
            w(f"\n    {cmd}\n      {what}\n")
            shown += 1

    if needle and not shown:
        w(f"\n  Nothing matches {needle!r}. Run  python3 commands.py  "
          f"for the lot.\n")
    if short_only:
        w("\n  Full list:  python3 commands.py\n")
    w("\n")
    return shown


def tail(out=None):
    """What refresh.py and dashboard.py print when they finish.

    Deliberately the whole list rather than a chosen few: the point of it
    being at the bottom of a run is that you never have to remember which
    script does what, and a shortened list would just send you looking.
    """
    print_all(out=out)


def write_markdown():
    """Regenerate COMMANDS.md. Generated, so never edit it by hand -- edit
    SECTIONS above and run this again."""
    lines = [
        "# Commands",
        "",
        "Everything in `pipeline_scripts/`, generated from `commands.py`.",
        "Do not edit this file by hand: edit `SECTIONS` in `commands.py` and run",
        "`python3 commands.py --md`.",
        "",
        "Every command below is run from this folder:",
        "",
        "```",
        CD,
        "```",
        "",
        "The folder name ends in a real space, which is why it is quoted.",
        "",
    ]
    for title, note, rows in SECTIONS:
        lines += [f"## {title.title()}", ""]
        if note:
            lines += [note.replace("\n  ", " ").strip(), ""]
        for cmd, what, _ in rows:
            lines += [f"**`{cmd}`**", "",
                      what.replace("\n      ", " ").strip(), ""]
    with open(MD_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return MD_FILE


def main():
    ap = argparse.ArgumentParser(description="Every command in this folder.")
    ap.add_argument("needle", nargs="?", default=None,
                    help='filter, e.g. "logo" or "deploy"')
    ap.add_argument("--md", action="store_true",
                    help="rewrite COMMANDS.md from this list")
    ap.add_argument("--short", action="store_true",
                    help="only the ones you need most days")
    args = ap.parse_args()

    if args.md:
        path = write_markdown()
        n = sum(len(r) for _, _, r in SECTIONS)
        print(f"\n  Wrote {os.path.basename(path)}  ({n} commands)\n")
        return 0

    print_all(needle=(args.needle or "").lower() or None,
              short_only=args.short)
    return 0


if __name__ == "__main__":
    sys.exit(main())
