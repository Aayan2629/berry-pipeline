#!/usr/bin/env python3
"""
find_logos.py -- work out which website an employer actually owns, so their
real logo can go on the slide instead of an initials tile.

    python3 find_logos.py --category commerce      just that category
    python3 find_logos.py                          every employer that's missing one
    python3 find_logos.py --dry-run                look, write nothing
    python3 find_logos.py --limit 15               stop after 15

    python3 find_logos.py --accept "Arup"          approve one from the review list
    python3 find_logos.py --reject "Nine"          stop asking about it
    python3 find_logos.py --set "ADP Consulting" adpconsulting.com
                                                  the finder had the wrong one,
                                                  here is the right one

WHAT THE ACTUAL PROBLEM IS

Not fetching logos. Once you know a company owns arup.com, poster_template.py
already fetches and caches the mark on its own -- brand_domains.json is the
only thing it needs. The hard part is going from "Arup" to "arup.com" without
getting it wrong.

WHY THIS ISN'T AN AI

An LLM asked for Arup's website says arup.com and is right. Asked about "Nine"
it picks confidently between nine.com.au, nineentertainment.com.au and
nine.com, and you get someone else's logo on your slide. A wrong logo is worse
than an initials tile: a tile reads as a small business, a wrong logo reads as
someone who doesn't check. So nothing here guesses without then checking.

HOW IT DECIDES

  1. Wikidata. Free, no key, and it holds the "official website" property for
     basically every employer big enough that a missing logo looks bad --
     Arup, QBE, Ventia, Ramsay, Clayton Utz, Ausgrid, Macquarie University.
     A hit here is taken as fact.

  2. Guess, then verify. Build a candidate from the name, fetch it, and read
     the page's own <title> and og:site_name. Accept it only when every
     significant word of the company name is there AND the domain itself
     contains one of them. Anything weaker goes to you.

  3. Everything else lands in logo_review.json and shows up on the dashboard
     with the logo it would use, for you to approve or throw out.

The 17 employers in your pool with nothing to go on -- Thaitax, PARts
Australia, "Private Advertiser" -- stay as initials tiles, and they should.
Nobody expects to recognise them.

NEEDS THE INTERNET, so run it on your Mac.
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import requests
except ImportError:
    sys.exit("Needs requests:  pip3 install --user requests")

import poster_template as P
from build_carousels import categorize, match_category, real_company

BRANDS_FILE = os.path.join(HERE, "brand_domains.json")
REVIEW_FILE = os.path.join(HERE, "logo_review.json")
OUTPUT_GLOB = os.path.join(HERE, "..", "output", "**", "*.jsonl")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Words that carry no identity. "Sydney Water" and "Water" are not the same
# company, but "Pty Ltd" tells you nothing about either.
NOISE = {"pty", "ltd", "limited", "group", "australia", "australian", "au",
         "the", "and", "co", "company", "holdings", "services", "service",
         "international", "global", "inc", "corp", "corporation", "nsw",
         "sydney", "recruitment", "consulting", "solutions", "partners"}

# Names too generic to ever resolve safely. "Nine" could be three different
# companies; a one-word name that is also an ordinary English word is exactly
# where a confident guess does the most damage.
TOO_GENERIC = {"nine", "seven", "ten", "uniting", "bring", "indus", "signify",
               "private advertiser", "confidential"}


def tokens(name):
    """The words in a company name that actually identify it."""
    ws = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    return [w for w in ws if w not in NOISE and len(w) > 1]


# ---------------------------------------------------------------------------
# 1. Wikidata
# ---------------------------------------------------------------------------
def wikidata_domain(name):
    """The company's official website, straight off Wikidata. None if it is
    not there or if the match is not confident."""
    try:
        r = requests.get("https://www.wikidata.org/w/api.php",
                         params={"action": "wbsearchentities", "search": name,
                                 "language": "en", "format": "json", "limit": 5,
                                 "type": "item"},
                         headers={"User-Agent": UA}, timeout=20)
        hits = r.json().get("search", [])
    except Exception:
        return None, "wikidata unreachable"

    want = set(tokens(name))
    for hit in hits:
        label = hit.get("label", "")
        desc = (hit.get("description") or "").lower()
        # The label has to actually be this company, and the entity has to be
        # an organisation of some kind. Searching "Apple" returns the fruit
        # first, and the fruit has no website.
        if not want or not want <= set(tokens(label)) | set(tokens(name)):
            continue
        if not any(k in desc for k in ("company", "business", "firm", "bank",
                                       "university", "school", "agency",
                                       "organisation", "organization",
                                       "council", "enterprise", "insurer",
                                       "retailer", "manufacturer", "hospital",
                                       "government", "institution", "charity")):
            continue
        try:
            c = requests.get("https://www.wikidata.org/w/api.php",
                             params={"action": "wbgetclaims", "entity": hit["id"],
                                     "property": "P856", "format": "json"},
                             headers={"User-Agent": UA}, timeout=20).json()
            url = c["claims"]["P856"][0]["mainsnak"]["datavalue"]["value"]
        except Exception:
            continue
        host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
        if host:
            return host, f"wikidata: {label} ({desc[:40]})"
    return None, "not on wikidata"


# ---------------------------------------------------------------------------
# 2. Guess, then verify
# ---------------------------------------------------------------------------
def candidates(name):
    """Domains this company might plausibly own, best first."""
    ts = tokens(name)
    if not ts:
        return []
    joined = "".join(ts)
    out = []
    for stem in dict.fromkeys([joined, ts[0]]):     # dedupe, keep order
        if len(stem) < 3:
            continue
        out += [f"{stem}.com.au", f"{stem}.com"]
    return out[:4]


def site_identity(domain):
    """(title, og:site_name) for a domain, or None if it doesn't answer."""
    for scheme in ("https://", "http://"):
        try:
            r = requests.get(scheme + domain, headers={"User-Agent": UA},
                             timeout=15, allow_redirects=True)
            if r.status_code != 200 or len(r.text) < 200:
                continue
            html = r.text[:200000]
            title = re.search(r"<title[^>]*>(.*?)</title>", html,
                              re.S | re.I)
            og = re.search(r'<meta[^>]+property=["\']og:site_name["\']'
                           r'[^>]+content=["\'](.*?)["\']', html, re.I)
            return ((title.group(1) if title else "").strip(),
                    (og.group(1) if og else "").strip())
        except Exception:
            continue
    return None


