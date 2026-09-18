#!/usr/bin/env python3
"""
upload_slides.py
=================
Puts a carousel's slides on the public web, so Instagram can fetch them.

WHY THIS EXISTS
---------------
You cannot upload an image file to Instagram. Meta's API only accepts a
public https:// URL, which it fetches itself. A JPEG sitting on your Desktop
is invisible to it. So the slides get pushed to a GitHub Pages site first,
and the publisher hands Meta those URLs.

    local file   →   git push   →   https://aayan2629.github.io/berry-slides/...
                                     ↑ this is what Instagram fetches

WHAT IT DOES
------------
1. Copies a carousel's .jpg slides into your local clone of berry-slides
2. Commits and pushes them
3. Waits until GitHub Pages has actually deployed them (this takes 30-90
   seconds and is the step people forget -- publishing before the URLs are
   live fails with a confusing Meta error)
4. Returns the public URLs, in slide order

ONE-TIME SETUP
--------------
Clone the repo next to this project:

    cd ~/Desktop/"job account "
    git clone https://github.com/Aayan2629/berry-slides.git

Then create a GitHub token so pushes can happen without you typing a
password (GitHub removed password auth for git):

    github.com → Settings → Developer settings → Personal access tokens
    → Tokens (classic) → Generate new token
    → tick the "repo" scope → generate → copy it

Put it in the .env file in this folder:

    GITHUB_TOKEN=ghp_xxxxxxxxxxxx

Never commit .env, and never paste that token into a chat.

USAGE
-----
    python3 upload_slides.py computer-science-software-engineering
"""

import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request

# Python from python.org ships without macOS's certificate store, so plain
# urllib HTTPS calls die with CERTIFICATE_VERIFY_FAILED. requests bundles
# its own certificates (via certifi) and just works -- the same fix already
# applied in get_backgrounds.py.
try:
    import requests
except ImportError:
    requests = None

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = None

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "queue_carousels")

GH_USER = "Aayan2629"
GH_REPO = "berry-slides"
GH_BRANCH = "main"

# We serve the slides straight from raw.githubusercontent.com rather than
# GitHub Pages.
#
# Pages needs to be enabled, then rebuilds the whole site on every push,
# which takes 20-90 seconds and failed outright the first time we tried it.
# raw.githubusercontent serves any file in a PUBLIC repo the instant the
# push lands -- no setup, no build step, no waiting -- and returns
# "content-type: image/jpeg", which is all Meta needs to fetch an image.
RAW_BASE = f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/{GH_BRANCH}"

# Kept in case you ever want Pages instead: set USE_PAGES = True.
PAGES_BASE = f"https://{GH_USER.lower()}.github.io/{GH_REPO}"
USE_PAGES = False

def _find_repo():
    """
    Find the local clone of berry-slides.

    Rather than hardcode one path (which was wrong the first time -- it
    looked INSIDE the job account folder when the clone is beside it on the
    Desktop), check the sensible places and use whichever actually exists.
    """
    candidates = [
        os.path.join(HERE, "..", "..", "..", GH_REPO),   # Desktop/berry-slides
        os.path.join(HERE, "..", "..", GH_REPO),         # inside job account
        os.path.expanduser(f"~/Desktop/{GH_REPO}"),
        os.path.expanduser(f"~/{GH_REPO}"),
    ]
    for c in candidates:
        c = os.path.abspath(c)
        if os.path.isdir(os.path.join(c, ".git")):
            return c
    return os.path.abspath(candidates[0])   # for the error message


REPO_DIR = _find_repo()

# How long to wait for Pages to deploy before giving up
DEPLOY_TIMEOUT = 60


