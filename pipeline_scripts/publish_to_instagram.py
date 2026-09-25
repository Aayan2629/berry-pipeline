#!/usr/bin/env python3
"""
publish_to_instagram.py
========================
Posts ONE carousel to Instagram, then records it so it never posts twice.

    python3 publish_to_instagram.py                    # next one due
    python3 publish_to_instagram.py --now              # ignore the 3-day gap
    python3 publish_to_instagram.py --dry-run          # show what WOULD post,
                                                       #   then open the dashboard
    python3 publish_to_instagram.py <carousel-name>    # a specific one

HOW PUBLISHING ACTUALLY WORKS
-----------------------------
Instagram never accepts an image file. You give Meta a public URL and Meta
fetches it. Publishing is three calls, in order:

  A. one "container" per slide      -> a staged, invisible image
  B. one carousel container          -> groups those, holds the caption
  C. publish                         -> the post appears

Containers expire 24 hours after creation, so all three happen in one run.

THE SCHEDULE
------------
Rather than trusting a 3-day timer, this is meant to run DAILY and decide
for itself whether enough days have passed. That survives your Mac being
asleep, restarts and missed runs -- a daily check that usually does nothing
beats a timer you have to trust.

WHICH CAROUSEL GOES NEXT
------------------------
The least recently posted category, so it rotates through them evenly
instead of hammering whichever has the most jobs. With ~10 carousels and a
3-day gap that's about a month of content per scrape, and the queue refills
faster than it drains.

SETUP -- put these in .env next to this script:

    IG_USER_ID=17841400000000000
    IG_ACCESS_TOKEN=IGQVJ...          long-lived, expires in 60 days
    IG_TOKEN_OBTAINED=2026-09-01      so it can warn you before it dies
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

from upload_slides import upload, QUEUE

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "posted_history.json")
ENV_FILE = os.path.join(HERE, ".env")

API = "https://graph.instagram.com/v21.0"

# One category per posting day. Architecture (Wednesday) and Medicine &
# Health (Sunday) joined in Sept 2026; Tuesday and Friday are the rest days,
# and where an overflow post lands when a category has more than five new
# listings. Monday is 0.
SCHEDULE = {
    0: "Technology, Data & AI",
    2: "Architecture",                 # built by side_categories/build_side_carousels.py
    3: "Business, Commerce, Marketing & Finance",
    5: "Engineering",
    6: "Medicine & Health",            # built by side_categories/build_side_carousels.py
}

# A category added to SCHEDULE only counts from its first real posting day.
# Without this, the day a new category goes live it looks "late" for the
# weekday that already went by before it existed.
SCHEDULE_START = {
    "Medicine & Health": "2026-09-27",   # first Sunday
    "Architecture": "2026-09-30",        # first Wednesday
}


def category_on(day):
    """The category scheduled for this date, or None (rest day, or a
    category that hadn't started yet on that date)."""
    category = SCHEDULE.get(day.weekday())
    start = SCHEDULE_START.get(category)
    if start and day.strftime("%Y-%m-%d") < start:
        return None
    return category
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


# The schedule above is in SYDNEY days. now() gives whatever clock
# the machine has: on the Mac that is Sydney, but on a GitHub runner it is
# UTC, and the cron fires at 21:20 UTC -- 7:20am the NEXT day in Sydney. Left
# alone, every post landed a day late: Monday's tech carousel went out Tuesday.
#
# Naive rather than timezone-aware on purpose. Every timestamp already in
# posted_history.json was written naive, and subtracting an aware datetime
# from a naive one raises TypeError.
SYDNEY = ZoneInfo("Australia/Sydney")


def now():
    """Sydney wall-clock time, as a naive datetime."""
    return datetime.now(SYDNEY).replace(tzinfo=None)

# When Meta refuses with "action is blocked" (subcode 2207051) the account is
# under a temporary restriction, and every further attempt while it is on makes
# it longer. The daily run is 24 hours apart so it is never affected; this only
# stops the back-to-back attempts that happen when someone is re-running the
# pipeline to fix something else. The block itself is still reported -- loudly
# -- it is just not poked at.
BLOCK_SUBCODE = "2207051"
BLOCK_COOLDOWN_HOURS = 6
# Its own file, not status.json: the workflow rewrites status.json at the start
# of every run, so anything recorded there is gone before the next run reads it.
# This one is only ever written here and rides home with the state commit.
BLOCK_FILE = os.path.join(HERE, "ig_block.json")


def note_block(detail):
    """Remember that Meta said no, so the next run does not ask again."""
    try:
        with open(BLOCK_FILE, "w", encoding="utf-8") as f:
            json.dump({"at": datetime.now(SYDNEY).isoformat(timespec="seconds"),
                       "subcode": BLOCK_SUBCODE,
                       "detail": str(detail)[:400]}, f, indent=2)
    except OSError:
        pass          # bookkeeping must never be the thing that breaks a run


def blocked_recently():
    """How long is left on a self-imposed cooldown, or None."""
    try:
        with open(BLOCK_FILE, encoding="utf-8") as f:
            when = datetime.fromisoformat(json.load(f)["at"])
    except Exception:
        return None
    when = when.replace(tzinfo=None)
    left = timedelta(hours=BLOCK_COOLDOWN_HOURS) - (now() - when)
    return left if left.total_seconds() > 0 else None


# How far back to look for a category whose leftover parts still need posting.
# Two days covers "Finance had 12 new roles on Thursday, so parts 2 and 3 go
# out Friday and Saturday".
OVERFLOW_LOOKBACK_DAYS = 2

POSTED_JOBS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "posted_jobs.json")

