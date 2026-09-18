#!/usr/bin/env python3
"""
ig_sync.py -- ask Instagram what is actually on the account, and fix the
local files to match.

    python3 ig_sync.py              reconcile: queue, history, posted jobs
    python3 ig_sync.py --dry-run    show what it would do, change nothing
    python3 ig_sync.py --list       just print the last posts on the account

WHY THIS EXISTS

Every other script here assumes that the only way a post reaches Instagram
is publish_to_instagram.py. That script writes down what it posted, moves
the carousel out of the queue, and marks its listings as used.

The moment you post from your phone instead, none of that happens. The
carousel stays in the queue, so the dashboard keeps telling you it is due.
The listings never get marked as posted, so build_carousels.py cheerfully
puts the same six jobs in a future carousel. And the count on the dashboard
quietly drifts below the real one.

That is exactly what happened: the account is ahead of posted_history.json,
and the dashboard has no way to know because it never asks Instagram
anything. So now it asks.

HOW IT MATCHES A POST TO A CAROUSEL

Not by caption text. You edit captions, Instagram mangles whitespace, and
the emoji do not always survive a round trip.

Every caption this pipeline writes carries the job links:

    2  SG Fleet2027 Internship- Data & Analytics
       seek.com.au/job/94421949

So the fingerprint is the LISTING IDS in the caption. Pull every long run of
digits out of an Instagram caption, pull the same out of a carousel's
meta.json, and if most of them line up it is that carousel. Links are the
one part of a caption nobody rewrites, which makes them the only part worth
matching on.

WHAT IT CHANGES

For a queued carousel that turns out to be live already:

    posted_history.json   gains the post, dated from Instagram's own
                          timestamp, tagged so you can see it was
                          reconciled rather than posted by the script
    posted_jobs.json      gains its listings, so they never come back
    queue_carousels/      the folder moves to posted_carousels/

It only ever adds. It will not delete a post from Instagram, and it will not
remove anything from your history -- the API only hands back the most recent
posts, so "not in the list" never means "not posted".

ig_posts.json is written every run and is what the dashboard reads, so the
dashboard can show the real account instead of only what it hoped happened.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

# Borrowed rather than copied. One copy of the token handling, one copy of
# the retire/record logic, so a fix in one place is a fix everywhere.
from publish_to_instagram import (
    API, QUEUE, load_env, check_token_age, load_history, save_history,
    record_posted_jobs, retire,
)

CACHE_FILE = os.path.join(HERE, "ig_posts.json")

# How many posts back to ask for. The account posts about four times a week,
# so 50 is roughly three months of history -- far more than enough to catch
# "I posted this one from my phone an hour ago", which is the whole job.
FETCH_LIMIT = 50

# A listing id is a long run of digits. Seek uses 8, LinkedIn uses 10.
# Seven is low enough to catch every board and high enough that a year, a
# count or a date in a caption never looks like one.
MIN_ID_DIGITS = 7

# How much of a carousel's listings have to appear in a caption before it is
# the same post. Not 100%: you might delete a line from a caption, or a
# listing might have closed and been edited out. Two thirds is comfortably
# past coincidence -- two unrelated posts sharing four listing ids does not
# happen.
MATCH_RATIO = 0.66


def ids_in(text):
    """Every listing id mentioned in a blob of text.

    Works on both an Instagram caption and a meta.json job id, which is why
    it is digits rather than a URL pattern -- meta.json stores LinkedIn jobs
    as 'js-https-www-linkedin-com-jobs-view-4462160397' while the caption
    stores them as 'linkedin.com/jobs/view/4462160397'. The number is the
    part both spellings agree on.
    """
    return {m for m in re.findall(r"\d{%d,}" % MIN_ID_DIGITS, text or "")}


def fetch_posts(user_id, token, limit=FETCH_LIMIT):
    """The account's recent posts, newest first.

    The try/except is not decoration. requests puts the full URL in the
    exception it raises, and the token is a query parameter, so an ordinary
    "no internet" error prints your access token across the terminal in
    plain text. Catching it and printing our own message is the difference
    between a network blip and a token you now have to rotate.
    """
    try:
        r = requests.get(
            f"{API}/me/media",
            params={"fields": "id,caption,timestamp,permalink,media_type",
                    "limit": limit, "access_token": token},
            timeout=60)
    except requests.exceptions.RequestException as e:
        # Never let the original exception text out: it contains the token.
        sys.exit(f"Couldn't reach Instagram ({type(e).__name__}).\n"
                 "Check you are online and try again.")
    if r.status_code != 200:
        detail = r.text.replace(token, "***")
        if r.status_code in (190, 401) or "expired" in detail.lower():
            sys.exit("Instagram rejected the token -- it has probably "
                     "expired.\nGet a fresh one and update IG_ACCESS_TOKEN "
                     "in .env.")
        sys.exit(f"Couldn't read the account (HTTP {r.status_code}):\n"
                 f"{detail[:400]}")
    return r.json().get("data", [])


def queued_carousels():
    """(name, category, set-of-listing-ids) for everything still waiting."""
    out = []
    if not os.path.isdir(QUEUE):
        return out
    for name in sorted(os.listdir(QUEUE)):
        meta_path = os.path.join(QUEUE, name, "meta.json")
        if not os.path.exists(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        ids = set()
        for jid in meta.get("job_ids", []):
            ids |= ids_in(str(jid))
        out.append((name, meta.get("category") or "Unknown", ids))
    return out


def best_match(carousel_ids, posts):
    """The post whose caption carries these listings, or None.

    Returns (post, how_many_matched) so the caller can print why.
    """
    if not carousel_ids:
        return None, 0
    best, best_n = None, 0
    for p in posts:
        hits = len(carousel_ids & ids_in(p.get("caption")))
        if hits > best_n:
            best, best_n = p, hits
    if best_n >= max(2, round(len(carousel_ids) * MATCH_RATIO)):
        return best, best_n
    return None, best_n


def when(post):
    """Instagram's timestamp as a plain local-ish ISO string, to match what
    publish_to_instagram.py writes. Meta sends '2026-09-07T09:14:22+0000'."""
    ts = (post.get("timestamp") or "").replace("+0000", "+00:00")
    try:
        return datetime.fromisoformat(ts).replace(tzinfo=None).isoformat(
            timespec="seconds")
    except ValueError:
        return datetime.now().isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(
        description="Make the local files agree with the actual account.")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what it would change, change nothing")
    ap.add_argument("--list", action="store_true", dest="just_list",
                    help="print recent posts and stop")
    ap.add_argument("--limit", type=int, default=FETCH_LIMIT)
    args = ap.parse_args()

    env = load_env()
    check_token_age(env)
    user_id, token = env.get("IG_USER_ID"), env.get("IG_ACCESS_TOKEN")
    if not user_id or not token:
        sys.exit("IG_USER_ID and IG_ACCESS_TOKEN both need to be in .env")

    print("\nASKING INSTAGRAM")
    posts = fetch_posts(user_id, token, args.limit)
    print(f"  {len(posts)} post(s) on the account")

    # Cache first, so the dashboard has the real numbers even if the
    # reconcile below finds nothing to do.
    if not args.dry_run:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": datetime.now().isoformat(
                timespec="seconds"), "posts": posts}, f, indent=2)

    if args.just_list:
        print()
        for p in posts[:25]:
            head = (p.get("caption") or "").splitlines()
            head = head[0][:64] if head else "(no caption)"
            print(f"  {when(p)[:16]}  {p.get('media_type','?'):<14} {head}")
        print()
        return 0

    # ---- reconcile ---------------------------------------------------------
    history = load_history()
    known_ids = {p.get("media_id") for p in history.get("posts", [])}

    print("\nCHECKING THE QUEUE AGAINST THE ACCOUNT")
    queue = queued_carousels()
    if not queue:
        print("  nothing in the queue")
    fixed = 0

    for name, category, ids in queue:
        post, hits = best_match(ids, posts)
        if not post:
            note = f"  {name}: not on the account yet"
            if hits:
                note += f"  ({hits} of {len(ids)} listings matched, not enough)"
            print(note)
            continue

        mid = post.get("id")
        print(f"\n  {name}")
        print(f"    already on Instagram: {hits} of {len(ids)} listings match")
        print(f"    posted {when(post)}  {post.get('permalink','')}")

        if args.dry_run:
            print("    (dry run, nothing changed)")
            fixed += 1
            continue

        if mid not in known_ids:
            history.setdefault("posts", []).append({
                "carousel": name,
                "category": category,
                "posted_at": when(post),
                "media_id": mid,
                # So a future you can tell the difference between "the script
                # posted this" and "the script found this after the fact".
                "source": "reconciled from Instagram",
                "permalink": post.get("permalink", ""),
            })
            known_ids.add(mid)
            print("    added to posted_history.json")

        record_posted_jobs(name)
        retire(name)
        fixed += 1

    if not args.dry_run and fixed:
        history["posts"].sort(key=lambda p: p.get("posted_at", ""))
        save_history(history)

    print()
    if fixed:
        print(f"  {fixed} carousel(s) were already live and have been "
              f"filed properly.")
        print("  Refresh the dashboard to see it:")
        print("    python3 dashboard.py")
    else:
        print("  Everything already agrees. Nothing to fix.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
