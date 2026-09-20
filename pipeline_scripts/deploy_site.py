#!/usr/bin/env python3
"""
deploy_site.py -- push berry_internships.html live to Netlify.

    python3 deploy_site.py              build is already done, just deploy it
    python3 deploy_site.py --check      show what's live vs what's on disk
    python3 deploy_site.py --site-id    print your site id and exit

WHY THIS EXISTS

build_site.py writes berry_internships.html to your Desktop and stops. Netlify
kept serving whatever was last dragged onto it, so the site sat two days and
fourteen listings behind the file on your own machine while every caption on
Instagram pointed at it.

This is the missing step. refresh.py calls it at the end, so a refresh now
scrapes, checks what closed, rebuilds the page AND puts it live.

HOW IT TALKS TO NETLIFY

No Node, no netlify-cli, no repo. Netlify's deploy API takes a list of files
and their SHA1s, tells you which ones it doesn't already have, and you upload
just those. One file, three calls:

    POST /sites/{id}/deploys   {"files": {"/index.html": sha1}}
    PUT  /deploys/{id}/files/index.html   <the bytes>
    GET  /deploys/{id}                    until state is "ready"

If the file hasn't changed since the last deploy, Netlify asks for nothing and
the whole thing takes a second.

ONE-TIME SETUP

1. Go to app.netlify.com, click your avatar, User settings, Applications,
   then "New access token" under Personal access tokens. Name it whatever.

2. Copy it into the .env file next to this script, on its own line:

       NETLIFY_TOKEN=nfp_xxxxxxxxxxxxxxxx
       NETLIFY_TOKEN_EXPIRES=2027-09-05

   Set an expiry on the token rather than "no expiration", and put that date
   in the second line. This script then warns you three weeks out, because an
   expiring token on an automated job fails the worst possible way -- the
   deploy stops and the site goes quietly stale, which is the exact problem
   this was written to fix.

That is the whole setup. The script finds the site by name on its own. If you
have several sites and it picks the wrong one, run --site-id, then pin it:

       NETLIFY_SITE_ID=1234abcd-...

.env is already in .gitignore. Do not paste that token anywhere else.
"""

import argparse
import hashlib
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

PAGE = os.path.join(HERE, "berry_internships.html")
ENV_FILE = os.path.join(HERE, ".env")
API = "https://api.netlify.com/api/v1"

# What the site is called. Netlify's own name for it, which is the bit before
# .netlify.app.
SITE_NAME = "internberry"

# Netlify serves the file at the path you give it, and a homepage has to be
# index.html. This is the mistake that makes a hand-drag look like it worked
# and then 404.
REMOTE_PATH = "/index.html"


# --- saying, afterwards, what happened ---------------------------------------
# refresh.py runs this step as optional, so a failed deploy leaves a green run
# and a site that quietly goes stale -- the exact failure this script exists to
# prevent, moved one level up. On GitHub the log is unreadable without signing
# in and expires anyway, so the outcome is written next to the publish outcome
# in status.json and rides home with the run's state commit.
STATUS = os.path.join(HERE, "status.json")
NOTE = []


def _redact(text):
    return re.sub(r"(nfp_[A-Za-z0-9_]{10,}|ghp_[A-Za-z0-9_]{10,}|IGA[A-Za-z0-9_-]{20,})",
                  "***", str(text))