# Meta's own limits, worth failing loudly on rather than discovering live
MAX_CAROUSEL_ITEMS = 10
TOKEN_LIFETIME_DAYS = 60
WARN_TOKEN_AT_DAYS = 50


def load_env():
    """Read .env. Values are never printed -- a leaked token in a log is
    exactly as bad as a leaked token anywhere else."""
    if not os.path.exists(ENV_FILE):
        sys.exit(f"No .env file at {ENV_FILE}\nSee the notes at the top of this file.")
    env = {}
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def check_token_age(env):
    """Long-lived tokens die after 60 days and nothing renews them
    automatically. This is the failure that silently kills the account."""
    obtained = env.get("IG_TOKEN_OBTAINED")
    if not obtained:
        return
    try:
        age = (now() - datetime.fromisoformat(obtained)).days
    except ValueError:
        return
    left = TOKEN_LIFETIME_DAYS - age
    if left <= 0:
        sys.exit(f"Your Instagram token expired {-left} days ago. Generate a new "
                 "one and update IG_ACCESS_TOKEN and IG_TOKEN_OBTAINED in .env.")
    if age >= WARN_TOKEN_AT_DAYS:
        print(f"  !! token expires in {left} days -- refresh it soon\n")


def load_history():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {"posts": []}


def save_history(h):
    json.dump(h, open(STATE_FILE, "w", encoding="utf-8"), indent=2)


def days_since_last_post(history):
    if not history["posts"]:
        return None
    last = max(p["posted_at"] for p in history["posts"])
    return (now() - datetime.fromisoformat(last)).days


