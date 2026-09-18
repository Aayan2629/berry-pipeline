#!/usr/bin/env python3
"""
scrapers/seek.py -- source one: Seek. The fast way to collect listings.

    python3 scrapers/seek.py                 all 73 searches
    python3 scrapers/seek.py --quick         8 searches
    python3 scrapers/seek.py --days 21 --pages 4

Seek blocks JobSpy outright, which is why it needs its own fetcher while
every other board shares scrapers/other_boards.py.

WHY THIS EXISTS

The Scrapy crawler asked Seek's search API for a page of results, then went
and requested every job's public page one at a time to read its description.
Seek puts those pages behind Cloudflare, so every single one of those requests
came back 403 with the description empty -- and each one still cost a two
second polite delay. In a typical run that was 16 wasted requests for every 4
useful ones, which is where the hour went.

The description was never coming from there anyway: this script gets it from
Seek's GraphQL endpoint, which is not behind Cloudflare.

So this script does the same job without the wasted half:

  1. hit the search API directly, page through the results          (fast)
  2. merge everything by job id -- 73 overlapping searches, one list
  3. filter FIRST: internships only, no grad programmes, in one of the
     four categories, posted recently
  4. only then fetch descriptions, and only for listings that survived and
     that we do not already have cached from a previous run

Fetching descriptions is the slow part at ~1.5s each, so doing it last, for
30 listings instead of 300, is most of the speed-up. Descriptions are cached
in description_cache.json and reused forever -- a job's description does not
change once posted.

Output goes to the same place the crawler used, so build_carousels.py,
build_site.py and everything else read it without knowing the difference.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))   # repo root, for GitHub Actions
sys.path.insert(0, HERE)

from all_jobs import (categorize, is_internship, job_track,      # noqa: E402
                      job_age_days, MAX_AGE_DAYS)
from search_terms import SEARCH_TERMS, QUICK_TERMS               # noqa: E402

SEARCH_URL = "https://www.seek.com.au/api/jobsearch/v5/search"
GRAPHQL_URL = "https://www.seek.com.au/graphql"
_DESC_QUERY = ("query jobDetails($jobId: ID!) { jobDetails(id: $jobId) "
               "{ job { title status content(platform: WEB) location { label } } } }")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15")

CACHE_FILE = os.path.join(HERE, "description_cache.json")
OUT_DIR = os.path.join(HERE, "..", "output", "seek_spider")

# The search API is a plain JSON endpoint with no Cloudflare in front of it,
# so it tolerates a much shorter gap than a page request would.
SEARCH_DELAY = 0.4
DESC_DELAY = 1.5
PAGE_SIZE = 20


def search(session, term, where, days, pages):
    """One search term, paged. Returns raw listing dicts."""
    out = []
    for page in range(1, pages + 1):
        params = {
            "siteKey": "AU-Main", "sourcesystem": "houston", "where": where,
            "keywords": term, "daterange": str(days), "page": str(page),
            "pageSize": str(PAGE_SIZE), "locale": "en-AU",
        }
        try:
            r = session.get(SEARCH_URL, params=params,
                            headers={"User-Agent": UA, "Accept": "application/json"},
                            timeout=25)
        except requests.RequestException as e:
            print(f"    ! {term!r} page {page}: {e}")
            break
        if r.status_code != 200:
            print(f"    ! {term!r} page {page}: HTTP {r.status_code}")
            break
        try:
            body = r.json()
        except ValueError:
            break
        rows = body.get("data") or []
        out.extend(rows)
        # Stop as soon as a page comes back short -- there is nothing after it.
        if len(rows) < PAGE_SIZE:
            break
        time.sleep(SEARCH_DELAY)
    return out


def to_item(d):
    """Seek's search record -> the shape the rest of the pipeline expects."""
    locs = d.get("locations") or [{}]
    return {
        "job_id": str(d.get("id") or ""),
        "job_title": d.get("title") or "",
        "company_name": d.get("companyName") or "",
        "business_name": (d.get("advertiser") or {}).get("description") or "",
        "logo_url": (d.get("branding") or {}).get("serpLogoUrl") or "",
        "bullet_points": d.get("bulletPoints") or [],
        "suburb": locs[0].get("label") or "",
        "area": locs[0].get("label") or "",
        "region": "Sydney",
        "work_type": ", ".join(d.get("workTypes") or []),
        "pay_range": d.get("salaryLabel") or "",
        "posted_date": d.get("listingDate") or "",
        "url": f"https://www.seek.com.au/job/{d.get('id')}",
        "teaser": d.get("teaser") or "",
        "description_text": "",
    }


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def fetch_description(session, job_id):
    payload = {"operationName": "jobDetails",
               "variables": {"jobId": str(job_id)}, "query": _DESC_QUERY}
    try:
        r = session.post(GRAPHQL_URL, json=payload,
                         headers={"User-Agent": UA,
                                  "Content-Type": "application/json"}, timeout=25)
        if r.status_code != 200:
            return None, None
        job = ((r.json().get("data") or {}).get("jobDetails") or {}).get("job")
    except (requests.RequestException, ValueError):
        return None, None
    if not job:
        return None, None
    return job.get("content") or "", (job.get("location") or {}).get("label") or ""


