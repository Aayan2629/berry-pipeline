#!/usr/bin/env python3
"""
scrapers/other_boards.py -- source two: LinkedIn, Indeed, Glassdoor, Google.

    python3 scrapers/other_boards.py
    python3 scrapers/other_boards.py --sites linkedin,indeed --results 40

Seek is one board and a general one. LinkedIn in particular carries the big
employer programmes Seek never sees, and -- the reason this exists at all --
LinkedIn returns a company logo for almost every listing, where Seek only has
one for advertisers who paid for branding.

Writes the same jobs_enriched.jsonl shape scrapers/seek.py does, into the same
output folder, so build_site.py and build_carousels.py merge the two sources
without knowing there are two.

JobSpy has no per-site error isolation: one failing request aborts the whole
call. So every site-and-term pair gets its own try/except and a failure skips
just that pair.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

OUT_DIR = os.path.join(HERE, "..", "output", "seek_spider")
LOCATION = "Sydney, New South Wales, Australia"

# Deliberately short. JobSpy is slow and rate-limited, and these boards match
# far more loosely than Seek, so a handful of broad terms finds nearly
# everything a long list would.
TERMS = ["internship", "intern", "vacation program", "graduate program"]
SITES = ["linkedin", "indeed", "glassdoor", "google"]


def clean(v):
    import pandas as pd
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", default=",".join(SITES))
    ap.add_argument("--results", type=int, default=30)
    ap.add_argument("--days", type=int, default=21)
    args = ap.parse_args()

    try:
        from jobspy import scrape_jobs
    except ImportError:
        sys.exit("Needs JobSpy:  pip3 install --user python-jobspy")

    sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    started = time.time()
    by_url = {}

    for site in sites:
        got = 0
        for term in TERMS:
            print(f"  {site:<10} <- {term!r}", end=" ... ", flush=True)
            try:
                df = scrape_jobs(
                    site_name=[site],
                    search_term=term,
                    google_search_term=f"{term} jobs in Sydney",
                    location=LOCATION,
                    results_wanted=args.results,
                    hours_old=args.days * 24,
                    country_indeed="Australia",
                )
            except Exception as e:
                print(f"skipped ({type(e).__name__}: {str(e)[:50]})")
                continue
            if df is None or not len(df):
                print("0")
                continue

            for _, row in df.iterrows():
                url = clean(row.get("job_url"))
                if not url or url in by_url:
                    continue
                lo, hi = clean(row.get("min_amount")), clean(row.get("max_amount"))
                pay = f"${lo} - ${hi}" if lo and hi else ""
                by_url[url] = {
                    "job_id": "js-" + re.sub(r"[^a-z0-9]+", "-", url.lower())[-50:],
                    "job_title": clean(row.get("title")),
                    "company_name": clean(row.get("company")),
                    "business_name": clean(row.get("company")),
                    # The whole point: LinkedIn hands back a logo for nearly
                    # every listing. The old code fetched this column and
                    # dropped it on the floor.
                    "logo_url": clean(row.get("company_logo")),
                    "company_url": clean(row.get("company_url")),
                    "suburb": clean(row.get("location")) or "Sydney NSW",
                    "area": clean(row.get("location")),
                    "region": "Sydney",
                    "work_type": clean(row.get("job_type")),
                    "pay_range": pay,
                    "posted_date": clean(row.get("date_posted")),
                    "url": url,
                    "source": site,
                    "description_text": clean(row.get("description")),
                }
                got += 1
            print(len(df))
            time.sleep(1.0)
        print(f"    {site}: {got} kept")

    if not by_url:
        print("\nNothing came back from any site. That is usually rate "
              "limiting -- wait ten minutes and try one site at a time.")
        return 1

    with_logo = sum(1 for j in by_url.values() if j["logo_url"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUT_DIR, stamp + "_jobspy", "sydney")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "jobs_enriched.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for j in by_url.values():
            f.write(json.dumps(j, ensure_ascii=False) + "\n")

    print(f"\n{len(by_url)} listings in {(time.time()-started)/60:.1f} minutes")
    print(f"  {with_logo} of them ({100*with_logo//len(by_url)}%) came with a logo")
    print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
