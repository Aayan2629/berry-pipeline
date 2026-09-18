#!/usr/bin/env python3
"""
check_other_boards_live.py -- ask LinkedIn/Indeed/Glassdoor/Google's own job
pages whether a listing is still accepting applications.

    python3 check_other_boards_live.py

check_live.py can only ask Seek about a listing, because Seek's GraphQL API
is the only one of these that knows about Seek's own ids -- it was tried
against LinkedIn/Indeed ids too early on and answered "no such job" for
every single one, which would have wiped every non-Seek listing off the
site. So those listings have only ever aged off after MAX_AGE_DAYS,
regardless of whether the employer actually closed applications days or
weeks earlier. That is why a LinkedIn ad can show "No longer accepting
applications" on LinkedIn itself while still looking live on the website.

This script closes that gap the only way available for these boards: it
revisits each listing's own page and looks for the phrase the site itself
shows once it has stopped taking applications ("No longer accepting
applications", "This job is no longer available", and similar). A page that
fails to load, gets blocked, or sits behind a login wall does NOT get
marked closed -- silence is not evidence. Only a page that explicitly says
it is closed gets recorded as such. Same principle check_live.py uses for
Seek: a failed or interrupted run leaves the site intact rather than
emptying it.

Writes into the same listing_status.json check_live.py uses, so
all_jobs.py's load_dead_listings() picks up both sources with no changes
needed there.

These boards are far more bot-sensitive than Seek's own API, so this asks
slower, caps how many it checks in one run, and stops itself early the
moment a site starts answering 429 rather than pushing through the rest of
the list.
"""

import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(HERE, "listing_status.json")
CRAWL_GLOB = os.path.join(HERE, "..", "output", "seek_spider", "*", "*")

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                   "Version/17.4.1 Safari/605.1.15"),
}

DELAY_SECONDS = 2.5             # slower than check_live.py -- these boards watch for bots
MAX_PER_RUN = 80                # stop well short of tripping a block, even if more is due
RECHECK_AFTER_HOURS = 12

# Matches MAX_AGE_DAYS in all_jobs.py: build_site.py drops anything older
# than that regardless of status, so there is no point asking past it.
STOP_CHECKING_AFTER_DAYS = 21

# What each of these sites says, in its own words, once a listing has
# stopped taking applications. Matched case-insensitively against the raw
# page text, so it survives most markup and wording differences between
# sites. Deliberately narrow: a page that fails to load, or shows a login
# wall instead of the listing, will not contain any of these, and correctly
# falls through to "unknown" rather than "Closed".
CLOSED_PHRASES = [
    "no longer accepting applications",
    "not currently accepting applications",
    "applications are now closed",
    "applications have closed",
    "applications closed",
    "this job is no longer available",
    "this job posting is no longer available",
    "this position has been filled",
    "job posting has expired",
    "this posting has expired",
    "job has expired",
]


def load_status():
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_status(status):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, sort_keys=True)


def is_other_board_id(jid):
    """These ids are the js- prefixed hashes other_boards.py makes from a
    LinkedIn/Indeed/Glassdoor/Google url. Seek's own ids are plain numbers
    and check_live.py already owns those."""
    return str(jid).startswith("js-")


def job_pool():
    """Every non-Seek job id seen in any crawl, with its url and posted date."""
    pool = {}
    for crawl_dir in sorted(glob.glob(CRAWL_GLOB)):
        for name in ("jobs_enriched.jsonl", "jobs.jsonl"):
            path = os.path.join(crawl_dir, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    jid = j.get("job_id")
                    url = j.get("url")
                    if jid and url and is_other_board_id(jid):
                        pool.setdefault(str(jid), {
                            "title": j.get("job_title") or "",
                            "posted": j.get("posted_date") or "",
                            "url": url,
                            "source": j.get("source") or "",
                        })
    return pool


def too_old(posted):
    if not posted:
        return False
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(posted[:19], fmt)
            return (datetime.now() - d).days > STOP_CHECKING_AFTER_DAYS
        except ValueError:
            continue
    return False


def checked_recently(entry):
    stamp = (entry or {}).get("checked_at")
    if not stamp:
        return False
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    return datetime.now() - when < timedelta(hours=RECHECK_AFTER_HOURS)


def ask_the_page(url, session):
    """('Closed' | 'Active' | 'blocked' | None). None means inconclusive --
    errored or just didn't say either way -- and is never treated as
    Closed. 'blocked' means the site answered 429 and this run should stop
    asking it rather than push through and get the IP flagged."""
    try:
        r = session.get(url, headers=_HEADERS, timeout=20, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code == 429:
        return "blocked"
    if r.status_code >= 400:
        return None
    text = r.text.lower()
    for phrase in CLOSED_PHRASES:
        if phrase in text:
            return "Closed"
    return "Active"


def main():
    pool = job_pool()
    status = load_status()

    todo = [jid for jid, info in pool.items()
            if not too_old(info["posted"]) and not checked_recently(status.get(jid))]

    print(f"{len(pool)} non-Seek listing(s) known, {len(todo)} to check "
          f"(the rest were checked in the last {RECHECK_AFTER_HOURS}h "
          f"or are older than {STOP_CHECKING_AFTER_DAYS} days)\n")
    if not todo:
        return 0

    if len(todo) > MAX_PER_RUN:
        print(f"  (only checking {MAX_PER_RUN} of {len(todo)} this run -- "
              f"the rest will be picked up next time)\n")
        todo = sorted(todo)[:MAX_PER_RUN]

    session = requests.Session()
    counts = {"Active": 0, "Closed": 0, "unknown": 0}

    for n, jid in enumerate(sorted(todo), start=1):
        info = pool[jid]
        state = ask_the_page(info["url"], session)
        if state == "blocked":
            print(f"  [{n}/{len(todo)}] {info['source']} started answering "
                  f"429 -- stopping here for this run, leaving the rest as they were")
            break
        if state is None:
            counts["unknown"] += 1
        else:
            counts[state] += 1
            status[jid] = {
                "status": state,
                "title": info["title"],
                "source": info["source"],
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }
            if state == "Closed":
                print(f"  [{n}/{len(todo)}] {info['source']:<9} CLOSED -- "
                      f"{info['title'][:52]}")
        if n % 20 == 0:
            save_status(status)          # don't lose a run's work to a Ctrl-C
        time.sleep(DELAY_SECONDS)

    save_status(status)

    print(f"\n  still open : {counts['Active']}")
    print(f"  closed     : {counts['Closed']}")
    if counts["unknown"]:
        print(f"  unknown    : {counts['unknown']}  (kept -- not treated as dead)")
    print(f"\nWrote: {STATUS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