def strip_html(text):
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="8 searches, not 73")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--pages", type=int, default=3,
                    help=f"pages per search, {PAGE_SIZE} results each (default 3)")
    ap.add_argument("--region", default="All Sydney NSW")
    ap.add_argument("--no-descriptions", action="store_true")
    args = ap.parse_args()

    terms = QUICK_TERMS if args.quick else SEARCH_TERMS
    session = requests.Session()
    started = time.time()

    # ---- 1. search -------------------------------------------------------
    print(f"Searching Seek: {len(terms)} terms, last {args.days} days, "
          f"up to {args.pages * PAGE_SIZE} results each\n")
    by_id = {}
    for n, term in enumerate(terms, start=1):
        rows = search(session, term, args.region, args.days, args.pages)
        fresh = 0
        for d in rows:
            jid = str(d.get("id") or "")
            if jid and jid not in by_id:
                by_id[jid] = to_item(d)
                fresh += 1
        print(f"  [{n:>2}/{len(terms)}] {term:<32} {len(rows):>3} found, "
              f"{fresh:>3} new")
        time.sleep(SEARCH_DELAY)

    print(f"\n{len(by_id)} unique listings in {time.time() - started:.0f}s\n")

    # ---- 2. filter BEFORE spending time on descriptions -------------------
    keep, maybe = {}, {}
    why = {"not an internship": 0, "graduate programme": 0, "too old": 0}
    for jid, j in by_id.items():
        title = j["job_title"]
        # The teaser is a sentence or two of the real ad, which is enough for
        # the internship and category tests. The full description is only
        # needed for closing dates on the card.
        hint = j["teaser"]
        if not is_internship(title, hint, j["work_type"]):
            why["not an internship"] += 1
            continue
        if job_track(title, hint, j["work_type"]) == "Graduate Programs":
            why["graduate programme"] += 1
            continue
        age = job_age_days(j["posted_date"])
        if age is not None and age > MAX_AGE_DAYS:
            why["too old"] += 1
            continue
        if not categorize(title, hint):
            # Held back rather than dropped. A title like "2026/27 CommBank
            # Summer Intern Program" names no field at all, and neither does a
            # one-line teaser -- but the description almost always does. These
            # get their description fetched below and are tested again.
            maybe[jid] = j
            continue
        keep[jid] = j

    print(f"{len(keep)} match a category on the title alone")
    for reason, n in why.items():
        if n:
            print(f"  left out: {n} {reason}")
    if maybe:
        print(f"  {len(maybe)} internship(s) name no field in the title -- "
              f"checking their descriptions")

    # ---- 3. descriptions, only for the survivors, only if not cached ------
    cache = load_cache()
    if not args.no_descriptions:
        todo = [jid for jid in list(keep) + list(maybe) if jid not in cache]
        cached = len(keep) + len(maybe) - len(todo)
        print(f"\nDescriptions: {cached} already cached, {len(todo)} to fetch "
              f"(~{len(todo) * DESC_DELAY / 60:.1f} min)")
        for n, jid in enumerate(todo, start=1):
            content, suburb = fetch_description(session, jid)
            if content is not None:
                cache[jid] = content
                if suburb:
                    (keep.get(jid) or maybe.get(jid))["suburb"] = suburb
            if n % 10 == 0:
                save_cache(cache)
                print(f"  {n}/{len(todo)}")
            time.sleep(DESC_DELAY)
        save_cache(cache)

    # Second look at the ones whose title gave nothing away.
    rescued = 0
    for jid, j in maybe.items():
        desc = strip_html(cache.get(jid, ""))
        if desc and categorize(j["job_title"], desc):
            keep[jid] = j
            rescued += 1
    if maybe:
        print(f"  rescued {rescued} of {len(maybe)} once their descriptions "
              f"were read")

    for jid, j in keep.items():
        j["description_text"] = strip_html(cache.get(jid, "")) or j["teaser"]
        j.pop("teaser", None)

    # ---- 4. write it where the rest of the pipeline looks ------------------
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUT_DIR, stamp, "sydney")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "jobs_enriched.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for j in keep.values():
            f.write(json.dumps(j, ensure_ascii=False) + "\n")

    mins = (time.time() - started) / 60
    print(f"\n{len(keep)} listings written in {mins:.1f} minutes")
    print(f"  {path}")
    print("\nNext:  python3 build_carousels.py --rebuild")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
