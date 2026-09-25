#!/usr/bin/env python3
"""
side_categories/scrape_side.py -- scrape Architecture and Medicine ON THE SIDE.

    python3 side_categories/scrape_side.py                    both categories
    python3 side_categories/scrape_side.py --only architecture
    python3 side_categories/scrape_side.py --only medicine
    python3 side_categories/scrape_side.py --no-descriptions  faster test run

WHY IT'S SAFE (doesn't touch the running pipeline)

  * It only READS from the main code: it borrows the search/description
    functions from scrapers/seek.py and the filters from all_jobs.py.
    It never edits those files.
  * It writes to its OWN places:
        output/side_spider/<timestamp>/architecture.jsonl
        output/side_spider/<timestamp>/medicine.jsonl
        side_categories/side_description_cache.json
    The main pipeline reads output/seek_spider/ and
    scrapers/description_cache.json, so it never sees any of this.
  * No GitHub workflow calls this file, so nothing runs it automatically.
    It only runs when you type the command.
  * It never posts anything. It just finds jobs and writes them down.

WHAT IT DOES (same 4 steps as seek.py)
  1. search Seek with each term for that category
  2. merge duplicates by job id
  3. filter: student role, not a grad program, not too old, actually in
     this field, and NOT already claimed by Tech/Business/Engineering
  4. fetch descriptions for the survivors, then write one file PER category

At the end it prints a report with the number that answers
"are there enough jobs to post?".
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Finding the main code so we can borrow from it
# ---------------------------------------------------------------------------
# HERE = this folder (side_categories/). REPO = one level up (the repo root).
# sys.path is the list of folders Python searches when you "import"
# something, a bit like the -I include paths you give gcc in C.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)                              # for all_jobs.py
sys.path.insert(0, os.path.join(REPO, "scrapers"))    # for seek.py

# Borrowed from the main pipeline, used READ-ONLY. Importing a file runs
# only its top-level definitions, not its main(), so seek.py doesn't start
# scraping just because we imported it.
import seek                                                       # noqa: E402
from all_jobs import (categorize, is_internship, job_track,       # noqa: E402
                      job_age_days, MAX_AGE_DAYS)
from side_rules import (SIDE_TERMS, categorize_side, is_student_role,  # noqa: E402
                        is_entry_level_architecture_grad,
                        is_clear_medicine_student_role)

# Our own files -- separate from the main pipeline's.
SIDE_CACHE_FILE = os.path.join(HERE, "side_description_cache.json")
SIDE_OUT_DIR = os.path.join(REPO, "output", "side_spider")

# Short names you can type after --only, mapped to the real category names.
SHORT_NAMES = {"architecture": "Architecture", "medicine": "Medicine & Health"}
FILE_NAMES = {"Architecture": "architecture.jsonl",
              "Medicine & Health": "medicine.jsonl"}

# A carousel with fewer jobs than this looks thin. Only used for the report
# at the end -- it doesn't stop anything being written.
MIN_JOBS_FOR_A_POST = 3


def load_cache():
    """Our own description cache (job id -> description HTML)."""
    try:
        with open(SIDE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    with open(SIDE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def scrape_category(session, category, args, cache):
    """
    Run the whole search -> filter -> describe process for ONE category.
    Returns (kept_jobs_dict, report_dict).

    Each category is done completely on its own, so Architecture and
    Medicine never get mixed together.
    """
    terms = SIDE_TERMS[category]
    print(f"\n=== {category}: {len(terms)} searches, last {args.days} days ===")

    # ---- 1. search ---------------------------------------------------------
    # by_id is a dict: job id -> job. Using the id as the key removes
    # duplicates for free (the same job found by 5 different searches is
    # stored once). In R you'd do this with !duplicated(df$id).
    by_id = {}
    term_hits = {}                      # how many jobs each term found
    for n, term in enumerate(terms, start=1):
        rows = seek.search(session, term, args.region, args.days, args.pages)
        fresh = 0
        for d in rows:
            jid = str(d.get("id") or "")
            if jid and jid not in by_id:
                by_id[jid] = seek.to_item(d)
                fresh += 1
        term_hits[term] = fresh
        print(f"  [{n:>2}/{len(terms)}] {term:<34} {len(rows):>3} found, "
              f"{fresh:>3} new")
        time.sleep(seek.SEARCH_DELAY)

    # ---- 2. filter ---------------------------------------------------------
    keep, maybe = {}, {}
    why = {"not a student role": 0, "graduate programme": 0,
           "mixed job, not clearly for students": 0, "too old": 0,
           "different field": 0, "already in Tech/Business/Engineering": 0}
    claimed_by_main = []               # jobs the main pipeline already owns

    for jid, j in by_id.items():
        title, hint = j["job_title"], j["teaser"]

        # Student role? Main rule OR the extra side words (student, cadet...)
        if not (is_internship(title, hint, j["work_type"])
                or is_student_role(title)):
            why["not a student role"] += 1
            continue
        # Graduate roles: dropped everywhere EXCEPT entry-level architecture
        # grads (see side_rules.py section 3b for why).
        if job_track(title, hint, j["work_type"]) == "Graduate Programs":
            arch_grad_ok = (category == "Architecture"
                            and is_entry_level_architecture_grad(title))
            if not arch_grad_ok:
                why["graduate programme"] += 1
                continue

        # Medicine: only clear student roles, no "Technician / Intern" combos.
        if category == "Medicine & Health" and \
           not is_clear_medicine_student_role(title):
            why["mixed job, not clearly for students"] += 1
            continue
        age = job_age_days(j["posted_date"])
        if age is not None and age > MAX_AGE_DAYS:
            why["too old"] += 1
            continue

        side_cat = categorize_side(title)       # title only, for now
        if side_cat is not None and side_cat != category:
            why["different field"] += 1          # e.g. a medicine job that
            continue                             # an architecture search found

        # Does the MAIN pipeline already post this job? If yes we skip it,
        # so nothing ever gets posted twice. We keep a list so you can see
        # the overlap before we merge everything.
        main_cat = categorize(title, hint)
        if main_cat:
            why["already in Tech/Business/Engineering"] += 1
            if side_cat == category:
                claimed_by_main.append((title, main_cat))
            continue

        if side_cat == category:
            keep[jid] = j
        else:
            maybe[jid] = j      # title says nothing -- check the description

    # ---- 3. descriptions (only for survivors, only if not cached) ----------
    if not args.no_descriptions:
        todo = [jid for jid in list(keep) + list(maybe) if jid not in cache]
        print(f"\n  descriptions: {len(keep) + len(maybe) - len(todo)} cached, "
              f"{len(todo)} to fetch (~{len(todo) * seek.DESC_DELAY / 60:.1f} min)")
        for jid in todo:
            content, suburb = seek.fetch_description(session, jid)
            if content is not None:
                cache[jid] = content
                if suburb:
                    (keep.get(jid) or maybe.get(jid))["suburb"] = suburb
            time.sleep(seek.DESC_DELAY)
        save_cache(cache)

    # Second chance for the "maybe" jobs, now that we have descriptions.
    rescued = 0
    for jid, j in maybe.items():
        desc = seek.strip_html(cache.get(jid, ""))
        if desc and categorize_side(j["job_title"], desc) == category \
           and not categorize(j["job_title"], desc):
            keep[jid] = j
            rescued += 1

    # Same final shape as seek.py writes, so build_carousels.py can use it later.
    for jid, j in keep.items():
        j["description_text"] = seek.strip_html(cache.get(jid, "")) or j["teaser"]
        j.pop("teaser", None)
        j["side_category"] = category

    report = {"found": len(by_id), "kept": len(keep), "rescued": rescued,
              "why": why, "claimed_by_main": claimed_by_main,
              "term_hits": term_hits}
    return keep, report


def print_report(category, keep, rep):
    """The part you actually read: is there enough to post?"""
    print(f"\n----- {category} -----")
    print(f"  unique listings found : {rep['found']}")
    for reason, n in rep["why"].items():
        if n:
            print(f"    left out: {n:>3}  {reason}")
    if rep["rescued"]:
        print(f"  rescued from descriptions: {rep['rescued']}")
    print(f"  >>> KEPT: {len(keep)} job(s)")
    for j in keep.values():
        print(f"      - {j['job_title']}  |  {j['company_name']}  "
              f"|  posted {str(j['posted_date'])[:10]}")

    if rep["claimed_by_main"]:
        print(f"  {category} jobs the main pipeline already posts "
              f"(skipped so they aren't posted twice):")
        for title, main_cat in rep["claimed_by_main"]:
            print(f"      - {title}  ->  {main_cat}")

    dead = [t for t, n in rep["term_hits"].items() if n == 0]
    if dead:
        print(f"  search terms that found nothing new ({len(dead)}): "
              + ", ".join(dead))

    if len(keep) >= MIN_JOBS_FOR_A_POST:
        print(f"  VERDICT: enough for a post ({len(keep)} >= "
              f"{MIN_JOBS_FOR_A_POST})")
    else:
        print(f"  VERDICT: too thin for a post right now ({len(keep)} < "
              f"{MIN_JOBS_FOR_A_POST}) -- skip this week or batch fortnightly")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(SHORT_NAMES),
                    help="run just one category")
    ap.add_argument("--days", type=int, default=MAX_AGE_DAYS)
    ap.add_argument("--pages", type=int, default=2,
                    help="pages per search, 20 results each (default 2)")
    ap.add_argument("--region", default="All Sydney NSW")
    ap.add_argument("--no-descriptions", action="store_true",
                    help="skip fetching descriptions (faster, less accurate)")
    args = ap.parse_args()

    categories = ([SHORT_NAMES[args.only]] if args.only
                  else list(SIDE_TERMS))       # both, one after the other

    session = seek.requests.Session()
    cache = load_cache()
    started = time.time()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(SIDE_OUT_DIR, stamp)
    os.makedirs(out_dir, exist_ok=True)

    results = {}
    for category in categories:
        keep, rep = scrape_category(session, category, args, cache)
        results[category] = (keep, rep)

        # One file PER category -- never combined.
        path = os.path.join(out_dir, FILE_NAMES[category])
        with open(path, "w", encoding="utf-8") as f:
            for j in keep.values():
                f.write(json.dumps(j, ensure_ascii=False) + "\n")

    print("\n" + "=" * 60 + "\nREPORT\n" + "=" * 60)
    for category, (keep, rep) in results.items():
        print_report(category, keep, rep)

    print(f"\nDone in {(time.time() - started) / 60:.1f} min. Files in:\n  {out_dir}")
    print("Nothing was posted. The main pipeline didn't see any of this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
