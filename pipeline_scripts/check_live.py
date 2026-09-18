#!/usr/bin/env python3
"""
check_live.py -- ask Seek which listings are still open.

    python3 check_live.py

A job disappears from a Seek search for two very different reasons: it was
filled and taken down, or it simply fell past the search limit we asked for.
Treating both as "gone" would delete live jobs from the website, so we do not
guess from absence -- we ask Seek about each listing by id.

Seek's GraphQL answers with a status per job:

    status "Active"    still open, still taking applications
    status "Expired"   the ad has run out
    job is null        the listing was deleted outright

The result is written to listing_status.json, which all_jobs.py and
build_carousels.py both read. A job that has never been checked counts as
live -- this file can only ever remove things it has positively confirmed are
dead, so a failed or interrupted run leaves the site intact rather than
emptying it.

Roughly 1.5 seconds per job, so a typical pool takes about a minute.
"""

import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(HERE, "listing_status.json")
CRAWL_GLOB = os.path.join(HERE, "..", "output", "seek_spider", "*", "*")

GRAPHQL_URL = "https://www.seek.com.au/graphql"
_QUERY = ("query jobDetails($jobId: ID!) { "
          "jobDetails(id: $jobId) { job { title status } } }")
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                   "Version/17.4.1 Safari/605.1.15"),
}

DELAY_SECONDS = 1.5

# Don't re-check something checked in the last few hours -- nothing changes
# that fast, and it makes running this twice in a row nearly instant.
RECHECK_AFTER_HOURS = 12

# Stop bothering Seek about listings this old. They are already past the
# website's display window, so their status no longer matters.
STOP_CHECKING_AFTER_DAYS = 30


def load_status():
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_status(status):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, sort_keys=True)


def is_seek_id(jid):
    """Seek job ids are plain numbers. Everything JobSpy brings back is
    prefixed 'js-' and belongs to another board entirely."""
    return str(jid).isdigit()


def job_pool():
    """Every job id seen in any crawl, with its posted date."""
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
                    # ONLY Seek ids. This check asks Seek's own API whether a
                    # listing is still up, and Seek has never heard of a
                    # LinkedIn or Indeed one -- so it answered "no such job"
                    # and every single non-Seek listing was marked Gone and
                    # dropped from the site. They age out on MAX_AGE_DAYS
                    # instead, which is the honest thing to do when there is
                    # no API to ask.
                    if jid and is_seek_id(jid):
                        pool.setdefault(str(jid), {
                            "title": j.get("job_title") or "",
                            "posted": j.get("posted_date") or "",
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


def ask_seek(job_id, session):
    """('Active' | 'Expired' | 'Gone' | None, title). None means we could not
    find out -- a network problem, not an answer."""
    payload = {"operationName": "jobDetails",
               "variables": {"jobId": str(job_id)},
               "query": _QUERY}
    try:
        r = session.post(GRAPHQL_URL, json=payload, headers=_HEADERS, timeout=20)
    except requests.RequestException:
        return None, ""
    if r.status_code != 200:
        return None, ""
    try:
        body = r.json()
    except ValueError:
        return None, ""
    if body.get("errors"):
        return None, ""
    job = ((body.get("data") or {}).get("jobDetails") or {}).get("job")
    if job is None:
        return "Gone", ""
    return job.get("status") or "Active", job.get("title") or ""


def main():
    pool = job_pool()
    status = load_status()

    todo = [jid for jid, info in pool.items()
            if not too_old(info["posted"]) and not checked_recently(status.get(jid))]

    print(f"{len(pool)} listing(s) known, {len(todo)} to check "
          f"(the rest were checked in the last {RECHECK_AFTER_HOURS}h "
          f"or are older than {STOP_CHECKING_AFTER_DAYS} days)\n")
    if not todo:
        return 0

    session = requests.Session()
    counts = {"Active": 0, "Expired": 0, "Gone": 0, "unknown": 0}

    for n, jid in enumerate(sorted(todo), start=1):
        state, title = ask_seek(jid, session)
        if state is None:
            counts["unknown"] += 1
            print(f"  [{n}/{len(todo)}] {jid}  couldn't reach Seek -- "
                  f"leaving it as it was")
        else:
            counts[state] += 1
            status[jid] = {
                "status": state,
                "title": title or pool[jid]["title"],
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }
            if state != "Active":
                print(f"  [{n}/{len(todo)}] {jid}  {state.upper()} -- "
                      f"{(title or pool[jid]['title'])[:52]}")
        if n % 20 == 0:
            save_status(status)          # don't lose an hour's work to a Ctrl-C
        time.sleep(DELAY_SECONDS)

    save_status(status)

    print(f"\n  still open : {counts['Active']}")
    print(f"  expired    : {counts['Expired']}")
    print(f"  deleted    : {counts['Gone']}")
    if counts["unknown"]:
        print(f"  unknown    : {counts['unknown']}  (kept -- not treated as dead)")
    print(f"\nWrote: {STATUS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