def guess_and_verify(name):
    """A domain we have actually checked belongs to this company."""
    want = tokens(name)
    if not want:
        return None, "no usable name", None
    for dom in candidates(name):
        ident = site_identity(dom)
        if ident is None:
            continue
        title, og = ident
        blob = tokens(title + " " + og)
        # Every identifying word has to be on the page, and the domain itself
        # has to carry at least one of them. Both, because a title match alone
        # passes on directory pages that list a hundred companies.
        if all(w in blob for w in want) and any(w in dom for w in want):
            return dom, f'verified: page title "{title[:48]}"', title, dom
        # It answered but it is not them. Hand the domain back anyway so the
        # dashboard can show you what it saw -- "this is what I found and this
        # is why I didn't believe it" is a far more useful thing to look at
        # than a blank row.
        return None, f'{dom} answered but says "{title[:48]}"', title, dom
    cands = candidates(name)
    return None, "no candidate domain answered", None, (cands[0] if cands else None)


# ---------------------------------------------------------------------------
# Reading what is on disk
# ---------------------------------------------------------------------------
def load_jobs():
    jobs = {}
    for f in sorted(glob.glob(OUTPUT_GLOB, recursive=True)):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if isinstance(j, dict) and j.get("job_id"):
                jobs[str(j["job_id"])] = j
    return list(jobs.values())