def carousels_for(category):
    """Every carousel folder belonging to a category, lowest part first."""
    out = []
    if not os.path.isdir(QUEUE):
        return []
    for name in sorted(os.listdir(QUEUE)):
        d = os.path.join(QUEUE, name)
        meta = os.path.join(d, "meta.json")
        if not os.path.isdir(d) or not os.path.exists(meta):
            continue
        try:
            with open(meta, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("category") == category:
            out.append((m.get("part", 1), name))
    return [name for _, name in sorted(out)]


def pick_for_today(today=None):
    """
    The carousel due today, or None.

    Today's category comes first. If today has no category -- or that
    category has nothing waiting -- we look back a couple of days for a
    category that still has parts left over, which is how a category with
    more than five new listings spills onto the following day.
    """
    today = today or now()
    for back in range(OVERFLOW_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=back)
        category = category_on(day)
        if not category:
            continue
        waiting = carousels_for(category)
        if waiting:
            return waiting[0], category, back
    return None, None, 0


def record_posted_jobs(carousel):
    """Add this carousel's listings to posted_jobs.json so build_carousels.py
    never puts them in a post again."""
    meta = os.path.join(QUEUE, carousel, "meta.json")
    try:
        with open(meta, encoding="utf-8") as f:
            ids = [str(i) for i in json.load(f).get("job_ids", [])]
    except (OSError, ValueError):
        print("  (no meta.json -- couldn't record which jobs went out)")
        return
    try:
        with open(POSTED_JOBS_FILE, encoding="utf-8") as f:
            known = {str(i) for i in json.load(f)}
    except (OSError, ValueError):
        known = set()
    known.update(ids)
    with open(POSTED_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(known), f, indent=2)
    print(f"  recorded {len(ids)} listing(s) as posted")


def retire(carousel):
    """Move a posted carousel out of the queue. Kept rather than deleted so
    you can look back at what went out."""
    done = os.path.join(os.path.dirname(QUEUE.rstrip("/")), "posted_carousels")
    os.makedirs(done, exist_ok=True)
    src = os.path.join(QUEUE, carousel)
    dst = os.path.join(done, carousel)
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(done, f"{carousel}-{n}")
        n += 1
    try:
        os.rename(src, dst)
        print(f"  moved out of the queue -> posted_carousels/{os.path.basename(dst)}")
    except OSError as e:
        print(f"  !! couldn't move {carousel} out of the queue: {e}\n"
              f"     Move it yourself or it may be posted again.")


# Meta hands back HTTP 500 with "is_transient": true more often than you would
# like. It is their side, not yours, and the reply literally asks you to retry.
# Without this, one flaky second kills the whole post -- and on an unattended
# daily run that is a silently missed day nobody notices until Thursday.
RETRY_WAITS = (5, 15, 40)          # seconds to wait before each retry


def _worth_retrying(status, detail):
    """Their problem rather than ours, so trying again might work."""
    if status == 0:                          # never reached them at all
        return True
    if status >= 500 or status == 429:       # their error, or rate limited
        return True
    return '"is_transient":true' in (detail or "").replace(" ", "")


def _call(method, path, params, what, allow_fail=False):
    """One call to Meta, retried while the failure looks transient, with the
    token kept out of every error message."""
    for attempt in range(len(RETRY_WAITS) + 1):
        status, detail = 0, ""
        try:
            if method == "post":
                r = requests.post(f"{API}/{path}", data=params, timeout=60)
            else:
                # A GET puts the token in the URL, and requests puts the URL
                # in every exception it raises -- so an ordinary network blip
                # would print your access token across the terminal. Hence the
                # bare exception name below and nothing else.
                r = requests.get(f"{API}/{path}", params=params, timeout=60)
            status = r.status_code
            if status == 200:
                return r.json()
            detail = r.text
            if "access_token" in params:
                detail = detail.replace(params["access_token"], "***")
        except requests.exceptions.RequestException as e:
            detail = type(e).__name__

        if attempt < len(RETRY_WAITS) and _worth_retrying(status, detail):
            wait = RETRY_WAITS[attempt]
            print(f"  {what}: {'no reply' if not status else f'HTTP {status}'}"
                  f" -- looks transient, retrying in {wait}s"
                  f" ({attempt + 1}/{len(RETRY_WAITS)})")
            time.sleep(wait)
            continue

        if allow_fail:
            return {"_error": detail[:500], "_http": status}
        if status == 0:
            sys.exit(f"\n{what} failed: couldn't reach Instagram "
                     f"({detail}). Check you are online.")
        sys.exit(f"\n{what} failed (HTTP {status}):\n{detail[:500]}")


def api_post(path, params, what, allow_fail=False):
    return _call("post", path, params, what, allow_fail)


def api_get(path, params, what):
    return _call("get", path, params, what)


def wait_ready(container_id, token, label, timeout=180):
    """Block until Meta has finished processing a container.

    Creating a container only queues the work: Meta then goes and fetches
    every image from the repo, and until that finishes the container cannot
    be published. Calling media_publish before then is what produces

        code 9007 / subcode 2207027 -- "The media is not ready to be
        published. Please wait a moment."

    which is not a real failure, just an impatient one. So ask for the
    container's status until it says FINISHED.
    """
    waited, step = 0, 2
    while waited < timeout:
        st = api_get(container_id,
                     {"fields": "status_code,status", "access_token": token},
                     f"Checking {label}")
        code = st.get("status_code", "")
        if code == "FINISHED":
            return True
        if code in ("ERROR", "EXPIRED"):
            sys.exit(f"\n  Meta gave up on {label}: {code}\n"
                     f"  {st.get('status', '')}\n"
                     f"  The slide images are probably not reachable. Check "
                     f"the repo is public and the URLs load in a browser.")
        time.sleep(step)
        waited += step
        step = min(step + 1, 8)      # ease off rather than hammer
        print(f"    still processing {label}... ({waited}s)")
    sys.exit(f"\n  {label} was still not ready after {timeout}s. "
             f"Nothing was posted -- run the command again.")


def _went_out_anyway(user_id, token, caption):
    """Meta sometimes publishes the post AND answers with an error (this
    happened on 23 Sep: posted at 9:46:04, "action is blocked" at 9:46:10).
    Treating that as a failure is dangerous -- the carousel stays in the
    queue and gets posted a second time. So before giving up, ask Instagram
    for the newest posts and look for ours.

    Returns the post id if it is there, else None. Never raises: if even
    this check fails we fall back to the old behaviour (report the error)."""
    first_line = (caption or "").strip().splitlines()[0][:60] if caption else ""
    for wait in (5, 15, 30):          # give Instagram a moment to list it
        time.sleep(wait)
        try:
            r = requests.get(f"{API}/{user_id}/media",
                             params={"fields": "id,caption,timestamp",
                                     "limit": 5, "access_token": token},
                             timeout=30)
            if r.status_code != 200:
                continue
            for m in r.json().get("data", []):
                when = datetime.strptime(m["timestamp"][:19], "%Y-%m-%dT%H:%M:%S")
                fresh = datetime.utcnow() - when < timedelta(minutes=15)
                same = first_line and (m.get("caption") or "").strip().startswith(first_line)
                if fresh and same:
                    return m["id"]
        except Exception:
            pass
    return None


def _listing_ids(text):
    """Every long run of digits in a caption -- the Seek/LinkedIn job ids.
    re.findall is like a loop of sscanf in C: pull out every match."""
    import re
    return set(re.findall(r"\d{7,}", text or ""))


def _already_on_instagram(user_id, token, caption, days=21):
    """The post id if a post from the last `days` days already carries most of
    this carousel's job links, else None.

    This is the duplicate guard. It asks Instagram itself rather than trusting
    posted_history.json, because the history file is exactly what went wrong
    on 20-23 Sep: Meta posted, answered with an error, nothing was written
    down, and the same carousel went out three times. Matching on the job
    ids (not the caption text) means a NEW carousel with the same heading,
    e.g. "6 Technology, Data & AI (part 1)", is still allowed."""
    from datetime import timezone
    ours = _listing_ids(caption)
    if not ours:
        return None
    try:
        r = requests.get(f"{API}/{user_id}/media",
                         params={"fields": "id,caption,timestamp", "limit": 25,
                                 "access_token": token}, timeout=30)
        if r.status_code != 200:
            return None
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        for m in r.json().get("data", []):
            when = datetime.strptime(m["timestamp"][:19], "%Y-%m-%dT%H:%M:%S")
            if now_utc - when > timedelta(days=days):
                continue
            overlap = len(ours & _listing_ids(m.get("caption")))
            if overlap >= max(1, len(ours) // 2):     # half or more of our jobs
                return m["id"]
    except Exception:
        pass
    return None


def publish(carousel, env, dry_run=False):
    folder = os.path.join(QUEUE, carousel)
    caption_path = os.path.join(folder, "caption.txt")
    caption = open(caption_path, encoding="utf-8").read().strip() if \
        os.path.exists(caption_path) else ""

    print(f"Carousel: {carousel}")

    if not dry_run:
        dup = _already_on_instagram(env["IG_USER_ID"], env["IG_ACCESS_TOKEN"], caption)
        if dup:
            print(f"  These jobs are already on Instagram (post {dup}).")
            print("  Not posting them again -- recording it as posted instead.")
            return dup

    print("  putting slides online...")
    urls = upload(carousel)

    if len(urls) > MAX_CAROUSEL_ITEMS:
        sys.exit(f"{len(urls)} slides -- Instagram allows {MAX_CAROUSEL_ITEMS} max.")

    if dry_run:
        print(f"\n  DRY RUN -- nothing was posted.")
        print(f"  would post {len(urls)} slides with this caption:\n")
        print("  " + caption.replace("\n", "\n  ")[:600])
        return None

    user_id = env["IG_USER_ID"]
    token = env["IG_ACCESS_TOKEN"]

    # --- A. one container per slide ---
    print(f"  staging {len(urls)} slides with Meta...")
    children = []
    for i, url in enumerate(urls, start=1):
        res = api_post(f"{user_id}/media", {
            "image_url": url,
            "is_carousel_item": "true",
            "access_token": token,
        }, f"Staging slide {i}")
        children.append(res["id"])
        print(f"    slide {i} ok")
        time.sleep(1)          # be gentle; Meta rate-limits bursts

    # Each slide is a container too, and each one has to finish downloading
    # before the carousel that holds them can be built.
    print("  waiting for Meta to fetch the slides...")
    for i, cid in enumerate(children, start=1):
        wait_ready(cid, token, f"slide {i}")

    # --- B. the carousel container ---
    print("  grouping them into a carousel...")
    carousel_res = api_post(f"{user_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption,
        "access_token": token,
    }, "Creating the carousel")

    wait_ready(carousel_res["id"], token, "the carousel")

    # --- C. publish ---
    print("  publishing...")
    for attempt in range(1, 6):
        published = api_post(f"{user_id}/media_publish", {
            "creation_id": carousel_res["id"],
            "access_token": token,
        }, "Publishing", allow_fail=True)
        if "_error" not in published:
            return published.get("id")
        # 2207027 is "not ready yet" and is worth another go; anything else
        # is a real error and should stop here rather than be retried blind.
        if "2207027" not in published["_error"] or attempt == 5:
            print("  Meta said no -- checking whether it went out anyway...")
            real_id = _went_out_anyway(user_id, token, caption)
            if real_id:
                print(f"  It DID go out (post {real_id}). Recording it as posted "
                      "so it is never posted twice.")
                return real_id
            if BLOCK_SUBCODE in published["_error"]:
                note_block(published["_error"])
            sys.exit(f"\nPublishing failed (HTTP {published['_http']}):\n"
                     f"{published['_error']}")
        print(f"    not ready yet, waiting... (attempt {attempt})")
        time.sleep(5 * attempt)

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carousel", nargs="?", default=None)
    ap.add_argument("--now", action="store_true",
                    help="post the next thing due, ignoring today's schedule")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be posted, post nothing")
    ap.add_argument("--category", default=None,
                    help="post the next waiting carousel for a category, "
                         "ignoring today's schedule. Matches loosely: "
                         '"data sci", "comp sci", "finance", "eng"')
    ap.add_argument("--schedule", action="store_true",
                    help="print the posting week and what is waiting")
    args = ap.parse_args()

    if args.schedule:
        print("Posting week:\n")
        for i, day in enumerate(DAY_NAMES):
            cat = SCHEDULE.get(i)
            if cat:
                waiting = carousels_for(cat)
                extra = (f"{len(waiting)} waiting" if waiting
                         else "nothing waiting")
                print(f"  {day:<10} {cat}  ({extra})")
            else:
                print(f"  {day:<10} -- rest day (or overflow from the day before)")
        return 0

    env = load_env()
    if not args.dry_run:
        for key in ("IG_USER_ID", "IG_ACCESS_TOKEN"):
            if key not in env:
                sys.exit(f"{key} missing from .env")
        check_token_age(env)

    history = load_history()

    if args.category:
        # Loose match, so you never have to type a whole category name.
        want = args.category.lower().split()
        hits = [c for c in SCHEDULE.values()
                if all(any(w in word for word in c.lower().replace(",", " ").split())
                       for w in want)]
        if not hits:
            sys.exit(f"No category matches {args.category!r}. Try one of:\n  "
                     + "\n  ".join(sorted(set(SCHEDULE.values()))))
        if len(hits) > 1:
            sys.exit(f"{args.category!r} matches more than one:\n  "
                     + "\n  ".join(hits) + "\nBe a bit more specific.")
        category = hits[0]
        waiting = carousels_for(category)
        if not waiting:
            print(f"Nothing waiting for {category}.")
            return 0
        carousel, back = waiting[0], 0
        print(f"{category} -- {len(waiting)} waiting, posting {carousel}\n")
    elif args.carousel:
        # Read the category off the carousel itself rather than leaving it
        # None. Posting one by name used to record a null in the history,
        # which the dashboard then tried to print and crashed on.
        carousel, back = args.carousel, 0
        category = None
        try:
            with open(os.path.join(QUEUE, carousel, "meta.json"),
                      encoding="utf-8") as f:
                category = json.load(f).get("category")
        except (OSError, ValueError):
            pass
        category = category or "Unknown"
    else:
        # Only the unattended path backs off. Asking for a post by name, by
        # category or with --now is a person deciding to try anyway, and that
        # is their call to make.
        left = blocked_recently()
        if left is not None and not args.now and not args.dry_run:
            mins = int(left.total_seconds() // 60)
            print(f"Instagram blocked the last publish (subcode {BLOCK_SUBCODE}). "
                  f"Every attempt while a block is on extends it, so this run is "
                  f"leaving it alone for another {mins // 60}h {mins % 60}m.")
            print("Nothing has been lost -- the carousel stays in the queue and "
                  "goes out on the next run once the block lifts.")
            return 0
        carousel, category, back = pick_for_today()
        if not carousel and args.now:
            # --now: post whatever is waiting, whatever day it is
            for cat in SCHEDULE.values():
                waiting = carousels_for(cat)
                if waiting:
                    carousel, category, back = waiting[0], cat, 0
                    break
        if not carousel:
            today = DAY_NAMES[now().weekday()]
            due = SCHEDULE.get(now().weekday())
            if due:
                print(f"{today} is {due} day, but there is nothing waiting "
                      f"in the queue for it.")
                print("Scrape and rebuild, or use --now to post another "
                      "category early.")
            else:
                print(f"{today} is a rest day and nothing is left over from "
                      f"the day before. Nothing to do.")
            return 0

    if back:
        print(f"(overflow: {category} had more than one carousel, "
              f"posting the next part today)\n")

    if args.dry_run:
        # A dry run is the moment you are looking at what is about to go out,
        # so it is also the right moment to refresh the public job board --
        # the post and the site should never disagree about what is open.
        print("Rebuilding the job board first...")
        try:
            import build_site
            rows, _ = build_site.collect()
            with open(build_site.OUT, "w", encoding="utf-8") as f:
                f.write(build_site.build(rows))
            print(f"  {len(rows)} internship(s) -> "
                  f"{os.path.basename(build_site.OUT)}")
        except Exception as e:
            # Never let a site problem look like a publishing problem.
            print(f"  !! couldn't rebuild the site: {e}")
            print("     Run  python3 build_site.py  on its own to see why.")

    if args.dry_run:
        # A dry run is you asking "what is about to go out?", so this is the
        # moment to put the whole picture in front of you: how many posts are
        # due, whether any are late, what every slide actually looks like,
        # and the command for each one.
        #
        # The import sits here rather than at the top of the file because
        # dashboard.py imports THIS file for the schedule. Importing it up
        # there would be a circular import; down here it is resolved by the
        # time it runs.
        try:
            import dashboard
            n = dashboard.build_and_open()
            print(f"\n  Dashboard opened -- {n} post(s) due today.")
        except Exception as e:
            # A dashboard problem must never look like a publishing problem.
            print(f"\n  !! couldn't open the dashboard: {e}")
            print("     Run  python3 dashboard.py  on its own to see why.")

    post_id = publish(carousel, env, dry_run=args.dry_run)

    if post_id:
        history["posts"].append({
            "carousel": carousel,
            "category": category or "Unknown",
            "posted_at": now().isoformat(timespec="seconds"),
            "media_id": post_id,
        })
        save_history(history)
        record_posted_jobs(carousel)
        retire(carousel)
        print(f"\n  LIVE -- https://www.instagram.com/berry.internships.syd/")
        print(f"  media id: {post_id}")

        nxt = now() + timedelta(days=1)
        for _ in range(7):
            if SCHEDULE.get(nxt.weekday()):
                print(f"  next scheduled: {nxt.strftime('%a %d %b')} "
                      f"-- {SCHEDULE[nxt.weekday()]}")
                break
            nxt += timedelta(days=1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
