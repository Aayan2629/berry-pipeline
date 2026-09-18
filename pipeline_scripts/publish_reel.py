#!/usr/bin/env python3
"""
publish_reel.py -- post ONE video to Instagram as a reel.

    python3 publish_reel.py ~/Desktop/"job account "/"Claude outputs"/berry_ad_reel.mp4
    python3 publish_reel.py <video.mp4> --dry-run       check everything, post nothing
    python3 publish_reel.py <video.mp4> --caption-file cap.txt
    python3 publish_reel.py <video.mp4> --yes           skip the confirm prompt

WHY THIS IS A SEPARATE SCRIPT

publish_to_instagram.py posts carousels. A reel is a different media type
with a different upload path: Meta has to download and TRANSCODE the video
before it can be published, which takes a minute or two rather than the few
seconds an image takes, and the container has to be polled until it says
FINISHED. Bolting that onto the carousel publisher would have meant two
different flows sharing one set of guard rails, and the guard rails there
are the part worth keeping intact.

Everything else is borrowed rather than copied -- the .env reading, the git
push, the URL check, the container polling all come straight out of your
existing scripts, so there is only one copy of each to keep correct.

HOW IT WORKS, WHICH IS THE SAME AS THE SLIDES

Instagram never accepts a file. You give Meta a public https:// URL and Meta
fetches it. So:

    berry_ad_reel.mp4  ->  git push  ->  raw.githubusercontent.com/...  ->  Meta

Then three calls: create the container, wait for Meta to finish transcoding,
publish.

WHAT IT WILL NOT DO

It will not post without asking you first, and it records what it posted so
running it twice cannot put the same video up twice. Pass --yes only once
you have watched the thing.

THE CAPTION

Put it in a .txt file next to the video with the same name
(berry_ad_reel.txt), or pass --caption-file. Typing a caption straight into
the terminal mangles emoji and eats quote marks, which is a miserable way to
find out your caption posted wrong.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

# Borrowed wholesale. If you change how pushing or polling works, change it
# in those files and this follows.
from upload_slides import git, load_token, wait_for_pages, REPO_DIR, \
    GH_USER, GH_REPO, GH_BRANCH, RAW_BASE
from publish_to_instagram import load_env, api_post, api_get, wait_ready, \
    check_token_age, API

POSTED_FILE = os.path.join(HERE, "posted_reels.json")

# Meta's published limits for reels. Worth failing on here rather than
# finding out after a two minute transcode.
MAX_BYTES = 1_000_000_000        # 1 GB
MIN_SECONDS = 3
MAX_SECONDS = 15 * 60

# Video transcode takes far longer than an image fetch. The carousel
# publisher waits 180s, which is generous for a JPEG and tight for an mp4.
TRANSCODE_TIMEOUT = 420


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def probe(path):
    """(seconds, width, height, vcodec, acodec) via ffprobe, or None.

    Optional on purpose. ffprobe catches the two mistakes that otherwise
    cost you a two minute upload and a useless error from Meta -- a video
    that is silently the wrong codec, or one under three seconds -- but the
    script still runs without it.
    """
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,width,height:format=duration",
             "-of", "json", path],
            capture_output=True, text=True, check=True).stdout
        d = json.loads(out)
        dur = float(d.get("format", {}).get("duration", 0))
        v = next((s for s in d["streams"] if s.get("codec_type") == "video"), {})
        a = next((s for s in d["streams"] if s.get("codec_type") == "audio"), {})
        return (dur, v.get("width"), v.get("height"),
                v.get("codec_name"), a.get("codec_name"))
    except Exception:
        return None


def check_video(path):
    """Fail loudly and specifically, before anything is pushed anywhere."""
    if not os.path.isfile(path):
        sys.exit(f"No file at {path}")
    if not path.lower().endswith((".mp4", ".mov")):
        sys.exit("Instagram wants an .mp4. Convert it first:\n"
                 f"  ffmpeg -i {os.path.basename(path)} -c:v libx264 -c:a aac "
                 "-pix_fmt yuv420p out.mp4")

    size = os.path.getsize(path)
    if size > MAX_BYTES:
        sys.exit(f"{size/1e6:.0f} MB is over Meta's 1 GB limit.")
    print(f"  {os.path.basename(path)}  {size/1e6:.1f} MB")

    info = probe(path)
    if info is None:
        print("  (no ffprobe, skipping the format check)")
        return
    dur, w, h, vc, ac = info
    print(f"  {dur:.1f}s  {w}x{h}  {vc}/{ac or 'no audio'}")

    if dur < MIN_SECONDS:
        sys.exit(f"{dur:.1f}s is under Instagram's {MIN_SECONDS}s minimum.")
    if dur > MAX_SECONDS:
        sys.exit(f"{dur/60:.1f} min is over the 15 minute limit.")
    if vc != "h264":
        print(f"  ! video is {vc}, not h264. Meta usually copes but may reject it.")
    if ac and ac != "aac":
        print(f"  ! audio is {ac}, not aac. Same caveat.")
    if w and h and abs(w / h - 9 / 16) > 0.02:
        # Not fatal: Instagram will letterbox or crop. Worth saying out loud
        # because a 4:5 file posted as a reel comes out with grey bars.
        print(f"  ! {w}x{h} is not 9:16. It will be cropped or letterboxed.")


# ---------------------------------------------------------------------------
# Getting the file onto the public web
# ---------------------------------------------------------------------------
def push_video(path):
    """Copy into the berry-slides clone, push, and return the raw URL."""
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        sys.exit(f"Can't find the berry-slides clone at:\n  {REPO_DIR}\n\n"
                 'Clone it first:\n  cd ~/Desktop/"job account "\n'
                 f"  git clone https://github.com/{GH_USER}/{GH_REPO}.git")

    name = os.path.basename(path)
    dest_dir = os.path.join(REPO_DIR, "reels")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(path, os.path.join(dest_dir, name))
    print(f"  copied into the repo as reels/{name}")

    git("add", "-A")
    ok, out = git("commit", "-m", f"reel: {name}")
    if not ok and "nothing to commit" not in out:
        print(f"  ! commit problem: {out[:200]}")

    token = load_token()
    if token:
        ok, out = git("push", f"https://{token}@github.com/{GH_USER}/{GH_REPO}.git",
                      GH_BRANCH)
    else:
        ok, out = git("push")
    if not ok:
        safe = out.replace(token, "***") if token else out
        sys.exit(f"Push failed:\n{safe[:400]}\n\n"
                 "Most likely no GITHUB_TOKEN in .env.")
    print("  pushed")

    url = f"{RAW_BASE}/reels/{name}"
    if not wait_for_pages(url, timeout=120):
        sys.exit("GitHub didn't serve the video in time.\n"
                 "Check the repo is still PUBLIC, then run this again.")
    return url


# ---------------------------------------------------------------------------
# Not posting the same thing twice
# ---------------------------------------------------------------------------
def load_posted():
    if os.path.exists(POSTED_FILE):
        try:
            return json.load(open(POSTED_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_posted(d):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Post one video to Instagram as a reel.")
    ap.add_argument("video")
    ap.add_argument("--caption-file", default=None)
    ap.add_argument("--caption", default=None,
                    help="inline caption. A file is safer for emoji.")
    ap.add_argument("--dry-run", action="store_true",
                    help="check the video and the caption, push nothing, post nothing")
    ap.add_argument("--yes", action="store_true", help="skip the confirm prompt")
    ap.add_argument("--again", action="store_true",
                    help="post it even though this file has been posted before")
    args = ap.parse_args()

    path = os.path.abspath(os.path.expanduser(args.video))

    print("\nTHE VIDEO")
    check_video(path)

    # ---- the caption -------------------------------------------------------
    cap_path = args.caption_file or os.path.splitext(path)[0] + ".txt"
    if args.caption is not None:
        caption = args.caption
    elif os.path.exists(cap_path):
        caption = open(cap_path, encoding="utf-8").read().strip()
        print(f"\nCAPTION  (from {os.path.basename(cap_path)})")
    else:
        sys.exit(f"\nNo caption. Either put one in:\n  {cap_path}\n"
                 "or pass --caption-file / --caption.")
    if not caption.strip():
        sys.exit("The caption file is empty.")
    if len(caption) > 2200:
        sys.exit(f"Caption is {len(caption)} characters. Instagram's limit is 2200.")
    print("  " + "\n  ".join(caption.splitlines()))

    posted = load_posted()
    key = os.path.basename(path)
    if key in posted and not args.again:
        sys.exit(f"\n{key} was already posted on {posted[key]['when']}.\n"
                 "Pass --again if you really mean to post it twice.")

    if args.dry_run:
        print("\nDRY RUN -- nothing pushed, nothing posted.")
        return 0

    env = load_env()
    check_token_age(env)
    user_id, token = env.get("IG_USER_ID"), env.get("IG_ACCESS_TOKEN")
    if not user_id or not token:
        sys.exit("IG_USER_ID and IG_ACCESS_TOKEN both need to be in .env")

    if not args.yes:
        print(f"\nThis will post {key} to @berry.internships.syd, publicly, now.")
        if input("Type yes to go ahead: ").strip().lower() != "yes":
            print("Nothing posted.")
            return 0

    # ---- 1. get it on the web ---------------------------------------------
    print("\nUPLOADING")
    video_url = push_video(path)
    print(f"  {video_url}")

    # ---- 2. container ------------------------------------------------------
    print("\nCREATING THE REEL")
    r = api_post(user_id, {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        # Reels only appear on the profile grid if you ask for it. Off by
        # default in the API, which is a strange default for an account whose
        # grid is the whole shopfront.
        "share_to_feed": "true",
        "access_token": token,
    }, "Creating the reel container")
    container = r["id"]
    print(f"  container {container}")

    # ---- 3. wait for Meta to transcode ------------------------------------
    print("\n  Meta is downloading and transcoding it. This is the slow part.")
    wait_ready(container, token, "the reel", timeout=TRANSCODE_TIMEOUT)

    # ---- 4. publish --------------------------------------------------------
    print("\nPUBLISHING")
    out = api_post(f"{user_id}/media_publish",
                   {"creation_id": container, "access_token": token},
                   "Publishing the reel")
    media_id = out.get("id", "?")

    posted[key] = {"when": time.strftime("%Y-%m-%d %H:%M"),
                   "media_id": media_id, "url": video_url}
    save_posted(posted)

    print(f"\n  posted. media id {media_id}")
    print("  https://www.instagram.com/berry.internships.syd/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
