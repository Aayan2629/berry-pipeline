#!/usr/bin/env python3
"""
build_carousels.py
===================
Builds Instagram CAROUSEL posts -- one per category.

Each carousel is:
    slide_01_cover.png   the category name over a photo ("Computer Science
                         & Software Engineering", "5 open roles", swipe hint)
    slide_02.png ...     one internship per slide, using the same job card
                         design as build_posts.py
    caption.txt          the post caption, with the links numbered by slide
    links.txt            a clean numbered list to paste into your Linktree

INTERNSHIPS ONLY. Graduate programs are deliberately skipped here -- they
belong in their own carousels, not mixed in with internships.

SLIDE NUMBERING: the links start at "Slide 2", because slide 1 is the cover
and has no job on it. Getting that off by one would send people to the wrong
listing, so it's derived from the slide's real position, never assumed.

More than 5 internships in a category? It splits into numbered carousels
(part 1, part 2, ...) rather than dropping any.

HOW TO RUN
----------
    python3 build_carousels.py                     every category
    python3 build_carousels.py --category arch     just Architecture
    python3 build_carousels.py --category "comp sci"
    python3 build_carousels.py --list              show the category names
    python3 build_carousels.py --rebuild           redo ones already built

--category matches loosely, so you don't have to type
"Computer Science & Software Engineering" in full -- "comp sci", "cs",
"software" and "computer" all find it.
"""

import glob
import json
import os
import re
import sys
from collections import defaultdict





# Instagram @mentions ARE tappable in a caption (plain URLs are not), so where
# we know a company's handle it is worth putting in. We never guess one: an
# invented handle tags a real stranger's account on the post. Fill in
# company_handles.json by hand and anything still blank is simply left off.

# Some Seek listings are posted by an agency account rather than the employer.
# "SEEK Grad" is Seek's own grad-program account: the real employer appears
# only in the job title. We will not guess the employer from the title, so
# these listings simply show no company name -- the advertiser's logo, which
# Seek still gives us, carries the branding instead.
NOT_EMPLOYERS = {"seek grad", "seek", "seek limited"}


def _has_logo(job):
    """
    True when this listing will get a REAL logo on its slide.

    Asks poster_template the same question it asks itself at draw time, so
    this can never drift out of step with what actually gets rendered: a
    cached or downloadable mark returns a path, and anything else falls back
    to the initials tile.
    """
    business = job.get("company_name") or job.get("business_name") or ""
    try:
        return bool(poster_template._logo_for(business, job.get("logo_url")))
    except Exception:
        # Never let a logo lookup stop a carousel being built.
        return False


def real_company(name):
    """The company name, or "" when it is an agency account rather than the
    actual employer."""
    name = (name or "").strip()
    return "" if name.casefold() in NOT_EMPLOYERS else name


_HANDLES = None