def has_logo_already(name):
    """True if a logo file is already cached, WITHOUT going to the network.

    Deliberately not calling poster_template._logo_for: that fetches, and a
    scan should not spend a minute downloading before it has decided what it
    is even looking for.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    if not slug:
        return True
    for suffix in ("", "_brand", "_seek"):
        p = os.path.join(P.LOGOS_DIR, f"{slug}{suffix}.png")
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return True
    return False


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
def accept(name):
    review = load_json(REVIEW_FILE, {})
    entry = review.get(name)
    if not entry or not entry.get("domain"):
        sys.exit(f"Nothing pending for {name!r}. "
                 f"Run find_logos.py first, or add it to brand_domains.json by hand.")
    brands = load_json(BRANDS_FILE, {})
    brands[name] = entry["domain"]
    save_json(BRANDS_FILE, brands)
    review.pop(name, None)
    save_json(REVIEW_FILE, review)
    print(f"{name} -> {entry['domain']}  saved.")
    print("It will appear on every future slide. Rebuild to see it now:")
    print("  python3 build_carousels.py --rebuild")


def set_domain(name, domain, force=False):
    """Pin a domain the finder did not come up with itself.

    This is the case accept/reject cannot cover. The finder proposed
    adp.com.au for ADP Consulting, which is a real site that answers -- it
    just belongs to the payroll company, not the engineering consultancy
    that posted the job. "Yes, that's them" would have put the wrong logo on
    a slide, and "Not them" would have written the employer off to an
    initials tile forever. Neither is right when you know the answer and the
    finder simply did not.

    It is checked before it is saved: the mark has to actually fetch, so a
    typo fails here rather than showing up as a blank square on a slide.
    """
    domain = (domain or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain).strip("/").split("/")[0]
    domain = re.sub(r"^www\.", "", domain)
    if not domain or "." not in domain:
        sys.exit(f"{domain!r} does not look like a domain. "
                 "Give it bare, like adpconsulting.com")

    print(f"checking {domain} serves a mark...")
    try:
        mark = P.fetch_brand_mark(domain, name)
    except Exception as e:
        mark = None
        print(f"  ! {type(e).__name__}: {e}")
    if not mark and not force:
        sys.exit(
            f"Nothing came back from {domain}, so it is NOT being saved.\n\n"
            "Two different things look like this:\n"
            f"  1. the domain is wrong -- open https://{domain} and check\n"
            "  2. this machine has no internet right now\n\n"
            "If the site opens fine in your browser and you are sure, save it\n"
            "anyway and the mark will be fetched the next time a slide needs it:\n"
            f'  python3 find_logos.py --set "{name}" {domain} --force')
    if not mark:
        print("  ! nothing fetched, saving anyway because you passed --force")

    brands = load_json(BRANDS_FILE, {})
    brands[name] = domain
    save_json(BRANDS_FILE, brands)

    review = load_json(REVIEW_FILE, {})
    review.pop(name, None)
    save_json(REVIEW_FILE, review)

    print(f"{name} -> {domain}  saved.")
    print("Rebuild to see it:")
    print("  python3 build_carousels.py --rebuild")
    return 0


def reject(name):
    review = load_json(REVIEW_FILE, {})
    review[name] = {"domain": None, "why": "rejected", "rejected": True}
    save_json(REVIEW_FILE, review)
    print(f"{name} will stay an initials tile and won't be asked about again.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--category", default=None,
                    help='part of a category name, e.g. "commerce"')
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--accept", default=None)
    ap.add_argument("--reject", default=None)
    ap.add_argument("--force", action="store_true",
                    help="with --set, save the domain even if the mark did "
                         "not fetch just now")
    ap.add_argument("--set", nargs=2, metavar=("NAME", "DOMAIN"), default=None,
                    dest="set_pair",
                    help='pin a domain yourself: --set "ADP Consulting" '
                         'adpconsulting.com')
    args = ap.parse_args()

    if args.set_pair:
        return set_domain(args.set_pair[0], args.set_pair[1], args.force)
    if args.accept:
        return accept(args.accept)
    if args.reject:
        return reject(args.reject)

    want_cat = None
    if args.category:
        hits = match_category(args.category)
        if not hits:
            sys.exit(f"No category matches {args.category!r}")
        want_cat = hits[0]
        print(f"Category: {want_cat}")

    jobs = load_jobs()
    brands = load_json(BRANDS_FILE, {})
    review = load_json(REVIEW_FILE, {})

    # One entry per employer, not per listing.
    todo = {}
    for j in jobs:
        name = real_company(j.get("company_name") or j.get("business_name")) or ""
        name = name.strip()
        if not name:
            continue
        if want_cat and categorize(j.get("job_title"),
                                   j.get("description_text") or "") != want_cat:
            continue
        todo.setdefault(name, 0)
        todo[name] += 1

    pending = [(n, c) for n, c in todo.items()
               if n not in brands
               and not has_logo_already(n)
               and not review.get(n, {}).get("rejected")]
    pending.sort(key=lambda x: -x[1])

    print(f"\n{len(todo)} employers here, {len(pending)} with no logo.\n")
    if args.limit:
        pending = pending[:args.limit]

    added = queued = 0
    for name, count in pending:
        print(f"{name}   ({count} listing{'s' if count != 1 else ''})")

        if name.lower() in TOO_GENERIC or len(tokens(name)) == 0:
            print("   too generic to resolve safely -- leaving it as a tile\n")
            review[name] = {"domain": None, "why": "name is ambiguous",
                            "count": count}
            continue

        dom, why = wikidata_domain(name)
        if dom:
            print(f"   {why}")
            print(f"   -> {dom}   ACCEPTED\n")
            brands[name] = dom
            added += 1
            review.pop(name, None)
            continue
        print(f"   {why}")

        dom, why, title, cand = guess_and_verify(name)
        if dom:
            print(f"   {why}")
            print(f"   -> {dom}   ACCEPTED\n")
            brands[name] = dom
            added += 1
            review.pop(name, None)
            continue

        print(f"   {why}")
        print("   -> needs your eyes\n")
        review[name] = {"domain": cand, "why": why, "count": count,
                        "saw": title, "confirmed": False}
        queued += 1

    print("=" * 62)
    print(f"  {added} resolved and saved, {queued} for you to look at")
    print("=" * 62)

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0

    save_json(BRANDS_FILE, brands)
    save_json(REVIEW_FILE, review)
    if added:
        print("\nSee them on the slides:")
        print("  python3 build_carousels.py --rebuild")
    if queued:
        print("\nThe ones it wasn't sure about are on the dashboard:")
        print("  python3 dashboard.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