def record(outcome, detail=""):
    import datetime, json
    try:
        data = json.load(open(STATUS, encoding="utf-8")) if os.path.exists(STATUS) else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    bits = [b for b in NOTE + [detail] if b]
    data["last_deploy"] = {
        "outcome": outcome,
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "detail": _redact(" | ".join(bits))[:700],
    }
    try:
        with open(STATUS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass          # never let bookkeeping be the thing that fails a deploy


def load_env():
    """Read .env. Values are never printed -- a token in a log is exactly as
    leaked as a token anywhere else."""
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def check_token_age(env):
    """Warn before the token dies, not after.

    A Netlify token with an expiry is the safer choice, but an expiring token
    on an automated job fails in the worst possible way: the deploy stops
    working and the site quietly goes stale, which is exactly the problem
    this script was written to fix. So the expiry date goes in .env next to
    the token and this says something while there is still time to act.
    """
    when = env.get("NETLIFY_TOKEN_EXPIRES")
    if not when:
        return
    from datetime import date, datetime
    try:
        d = datetime.strptime(when.strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"  ! NETLIFY_TOKEN_EXPIRES={when!r} isn't a date. "
              f"Use YYYY-MM-DD.")
        return
    left = (d - date.today()).days
    if left < 0:
        print(f"  ! The Netlify token expired {-left} days ago. That is why "
              f"this is failing.\n"
              f"    Make a new one at app.netlify.com -> User settings -> "
              f"Applications, and update both lines in .env.")
    elif left <= 21:
        print(f"  ! The Netlify token expires in {left} days "
              f"({d:%d %b %Y}). Replace it before then or the site stops "
              f"updating itself.")


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def find_site(token, env):
    """The site's id. Pinned in .env if you set it, otherwise looked up by
    name so there is nothing to configure."""
    pinned = env.get("NETLIFY_SITE_ID")
    if pinned:
        return pinned

    r = requests.get(f"{API}/sites", headers=headers(token),
                     params={"per_page": 100}, timeout=30)
    if r.status_code == 401:
        sys.exit("Netlify rejected the token.\n"
                 "Make a new one at app.netlify.com -> User settings -> "
                 "Applications -> New access token, and put it in .env as "
                 "NETLIFY_TOKEN=...")
    r.raise_for_status()
    sites = r.json()
    for s in sites:
        if s.get("name") == SITE_NAME or SITE_NAME in (s.get("url") or ""):
            return s["id"]
    names = ", ".join(s.get("name", "?") for s in sites[:10]) or "none"
    sys.exit(f"No site called {SITE_NAME!r} on this account.\n"
             f"Sites found: {names}\n"
             f"Either fix SITE_NAME at the top of this file, or put the id in "
             f".env as NETLIFY_SITE_ID=...")


def live_summary():
    """What the public site currently says, so --check can compare it against
    the file without you opening a browser."""
    try:
        html = requests.get(f"https://{SITE_NAME}.netlify.app/",
                            timeout=20).text
    except Exception as e:
        return f"couldn't reach the site ({type(e).__name__})"
    return summarise(html)


def summarise(html):
    n = re.search(r">\s*(\d{1,4})\s*<[^>]*>?\s*internships", html) \
        or re.search(r"(\d{1,4})\s+internships", html)
    d = re.search(r"updated\s+([0-9]{1,2}\s+\w+\s+[0-9]{4})", html, re.I)
    return (f"{n.group(1) if n else '?'} internships, "
            f"updated {d.group(1) if d else '?'}")


def deploy(token, site_id, body):
    digest = hashlib.sha1(body).hexdigest()

    NOTE.append(f"site={site_id[:8]}... sha1={digest[:10]}")
    print("  telling Netlify what we have...")
    r = requests.post(f"{API}/sites/{site_id}/deploys", headers=headers(token),
                      json={"files": {REMOTE_PATH: digest}}, timeout=60)
    if r.status_code not in (200, 201):
        sys.exit(f"  Netlify said no (HTTP {r.status_code}):\n  {r.text[:300]}")
    dep = r.json()
    need = dep.get("required", [])

    if digest in need:
        print(f"  uploading {len(body)/1000:.0f} KB...")
        u = requests.put(
            f"{API}/deploys/{dep['id']}/files{REMOTE_PATH}",
            headers={**headers(token),
                     "Content-Type": "application/octet-stream"},
            data=body, timeout=120)
        if u.status_code not in (200, 201):
            sys.exit(f"  upload failed (HTTP {u.status_code}):\n  {u.text[:300]}")
    else:
        # Netlify already had this exact file. Nothing changed since the last
        # deploy, which is a normal outcome, not a failure.
        print("  Netlify already had this exact file, nothing to upload")

    print("  waiting for it to go live", end="", flush=True)
    for _ in range(40):
        s = requests.get(f"{API}/deploys/{dep['id']}", headers=headers(token),
                         timeout=30).json()
        state = s.get("state")
        if state == "ready":
            print(" done")
            NOTE.append(f"deploy {s.get('id','?')} ready")
            return s
        if state == "error":
            sys.exit(f"\n  Netlify errored: {s.get('error_message')}")
        print(".", end="", flush=True)
        time.sleep(2)
    print("\n  still building. It will finish on its own, check "
          f"https://{SITE_NAME}.netlify.app/ in a minute.")
    return dep


def main():
    ap = argparse.ArgumentParser(description="Put the job board live.")
    ap.add_argument("--check", action="store_true",
                    help="compare live against the file, deploy nothing")
    ap.add_argument("--site-id", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(PAGE):
        sys.exit(f"No {os.path.basename(PAGE)} to deploy.\n"
                 "  python3 build_site.py")

    body = open(PAGE, "rb").read()
    env = load_env()
    token = env.get("NETLIFY_TOKEN")

    if args.check:
        print(f"  on disk: {summarise(body.decode('utf-8', 'ignore'))}")
        print(f"  live:    {live_summary()}")
        return 0

    if not token:
        sys.exit("No NETLIFY_TOKEN in .env.\n\n"
                 "One-time setup:\n"
                 "  1. app.netlify.com -> your avatar -> User settings\n"
                 "  2. Applications -> New access token\n"
                 "  3. add this line to .env next to this script:\n"
                 "       NETLIFY_TOKEN=nfp_...\n")

    check_token_age(env)
    site_id = find_site(token, env)
    if args.site_id:
        print(site_id)
        return 0

    NOTE.append("sent: " + summarise(body.decode("utf-8", "ignore")))
    print(f"\nDeploying {summarise(body.decode('utf-8', 'ignore'))}")
    deploy(token, site_id, body)
    print(f"\n  https://{SITE_NAME}.netlify.app/\n")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit as e:
        bad = e.code not in (0, None)
        record("failure" if bad else "ok",
               e.code if isinstance(e.code, str) else "")
        raise
    except Exception as e:                      # noqa: BLE001 -- record, then re-raise
        record("failure", f"{type(e).__name__}: {e}")
        raise
    record("ok" if code == 0 else "failure")
    sys.exit(code)
