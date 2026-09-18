#!/usr/bin/env python3
"""
refresh_ig_token.py -- extend the Instagram token before it dies.

    python3 refresh_ig_token.py              on your Mac: updates .env
    python3 refresh_ig_token.py --check      how many days are left
    python3 refresh_ig_token.py --github     in Actions: updates the secret

WHY THIS IS THE MOST IMPORTANT SCRIPT IN THE FOLDER

An Instagram long-lived token lasts sixty days and nothing renews it. On day
sixty-one every publish fails. If the whole account runs itself in the cloud,
that is a system that quietly stops working after two months and tells you by
going silent, which is the worst way to find out.

Meta will hand you a fresh sixty days for the asking, as long as the token
you ask with is still valid and at least a day old. So ask, monthly, forever.

WHAT IT NEVER DOES

Print the token. Not on success, not in an error, not in an Actions log. The
new value goes straight into .env or straight into a GitHub secret and is
never rendered anywhere a human or a log file can see it.

THE GITHUB SIDE

A workflow cannot change its own secrets with the token GitHub hands it --
that token deliberately cannot write secrets. So --github needs a personal
access token of your own, in the GH_PAT secret, with:

    Repository permissions -> Secrets -> Read and write

Secrets are encrypted before they are sent, with the repository's own public
key, so the value never crosses the wire in the clear.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, ".env")
GRAPH = "https://graph.instagram.com"

# Meta's own number. Everything here is measured against it.
LIFETIME_DAYS = 60

# Refresh when fewer than this many days are left. Well before the wire, so a
# single failed run is an inconvenience rather than an outage, and comfortably
# after Meta's one-day minimum age.
REFRESH_UNDER_DAYS = 25


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def days_left(obtained):
    if not obtained:
        return None
    try:
        age = (datetime.now() - datetime.fromisoformat(obtained)).days
    except ValueError:
        return None
    return LIFETIME_DAYS - age


def refresh(token):
    """Ask Meta for a fresh sixty days. Returns (new_token, days)."""
    try:
        r = requests.get(f"{GRAPH}/refresh_access_token",
                         params={"grant_type": "ig_refresh_token",
                                 "access_token": token},
                         timeout=45)
    except requests.exceptions.RequestException as e:
        # The URL carries the token, and requests puts the URL in the
        # exception, so the original must never reach the log.
        sys.exit(f"Couldn't reach Instagram ({type(e).__name__}).")

    if r.status_code != 200:
        detail = r.text.replace(token, "***")
        sys.exit(f"Instagram refused to refresh it (HTTP {r.status_code}):\n"
                 f"{detail[:300]}\n\n"
                 "If it says the token is invalid or expired, this script "
                 "cannot help -- generate a new one by hand in the Meta app "
                 "dashboard.")

    data = r.json()
    new = data.get("access_token")
    if not new:
        sys.exit("Instagram answered but sent no token back.")
    return new, int(data.get("expires_in", 0)) // 86400


def write_env(new_token):
    """Rewrite .env in place, keeping every other line exactly as it was."""
    today = datetime.now().date().isoformat()
    lines, seen_token, seen_date = [], False, False
    for line in open(ENV_FILE, encoding="utf-8"):
        if line.startswith("IG_ACCESS_TOKEN="):
            lines.append(f"IG_ACCESS_TOKEN={new_token}\n"); seen_token = True
        elif line.startswith("IG_TOKEN_OBTAINED="):
            lines.append(f"IG_TOKEN_OBTAINED={today}\n"); seen_date = True
        else:
            lines.append(line)
    if not seen_token:
        lines.append(f"IG_ACCESS_TOKEN={new_token}\n")
    if not seen_date:
        lines.append(f"IG_TOKEN_OBTAINED={today}\n")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def put_secret(repo, pat, name, value):
    """Store one Actions secret, encrypted with the repo's public key."""
    try:
        from nacl import encoding, public
    except ImportError:
        sys.exit("Needs PyNaCl to encrypt the secret:  pip install pynacl")
    import base64

    head = {"Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json"}

    k = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
                     headers=head, timeout=30)
    if k.status_code != 200:
        sys.exit(f"Couldn't read the repo public key (HTTP {k.status_code}).\n"
                 "The GH_PAT secret needs Secrets: Read and write on this repo.")
    key = k.json()

    sealed = public.SealedBox(
        public.PublicKey(key["key"].encode(), encoding.Base64Encoder)
    ).encrypt(value.encode())

    r = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
        headers=head, timeout=30,
        json={"encrypted_value": base64.b64encode(sealed).decode(),
              "key_id": key["key_id"]})
    if r.status_code not in (201, 204):
        sys.exit(f"Couldn't store {name} (HTTP {r.status_code}): {r.text[:200]}")
    print(f"  stored {name}")


def main():
    ap = argparse.ArgumentParser(description="Extend the Instagram token.")
    ap.add_argument("--check", action="store_true",
                    help="say how long is left, change nothing")
    ap.add_argument("--github", action="store_true",
                    help="store the new token as a GitHub Actions secret")
    ap.add_argument("--force", action="store_true",
                    help="refresh even though there is plenty of time left")
    args = ap.parse_args()

    env = load_env()
    token = env.get("IG_ACCESS_TOKEN")
    if not token:
        sys.exit("No IG_ACCESS_TOKEN in .env")

    left = days_left(env.get("IG_TOKEN_OBTAINED"))
    if left is None:
        print("  no IG_TOKEN_OBTAINED date, so the age is unknown")
    else:
        print(f"  {left} day(s) left on the current token")

    if args.check:
        return 0 if (left is None or left > 7) else 1

    if left is not None and left > REFRESH_UNDER_DAYS and not args.force:
        print(f"  more than {REFRESH_UNDER_DAYS} days left, leaving it alone")
        return 0

    print("  asking Meta for a fresh sixty days...")
    new_token, days = refresh(token)
    print(f"  got one, good for about {days} days")

    if args.github:
        repo = os.environ.get("GITHUB_REPOSITORY")
        pat = os.environ.get("GH_PAT")
        if not repo:
            sys.exit("GITHUB_REPOSITORY is not set -- is this really Actions?")
        if not pat:
            sys.exit(
                "The token was refreshed but there is nowhere to put it.\n"
                "Add a GH_PAT secret (a personal access token with\n"
                "Secrets: Read and write on this repo) and run this again.\n"
                "The old token still works until its own expiry, so nothing\n"
                "is broken yet.")
        put_secret(repo, pat, "IG_ACCESS_TOKEN", new_token)
        put_secret(repo, pat, "IG_TOKEN_OBTAINED",
                   datetime.now().date().isoformat())
        print("\n  done. The next run will pick it up.")
    else:
        write_env(new_token)
        print(f"\n  .env updated. Good until about "
              f"{(datetime.now() + timedelta(days=days)).date()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