def load_handles():
    """Read company_handles.json once, the first time a handle is asked for.
    Read lazily rather than at import time so the file is optional and a typo
    in it can never stop the whole build."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "company_handles.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for name, handle in raw.items():
        handle = (handle or "").strip().lstrip("@")
        if handle:
            out[name.strip().casefold()] = handle
    return out


def handle_for(company):
    global _HANDLES
    if _HANDLES is None:
        _HANDLES = load_handles()
    return _HANDLES.get((company or "").strip().casefold(), "")


# Keycap emoji for the slide numbers. A carousel is at most 6 slides, so this
# covers every case; anything past it falls back to a plain number.
KEYCAPS = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣",
           4: "4️⃣", 5: "5️⃣", 6: "6️⃣",
           7: "7️⃣", 8: "8️⃣", 9: "9️⃣",
           10: "🔟"}


def keycap(n):
    return KEYCAPS.get(n, "[%d]" % n)


# Instagram allows 30 hashtags. Around a dozen is the sweet spot: enough to be
# found, not so many it looks like spam. The first few are the broad ones people
# actually search; the last is the category, so each post is still distinct.
BASE_TAGS = ["sydneyinternships", "internships", "internship", "studentjobs",
             "graduatejobs", "sydneystudents", "unsw", "usyd", "uts",
             "macquarieuniversity", "westernsydneyuni", "sydneyjobs"]


# Tags per category, on top of BASE_TAGS. Deliberately specific: a post from
# an account this size disappears inside #jobs or #career within the hour,
# while the university tags are small enough to actually surface and are read
# by exactly the people the post is for.
CATEGORY_TAGS = {
    "Engineering": ["engineeringstudent", "engineeringjobs", "civilengineering",
                    "engineeringinternship"],
    "Technology, Data & AI": ["techinternship", "datascience",
                              "softwareengineering", "compsci"],
    "Business, Commerce, Marketing & Finance": ["financeinternship",
                                                "accountingjobs", "consulting",
                                                "businessstudent"],
}


def hashtags(category):
    """The shared tags plus the ones for this category."""
    extra = CATEGORY_TAGS.get((category or "").strip())
    if not extra:
        extra = [slug(category).replace("-", "")[:24]]
    return " ".join("#" + t for t in BASE_TAGS + extra)


def say(*a):
    print(*a, flush=True)

import poster_template            # for _logo_for, used by _has_logo below
from poster_template import build_poster, build_cover, build_endcard

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "queue_carousels")
SEEN_FILE = os.path.join(HERE, "seen_carousels.json")
# Job ids that have actually gone out on Instagram. Written by
# publish_to_instagram.py, read here so a listing is never posted twice.
# It starts empty, which is what makes the very first week post everything
# and every week after it post only what is new.
POSTED_JOBS_FILE = os.path.join(HERE, "posted_jobs.json")

# Your real handle once the account exists.
ACCOUNT_HANDLE = "berry.internships.syd"

# Slide 1 is the cover, so this many JOBS makes a 6-slide post.
# Six roles plus the cover is a 7-slide post. Instagram allows 10, so
# there is headroom; override per run with --per-carousel N.
JOBS_PER_CAROUSEL = 6

# Engineering is the one category that also carries graduate programmes.
# In Australia almost every student engineering role is advertised as a
# graduate programme, a vacation program or a cadetship -- filtering grads out
# left Engineering with three roles a fortnight while the actual openings sat
# there unposted. The cover says INTERNSHIPS & GRADS when a carousel contains
# any, so nobody is misled about what they are swiping through.
CATEGORIES_ALLOWING_GRADS = {"Engineering"}

# At most this many roles per category per build, newest first. Two full
# carousels each. Without a cap Business ran to four parts and monopolised the
# queue for a fortnight while Technology sat empty; with it, every category
# gets the same amount of airtime and what does go out is the freshest thing
# available. A category with fewer than this simply posts what it has.
MAX_PER_CATEGORY = 12

# What a cover says, where that differs from the internal category name.
# Engineering carries graduate programmes as well as internships, and the
# cover should say so before someone swipes in expecting only internships.
COVER_NAMES = {
    "Engineering": "Engineering Internships & Grad Roles",
}

# Which day each category goes out. Mirrors SCHEDULE in
# publish_to_instagram.py -- kept here only so the summary at the end of a
# build can tell you when what you are looking at will actually post.
POSTING_DAY = {
    "Technology, Data & AI": "Monday",
    "Business, Commerce, Marketing & Finance": "Thursday",
    "Engineering": "Saturday",
}

# Reuse the category + internship-vs-graduate logic from all_jobs.py so the
# carousels match the website exactly.
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
from all_jobs import (categorize, job_track, is_internship,
                      job_age_days, MAX_AGE_DAYS,
                      load_dead_listings)


def load_all_jobs():
    """
    Merge EVERY crawl, newest copy of each job wins, and prefer the enriched
    version of a crawl (the one with descriptions) when it exists.

    Reading only the newest enriched file was too strict -- enrichment is
    slow, so most crawls only have the plain file, and a job card is still
    perfectly good without a description. It just loses the closing-date
    pill and start date, which come out of the description text.
    """
    roots = [os.path.join(HERE, "..", "output", "seek_spider")]
    crawl_dirs = []
    for root in roots:
        crawl_dirs.extend(glob.glob(os.path.join(root, "*", "*")))
    if not crawl_dirs:
        raise SystemExit(
            "No crawl output found. Run this first:\n"
            "  python3 ../scrapers/seek.py"
        )
    crawl_dirs.sort(key=os.path.getmtime)

    by_id = {}
    for crawl_dir in crawl_dirs:
        enriched = os.path.join(crawl_dir, "jobs_enriched.jsonl")
        plain = os.path.join(crawl_dir, "jobs.jsonl")
        path = enriched if os.path.exists(enriched) else plain
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                j = json.loads(line)
                jid = j.get("job_id")
                if not jid:
                    continue
                old = by_id.get(jid)
                # never let a description-less copy overwrite an enriched one
                if old and old.get("description_text") and not j.get("description_text"):
                    continue
                by_id[jid] = j
    return list(by_id.values())


def slug(text):
    import re
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


ALL_CATEGORIES = [name for name, _ in __import__("all_jobs").CATEGORY_RULES]


def match_category(typed):
    """
    Find which of the 7 categories the user meant, without making them type
    the whole thing. Every word they typed has to appear somewhere in the
    category name, so "comp sci" and "arch" both work, while a word that
    matches nothing returns no result rather than guessing.
    """
    want = re.sub(r"[^a-z0-9 ]+", " ", typed.lower()).split()
    hits = []
    for cat in ALL_CATEGORIES:
        haystack = re.sub(r"[^a-z0-9 ]+", " ", cat.lower())
        if all(any(w in word for word in haystack.split()) for w in want):
            hits.append(cat)
    return hits




def clear_queue():
    """Move every unposted carousel out of the queue.

    Only used by --rebuild. The carousel a set of listings splits into changes
    whenever the rules change -- dropping graduate roles turned a 6-role
    Computer Science pair into a single 3-role carousel -- and the old folders
    do not disappear on their own. Left there, publish_to_instagram.py would
    happily post the stale one. Moved rather than deleted so nothing is lost.
    """
    old = os.path.join(HERE, "old_carousels")
    moved = 0
    # queue_carousels/ is generated output and is not in git, so on a fresh
    # checkout (GitHub Actions) it does not exist yet. Nothing to clear.
    os.makedirs(OUT_ROOT, exist_ok=True)
    for name in sorted(os.listdir(OUT_ROOT)):
        src = os.path.join(OUT_ROOT, name)
        if not os.path.isdir(src):
            continue
        os.makedirs(old, exist_ok=True)
        dst = os.path.join(old, name)
        n = 2
        while os.path.exists(dst):
            dst = os.path.join(old, f"{name}-{n}")
            n += 1
        os.rename(src, dst)
        moved += 1
    if moved:
        print(f"--rebuild: moved {moved} old carousel(s) to old_carousels/")




def split_evenly(items, cap):
    """
    Split a category into carousels of at most `cap` roles, as evenly as
    possible, and never put one employer on two slides of the same post.

    Two problems, one function.

    SIZE. Slicing straight down the list leaves a runt: seven roles at a cap
    of six becomes 6 + 1, and a carousel with one role is a two-slide post --
    a cover and a single card. Balancing gives 4 + 3 instead, which is two
    respectable posts and still under the cap.

    REPEATS. drop_repeats already caps an employer at MAX_PER_EMPLOYER, but
    it does that across the whole CATEGORY, and a category becomes several
    carousels. Slicing contiguously then undid the work: items are sorted by
    logo and posted date, an employer's two roles almost always share both,
    so they sat next to each other in the list and fell into the same post.
    Zimmer Biomet twice, Apple twice, AECOM twice -- different roles every
    time, but two slides carrying the same name and the same mark read as a
    duplicate, which is how this was reported.

    So the roles are dealt into the parts rather than sliced. Employers with
    the most roles are dealt first, because they are the ones that need the
    room, and each role goes to the emptiest part that does not already hold
    that employer. Each part is then put back into the original order, so the
    newest-first feel of the carousel survives the dealing.
    """
    n = len(items)
    if n <= cap:
        return [items]

    parts = -(-n // cap)                 # how many carousels we need
    base, extra = divmod(n, parts)       # spread the remainder over the first few
    sizes = [base + (1 if k < extra else 0) for k in range(parts)]

    position = {id(j): i for i, j in enumerate(items)}
    buckets = [[] for _ in range(parts)]
    owners = [set() for _ in range(parts)]

    groups = {}
    for j in items:
        groups.setdefault(employer_identity(j), []).append(j)

    for who in sorted(groups, key=lambda k: -len(groups[k])):
        for j in groups[who]:
            room = [i for i in range(parts) if len(buckets[i]) < sizes[i]]
            # a part that has not got this employer yet, if there is one; with
            # MAX_PER_EMPLOYER at 2 and at least 2 parts there always is.
            choice = [i for i in room if who not in owners[i]] or room
            i = min(choice, key=lambda i: len(buckets[i]))
            buckets[i].append(j)
            owners[i].add(who)

    for b in buckets:
        b.sort(key=lambda j: position[id(j)])
    return buckets


# How many slides one employer may take in a category. Three SG Fleet cards
# in a six-slide carousel is not a roundup of Sydney tech internships, it is
# an SG Fleet ad, even when all three roles are genuinely different.
MAX_PER_EMPLOYER = 2


def employer_identity(j):
    """
    Who a listing is REALLY from, with the spellings collapsed.

    This is the whole fix. The same job arrives from Seek, LinkedIn, Indeed
    and Glassdoor under whatever name each board happened to store, so
    matching on the raw company name treats

        Zurich Australia / Zurich Insurance / Zurich Financial Services
        Munich Re / Munich Reinsurance

    as five different employers and puts the identical listing on three
    slides of the same carousel. brand_domains.json already knows all of
    those map to zurich.com.au and munichre.com -- it was built for picking
    logos -- so the domain is the identity, and the normalised name is only
    the fallback for employers that have no entry.
    """
    name = real_company(j.get("company_name") or j.get("business_name")) or ""
    try:
        dom = poster_template.brand_domain(name)
    except Exception:
        dom = ""
    return dom or re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


# Words that appear in job titles but never tell two roles apart. Every
# listing on this account is a Sydney internship, so "Sydney" in a title is
# decoration, not information -- and it is exactly what let ADP Consulting
# put "Graduate Engineer 2027 | Fire Safety" and "Graduate Engineer 2027 |
# Fire Safety (Sydney)" on two slides of the same carousel.
#
# Keep this list to things that are true of EVERY listing. A word that
# actually distinguishes one role from another (a team, a discipline, a
# year) must not go in here, or two different jobs collapse into one and a
# real listing silently disappears.
TITLE_NOISE = {
    "sydney", "nsw", "australia", "australian", "au", "aus",
    "remote", "hybrid", "onsite", "cbd", "office", "based",
    "full", "part", "time", "casual", "ongoing", "temp", "temporary",
    "m", "f", "d", "x",          # what is left of "(m/f/d)" after stripping
}


def _title_key(job_title, who):
    """The role, with everything that is not the role taken back out of it.

    Three different things make the same job hash differently depending on
    which board it came from:

      1. Seek puts the company in the title ("SG Fleet2027 Internship-
         Data & Analytics"), LinkedIn does not.
      2. LinkedIn posts the same role once with a location suffix and once
         without ("... | Fire Safety" and "... | Fire Safety (Sydney)").
      3. Punctuation and case differ everywhere.

    So: drop anything in brackets, drop the employer's own name, drop the
    words that are true of every listing, and compare what is left.
    """
    t = (job_title or "").lower()

    # Anything in brackets is nearly always a location, a requisition number
    # or an equal-opportunity tag, never the thing that makes a role itself.
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)

    # Handled as a phrase so the individual words "new", "south" and "wales"
    # stay usable -- "New Business Intern" is a real and different role.
    t = t.replace("new south wales", " ")

    t = re.sub(r"[^a-z0-9]+", " ", t)

    for token in who.replace(".", " ").split():
        if len(token) > 3:
            t = t.replace(token, " ")

    return " ".join(w for w in t.split() if w not in TITLE_NOISE)


def drop_repeats(items):
    """
    One slide per role, and no employer taking over a carousel.

    Two listings are the same when they come from the same employer and the
    same role once punctuation, case, source spelling and the company name
    inside the title are all ignored. Big employers repost the identical ad
    on several boards, and a carousel showing the same card three times
    reads as broken rather than thorough.
    """
    seen, out, dropped, crowded = set(), [], 0, 0
    per_employer = {}
    for j in items:
        who = employer_identity(j)
        key = (who, _title_key(j.get("job_title"), who))
        if key in seen:
            dropped += 1
            continue
        if per_employer.get(who, 0) >= MAX_PER_EMPLOYER:
            crowded += 1
            continue
        seen.add(key)
        per_employer[who] = per_employer.get(who, 0) + 1
        out.append(j)
    return out, dropped, crowded


def load_posted_jobs():
    """Ids of listings already published. Missing file means nothing has been
    posted yet, so nothing gets filtered out."""
    try:
        with open(POSTED_JOBS_FILE, encoding="utf-8") as f:
            return {str(k) for k in json.load(f)}
    except (OSError, ValueError):
        return set()


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def main():
    argv = sys.argv[1:]

    if "--list" in argv:
        say("The 7 categories:")
        for cat in ALL_CATEGORIES:
            say(f"  - {cat}")
        say("\nUse any part of a name, e.g.:")
        say('  python3 build_carousels.py --category arch')
        return

    only_category = None
    if "--category" in argv:
        i = argv.index("--category")
        if i + 1 >= len(argv):
            raise SystemExit("--category needs a name after it, "
                             'e.g. --category "comp sci"')
        typed = argv[i + 1]
        hits = match_category(typed)
        if not hits:
            raise SystemExit(
                f"No category matches {typed!r}.\n"
                "Run  python3 build_carousels.py --list  to see the names.")
        if len(hits) > 1:
            raise SystemExit(
                f"{typed!r} matches more than one category:\n  "
                + "\n  ".join(hits) + "\nBe a bit more specific.")
        only_category = hits[0]
        del argv[i:i + 2]

    if "--per-carousel" in argv:
        i = argv.index("--per-carousel")
        if i + 1 >= len(argv):
            raise SystemExit("--per-carousel needs a number after it")
        global JOBS_PER_CAROUSEL
        JOBS_PER_CAROUSEL = max(1, min(9, int(argv[i + 1])))
        del argv[i:i + 2]

    repost = "--repost" in argv
    argv = [a for a in argv if a != "--repost"]

    args = [a for a in argv if a not in ("--rebuild", "-r")]
    rebuild = len(args) != len(argv)
    if args:
        jobs = [json.loads(l) for l in open(args[0], encoding="utf-8") if l.strip()]
        print(f"Reading: {args[0]}")
    else:
        jobs = load_all_jobs()
        print(f"Read every crawl on disk: {len(jobs)} unique jobs")

    # keep internships only, and only ones with a real description
    by_category = defaultdict(list)
    already_posted = set() if repost else load_posted_jobs()
    grad_count = skipped_nodesc = skipped_uncat = skipped_posted = skipped_grad = skipped_old = skipped_dead = 0
    dead_listings = load_dead_listings()
    for j in jobs:
        title, desc = j.get("job_title"), j.get("description_text") or ""
        if not desc:
            skipped_nodesc += 1      # counted, but still posted
        if not is_internship(title, desc, j.get("work_type")):
            continue
        cat = categorize(title, desc)
        if not cat:
            skipped_uncat += 1
            continue
        # Internships only, except where a category is allowed grads too.
        if (job_track(title, desc, j.get("work_type")) == "Graduate Programs"
                and cat not in CATEGORIES_ALLOWING_GRADS):
            skipped_grad += 1
            continue
        if str(j.get("job_id")) in already_posted:
            skipped_posted += 1
            continue
        # Old listings are usually filled or closed. Posting one wastes a
        # slide and sends people to a dead application page, which is worse
        # than posting nothing. A listing with no date is kept -- Seek not
        # telling us is not evidence that it is stale.
        age = job_age_days(j.get("posted_date"))
        if age is not None and age > MAX_AGE_DAYS:
            skipped_old += 1
            continue
        # Closed since we scraped it. Run check_live.py to keep this current;
        # without it nothing is treated as dead, so this simply does nothing.
        if str(j.get("job_id")) in dead_listings:
            skipped_dead += 1
            continue
        by_category[cat].append(j)

    if only_category:
        by_category = {k: v for k, v in by_category.items() if k == only_category}
        say(f"Only building: {only_category}")
        if not by_category:
            raise SystemExit(f"No internships found in {only_category!r} "
                             "right now. Try another category, or scrape more.")

    print(f"Internships to post: {sum(len(v) for v in by_category.values())}")
    print(f"  (skipped {skipped_grad} graduate programme(s) -- "
          f"internships only)")
    print(f"  (skipped {skipped_old} older than {MAX_AGE_DAYS} days)")
    print(f"  (skipped {skipped_dead} that Seek says have closed)")
    print(f"  (skipped {skipped_uncat} that fit none of the categories)")
    if skipped_posted:
        print(f"  (skipped {skipped_posted} already posted to Instagram -- "
              f"pass --repost to include them again)")
    print(f"  ({skipped_nodesc} have no description yet -- their cards just "
          f"won't show closing/start dates)\n")

    seen = set() if rebuild else load_seen()
    if rebuild:
        print("--rebuild: regenerating everything")
        clear_queue()
        print()

    built = 0
    summary = {}
    for category in sorted(by_category, key=lambda c: len(by_category[c]), reverse=True):
        items = by_category[category]
        # Logo first, then freshness.
        #
        # This used to sort on posted_date alone, which meant the slides were
        # whichever listings happened to be newest -- and roughly half of all
        # employers on the board have no logo we can resolve, so about every
        # second slide went out carrying a grey initials tile instead of a
        # mark. A post is the shop window; a slide that says "AA" sells
        # nothing. Sorting logo-backed listings to the front costs nothing
        # (there are far more of them than fit in a carousel) and the ones
        # without a logo still reach people through the website.
        items.sort(key=lambda j: (_has_logo(j), str(j.get("posted_date") or "")),
                   reverse=True)
        items, repeats, crowded = drop_repeats(items)
        if repeats:
            say(f"  ({repeats} duplicate listing(s) dropped from {category})")
        if crowded:
            say(f"  ({crowded} extra listing(s) dropped from {category} so no "
                f"employer takes more than {MAX_PER_EMPLOYER} slides)")

        # Newest first, then keep only the freshest MAX_PER_CATEGORY of them.
        if len(items) > MAX_PER_CATEGORY:
            say(f"  ({category}: keeping the {MAX_PER_CATEGORY} most recent "
                f"of {len(items)})")
            items = items[:MAX_PER_CATEGORY]

        chunks = split_evenly(items, JOBS_PER_CAROUSEL)

        for part, chunk in enumerate(chunks, start=1):
            name = slug(category) + (f"-part{part}" if len(chunks) > 1 else "")
            out_dir = os.path.join(OUT_ROOT, name)
            # A folder still in the queue is waiting to be posted -- leave it
            # be. Once it has gone out the publisher moves it away, so the
            # name is free again for the next batch of listings.
            if os.path.isdir(out_dir) and not rebuild:
                continue
            os.makedirs(out_dir, exist_ok=True)

            # --- slide 1: the cover ---
            n_grad = sum(1 for j in chunk
                         if job_track(j.get("job_title"),
                                      j.get("description_text") or "",
                                      j.get("work_type")) == "Graduate Programs")
            build_cover(COVER_NAMES.get(category, category),
                        len(chunk), out_dir,
                        account_handle=ACCOUNT_HANDLE, seed=name,
                        n_grad=n_grad)

            # --- slides 2..N: one job each ---
            caption_links, bio_links = [], []
            for i, job in enumerate(chunk):
                slide_no = i + 2          # +2: slide 1 is the cover
                build_poster(job, out_dir,
                             account_handle=ACCOUNT_HANDLE,
                             category=category,
                             filename=f"slide_{slide_no:02d}.jpg",
                             write_caption=False,
                             bg_seed=name)   # one photo for the whole carousel
                title = job.get("job_title") or ""
                company = real_company(job.get("company_name")
                                      or job.get("business_name"))
                url = job.get("url") or ""
                # Instagram shows plain text, so a shorter URL simply reads
                # better. seek.com.au/job/123 resolves the same as the full one.
                short = re.sub(r"^https?://(www\.)?", "", url)
                # a known handle turns the company line into a real link
                tag = handle_for(company)
                entry = [f"{keycap(slide_no)} {title}"]
                if tag:
                    entry.append(f"🏢 @{tag}")
                elif company:
                    entry.append(f"🏢 {company}")
                entry.append(f"🔗 {short}")
                caption_links.append("\n".join(entry))
                bio_links.append(
                    f"Slide {slide_no}: {title}"
                    + (f" \u2014 {company}" if company else "")
                    + f"\n{url}")

            # --- last slide: the ask ---
            # Numbered so it sorts after the job slides rather than before
            # them: sorted() is what puts a carousel in swipe order, and
            # "slide_99_end" would be fine but "slide_08_end" keeps the
            # numbering honest about where it actually falls.
            build_endcard(category, out_dir,
                          account_handle=ACCOUNT_HANDLE,
                          filename=f"slide_{len(chunk) + 2:02d}_end.jpg",
                          seed=name)

            # --- caption.txt ---
            heading = category if len(chunks) == 1 else f"{category} (part {part})"
            # The first line is the only part Instagram shows before the
            # "... more" cut, so the count, the field and the city all go there.
            lead = category if len(chunks) == 1 else f"{category} (part {part})"
            n = len(chunk)
            # The first line is the only part Instagram shows before the
            # "... more" cut, so the count, the field and the city all go there.
            lead = category if len(chunks) == 1 else f"{category} (part {part})"
            n = len(chunk)
            rule = "━" * 13
            caption = [
                f"📍 {n} {lead} internship{'s' if n != 1 else ''} "
                f"open in Sydney right now",
                "",
                "👉 Swipe through, then comment ACCESS and I'll send you "
                "the full list",
                "",
                rule,
                "",
                "\n\n".join(caption_links),
                "",
                rule,
                "",
                "🔔 New roles every 3 days — follow so you "
                "don't miss one",
                "",
                "💬 comment ACCESS for every Sydney internship, not just "
                "these ones",
                "",
                hashtags(category),
            ]
            with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(caption) + "\n")

            # --- links.txt (for Linktree) ---
            with open(os.path.join(out_dir, "links.txt"), "w", encoding="utf-8") as f:
                f.write(f"{heading}\n{'=' * len(heading)}\n\n")
                f.write("\n\n".join(bio_links) + "\n")

            # what the publisher needs to know about this carousel
            with open(os.path.join(out_dir, "meta.json"), "w",
                      encoding="utf-8") as f:
                json.dump({
                    "category": category,
                    "part": part,
                    "job_ids": [str(j.get("job_id")) for j in chunk],
                }, f, indent=2)

            print(f"  {name}/  ({len(chunk) + 1} slides)")
            summary.setdefault(category, []).append((name, part, chunk))
            seen.add(name)
            built += 1

    save_seen(seen)
    print(f"\nBuilt {built} carousel(s) in: {OUT_ROOT}")
    if not built:
        print("(nothing new -- use --rebuild to redo the existing ones)")
        return
    print_summary(summary)


def print_summary(summary):
    """
    Everything that is now sitting in the queue, listed out.

    The build log above is a list of folder names, which tells you nothing
    about what is actually going to be posted. This prints the real roles,
    grouped by category and in swipe order, with the day each carousel goes
    out -- so the last thing on screen after a build is the thing you would
    otherwise have to open a folder to find out.
    """
    line = "=" * 66
    print(f"\n{line}\n  WHAT IS READY TO POST\n{line}")

    total = 0
    for category in sorted(summary, key=lambda c: POSTING_DAY.get(c, "z")):
        parts = summary[category]
        n = sum(len(chunk) for _, _, chunk in parts)
        total += n
        day = POSTING_DAY.get(category, "unscheduled")
        heading = COVER_NAMES.get(category, category)
        print(f"\n  {heading}")
        print(f"  {'-' * (len(heading))}")
        print(f"  {n} role{'s' if n != 1 else ''} across "
              f"{len(parts)} carousel{'s' if len(parts) != 1 else ''}"
              f"  ·  posts {day}s\n")

        for name, part, chunk in parts:
            when = day if part == 1 else f"{day} + {part - 1} (overflow)"
            print(f"    {name}   [{when}]")
            for i, j in enumerate(chunk, start=2):      # slide 1 is the cover
                title = (j.get("job_title") or "")[:52]
                who = real_company(j.get("company_name")
                                   or j.get("business_name")) or "—"
                grad = (" (grad)" if job_track(
                    j.get("job_title"), j.get("description_text") or "",
                    j.get("work_type")) == "Graduate Programs" else "")
                print(f"      {i}. {title:<52}  {who[:26]}{grad}")
            print()

    print(f"{line}")
    print(f"  {total} role(s) queued in total")
    print(f"{line}\n")
    print("  python3 preview.py                  see the actual slides")
    print("  python3 publish_to_instagram.py     post what is due today\n")


if __name__ == "__main__":
    main()
