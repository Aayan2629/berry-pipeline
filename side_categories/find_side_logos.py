#!/usr/bin/env python3
"""
side_categories/find_side_logos.py -- find real logos for the side employers.

    python3 side_categories/find_side_logos.py
    python3 side_categories/find_side_logos.py --dry-run   look, write nothing

The main pipeline runs pipeline_scripts/find_logos.py BEFORE building slides:
it looks each employer up online (Wikidata's "official website", then a
guess-and-verify of the company's own site) and saves the domain in
brand_domains.json. poster_template.py then fetches the real logo from that
domain. Skip that step and every unknown company gets an initials tile --
which is exactly what happened to the first side build.

This does the SAME search, using find_logos.py's own functions (not a copy),
but only for employers in the newest architecture.jsonl / medicine.jsonl.
build_side_carousels.py now calls it automatically before drawing anything.

Shared files it writes (same as find_logos.py does -- additive only):
  brand_domains.json  new employer -> domain, only when the lookup is sure
  logo_review.json    ones it's unsure about, shown on the dashboard for you
                      to --accept / --reject with find_logos.py
It never removes or changes an existing entry.
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PIPE = os.path.join(REPO, "pipeline_scripts")
sys.path.insert(0, REPO)
sys.path.insert(0, PIPE)

import find_logos as fl                                          # noqa: E402

RUNS = os.path.join(REPO, "output", "side_spider")
FILES = ("architecture.jsonl", "medicine.jsonl")


def side_employers():
    """employer name -> how many side listings it has (newest run of each file)."""
    counts = {}
    for name in FILES:
        paths = sorted(glob.glob(os.path.join(RUNS, "*", name)))
        if not paths:
            continue
        with open(paths[-1], encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                j = json.loads(line)
                who = (fl.real_company(j.get("company_name")
                                       or j.get("business_name")) or "").strip()
                if who:
                    counts[who] = counts.get(who, 0) + 1
    return counts


def find(dry_run=False, verbose=True):
    """Look up every side employer that has no logo yet. Returns (added, queued)."""
    say = print if verbose else (lambda *a, **k: None)
    brands = fl.load_json(fl.BRANDS_FILE, {})
    review = fl.load_json(fl.REVIEW_FILE, {})

    todo = side_employers()
    # Skip ones already sorted: a known domain, a cached logo file, or one
    # you've already rejected by hand.
    pending = [(n, c) for n, c in todo.items()
               if n not in brands
               and not fl.has_logo_already(n)
               and not review.get(n, {}).get("rejected")]
    say(f"Logos: {len(todo)} side employers, {len(pending)} still need a search")

    added = queued = 0
    for name, count in sorted(pending, key=lambda x: -x[1]):
        say(f"  {name}")
        if name.lower() in fl.TOO_GENERIC or not fl.tokens(name):
            say("     too generic to look up safely -- stays a tile")
            continue

        dom, why = fl.wikidata_domain(name)          # 1. Wikidata
        if not dom:
            dom, why, title, cand = fl.guess_and_verify(name)   # 2. guess + check
        if dom:
            say(f"     found {dom}  ({why})")
            brands[name] = dom
            review.pop(name, None)
            added += 1
        else:
            say(f"     not sure ({why}) -> on the dashboard for you to check")
            review[name] = {"domain": cand, "why": why, "count": count,
                            "saw": title, "confirmed": False}
            queued += 1

    if not dry_run:
        fl.save_json(fl.BRANDS_FILE, brands)
        fl.save_json(fl.REVIEW_FILE, review)
    say(f"Logos: {added} found, {queued} need your eyes"
        + (" (dry run, nothing saved)" if dry_run else ""))
    return added, queued


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    find(dry_run=ap.parse_args().dry_run)