def load_token():
    """Read GITHUB_TOKEN from .env without printing it anywhere."""
    env_path = os.path.join(HERE, ".env")
    if not os.path.exists(env_path):
        return None
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("GITHUB_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def git(*args, cwd=None):
    """Run a git command. Returns (ok, output)."""
    result = subprocess.run(["git", *args], cwd=cwd or REPO_DIR,
                            capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def wait_for_pages(url, timeout=DEPLOY_TIMEOUT):
    """
    Poll one URL until GitHub actually serves it.

    Even on the raw path this is worth doing -- a push has to land and
    propagate before the file is fetchable, and handing Meta a URL that
    404s produces an error message that won't explain itself. Raw usually
    passes on the first try; Pages took longer than 3 minutes and failed.
    """
    print(f"  checking the slides are reachable...", end="", flush=True)
    started = time.time()
    last_error = "no response"
    while time.time() - started < timeout:
        try:
            if requests is not None:
                status = requests.get(url, timeout=10).status_code
            else:
                with urllib.request.urlopen(url, timeout=10, context=_SSL) as r:
                    status = r.status
            if status == 200:
                print(f" live after {time.time() - started:.0f}s")
                return True
            last_error = f"HTTP {status}"
        except Exception as e:
            # Report WHY rather than printing anonymous dots. The first
            # version swallowed this, so a certificate problem on this Mac
            # looked identical to the file genuinely not being there.
            last_error = f"{type(e).__name__}: {str(e)[:90]}"
        print(".", end="", flush=True)
        time.sleep(5)
    print(f" TIMED OUT\n  last response was -> {last_error}")
    return False


def upload(carousel_name):
    src = os.path.join(QUEUE, carousel_name)
    if not os.path.isdir(src):
        raise SystemExit(f"No carousel called {carousel_name!r} in queue_carousels/")

    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        raise SystemExit(
            f"Can't find the berry-slides clone at:\n  {REPO_DIR}\n\n"
            'Clone it first:\n  cd ~/Desktop/"job account "\n'
            f"  git clone https://github.com/{GH_USER}/{GH_REPO}.git")

    slides = sorted(f for f in os.listdir(src) if f.lower().endswith(".jpg"))
    if not slides:
        raise SystemExit(f"No .jpg slides in {src} -- run build_carousels.py first.")

    # --- copy into the repo ---
    dest = os.path.join(REPO_DIR, "slides", carousel_name)
    os.makedirs(dest, exist_ok=True)
    for f in slides:
        shutil.copy2(os.path.join(src, f), os.path.join(dest, f))
    print(f"  copied {len(slides)} slides into the repo")

    # --- commit and push ---
    git("add", "-A")
    ok, out = git("commit", "-m", f"slides: {carousel_name}")
    if not ok and "nothing to commit" not in out:
        print(f"  ! commit problem: {out[:200]}")

    token = load_token()
    if token:
        # Push with the token embedded so this works unattended. The token
        # is never printed, and the remote URL isn't changed permanently.
        push_url = f"https://{token}@github.com/{GH_USER}/{GH_REPO}.git"
        ok, out = git("push", push_url, "main")
    else:
        ok, out = git("push")

    if not ok:
        safe = out.replace(token, "***") if token else out
        raise SystemExit(
            f"Push failed:\n{safe[:400]}\n\n"
            "Most likely no GITHUB_TOKEN in .env -- see the notes at the top "
            "of this file.")
    print("  pushed")

    base = PAGES_BASE if USE_PAGES else RAW_BASE
    urls = [f"{base}/slides/{carousel_name}/{f}" for f in slides]

    if not wait_for_pages(urls[0]):
        raise SystemExit(
            "GitHub didn't serve the slides in time.\n"
            "Check the repo is still PUBLIC (private repos won't serve raw "
            "files to Meta), then try again.\n"
            "Do NOT publish to Instagram until these URLs load in a browser.")

    return urls


def main():
    if len(sys.argv) < 2:
        available = sorted(os.listdir(QUEUE)) if os.path.isdir(QUEUE) else []
        raise SystemExit(
            "Usage: python3 upload_slides.py <carousel-name>\n\n"
            "Available:\n  " + "\n  ".join(available))

    name = sys.argv[1]
    print(f"Uploading: {name}")
    urls = upload(name)
    print(f"\n{len(urls)} slides live:\n")
    for i, u in enumerate(urls, start=1):
        print(f"  slide {i}: {u}")


if __name__ == "__main__":
    main()
