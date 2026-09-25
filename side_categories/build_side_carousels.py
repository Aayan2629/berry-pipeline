#!/usr/bin/env python3
"""
side_categories/build_side_carousels.py -- real carousels for the side categories.

    python3 side_categories/build_side_carousels.py

Takes the newest architecture.jsonl and medicine.jsonl that scrape_side.py
wrote, and draws them with the SAME slide design as the main pipeline:
cover, one job per slide with the company logo, end card, caption.

WHY IT'S SAFE
  * Slides go to side_categories/side_carousels/, NOT queue_carousels/.
    publish_to_instagram.py only ever posts from queue_carousels/, so these
    physically can't be posted by accident.
  * It borrows poster_template.py and build_carousels.py read-only. The
    extra colours for Architecture/Medicine are added in memory while this
    script runs -- the files themselves aren't edited.
  * The background-photo "memory" (which photo was used last) is shared by
    the main pipeline, so this script points it at its own file instead:
    side_categories/side_background_rotation.json.
  * It does NOT write seen_carousels.json or posted_jobs.json. It only READS
    posted_jobs.json, to skip anything already posted.
  * The only shared thing it can add to is the logos/ cache -- a new
    company's logo gets downloaded there once. That's the same logo lookup
    the main slides use, and a cached logo only helps them.
"""

import glob
import json
import os
import re
import sys

# ---- find the main code ---------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))        # side_categories/
REPO = os.path.dirname(HERE)                             # SeekSpider-main/
PIPE = os.path.join(REPO, "pipeline_scripts")
sys.path.insert(0, REPO)          # all_jobs.py
sys.path.insert(0, PIPE)          # poster_template.py, build_carousels.py
sys.path.insert(0, HERE)          # find_side_logos.py

import poster_template as pt                                      # noqa: E402
import build_carousels as bc                                      # noqa: E402
from all_jobs import job_track                                    # noqa: E402

RUNS = os.path.join(REPO, "output", "side_spider")
# LIVE: these now go into the real queue, same as the main categories, so
# publish_to_instagram.py posts them on their day (Architecture Wednesday,
# Medicine Sunday). Before going live they went to side_categories/side_carousels/.
OUT_ROOT = bc.OUT_ROOT            # pipeline_scripts/queue_carousels

# category -> (results file, posting day, slide colours (main, deep), short name)
# Colours are picked to sit at the same muted darkness as the existing three
# (berry, teal, rust) so the feed still looks like one account.
SIDE = {
    "Architecture": ("architecture.jsonl", "Wednesday",
                     ((84, 92, 150), (28, 30, 56)), "Architecture"),
    "Medicine & Health": ("medicine.jsonl", "Sunday",
                          ((46, 128, 92), (16, 46, 34)), "Medicine & health"),
}

HASHTAGS = {
    "Architecture": "#sydneyinternships #architecturestudent #architecture "
                    "#archigrad #studentjobs #unsw #usyd #uts",
    "Medicine & Health": "#sydneyinternships #medicalstudent #pharmacystudent "
                         "#nursingstudent #healthcare #studentjobs #unsw #usyd",
}


def teach_poster_template_the_new_categories():
    """Add the two categories to poster_template's lookup tables IN MEMORY.

    Python modules are objects you can change while the program runs --
    like editing a global array in C at runtime. Nothing on disk changes,
    and the next time the main pipeline runs it loads the original values.
    """
    for cat, (_f, _d, colours, short) in SIDE.items():
        pt.PALETTES[cat] = colours
        pt.SHORT_CATEGORY[cat] = short
    # Own photo-rotation memory, so the main carousels' photo order is untouched.
    pt.ROTATION_FILE = os.path.join(HERE, "side_background_rotation.json")


def newest(file_name):
    paths = sorted(glob.glob(os.path.join(RUNS, "*", file_name)))
    return paths[-1] if paths else None


def load_jobs(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def clear_old_slides(folder):
    """Remove the last build's slides so a smaller build doesn't leave extras.
    Only touches files inside side_carousels/."""
    for f in glob.glob(os.path.join(folder, "*")):
        try:
            os.remove(f)
        except OSError:
            pass


def retire_old(category):
    if not os.path.isdir(OUT_ROOT):
        return
    old_dir = os.path.join(PIPE, "old_carousels")
    for name in sorted(os.listdir(OUT_ROOT)):
        meta = os.path.join(OUT_ROOT, name, "meta.json")
        try:
            with open(meta, encoding="utf-8") as f:
                if json.load(f).get("category") != category:
                    continue
        except (OSError, ValueError):
            continue
        os.makedirs(old_dir, exist_ok=True)
        dst, n = os.path.join(old_dir, name), 2
        while os.path.exists(dst):
            dst, n = os.path.join(old_dir, f"{name}-{n}"), n + 1
        os.rename(os.path.join(OUT_ROOT, name), dst)


def build_category(category, tiles):
    file_name, day, _c, _s = SIDE[category]
    path = newest(file_name)
    if not path:
        print(f"{category}: no results yet -- run scrape_side.py first")
        return []

    posted = bc.load_posted_jobs()       # read only
    jobs = [j for j in load_jobs(path) if str(j.get("job_id")) not in posted]

    # Same ordering as the main build: jobs WITH a real logo first, then newest.
    jobs.sort(key=lambda j: (bc._has_logo(j), str(j.get("posted_date") or "")),
              reverse=True)
    jobs, _repeats, _crowded = bc.drop_repeats(jobs)
    jobs = jobs[:bc.MAX_PER_CATEGORY]
    if not jobs:
        print(f"{category}: nothing to build")
        return []

    # Move this category's previous (unposted) carousels out of the queue
    # first, like build_carousels.py --rebuild does, so a stale part 2 from
    # an older build can never be posted. Moved to old_carousels/, not deleted.
    retire_old(category)

    chunks = bc.split_evenly(jobs, bc.JOBS_PER_CAROUSEL)
    built = []
    for part, chunk in enumerate(chunks, start=1):
        name = bc.slug(category) + (f"-part{part}" if len(chunks) > 1 else "")
        out_dir = os.path.join(OUT_ROOT, name)
        os.makedirs(out_dir, exist_ok=True)
        clear_old_slides(out_dir)

        n_grad = sum(1 for j in chunk
                     if job_track(j.get("job_title"), j.get("description_text") or "",
                                  j.get("work_type")) == "Graduate Programs")
        pt.build_cover(category, len(chunk), out_dir,
                       account_handle=bc.ACCOUNT_HANDLE, seed=name, n_grad=n_grad)

        links = []
        for i, job in enumerate(chunk):
            slide_no = i + 2                      # slide 1 is the cover
            pt.build_poster(job, out_dir, account_handle=bc.ACCOUNT_HANDLE,
                            category=category, filename=f"slide_{slide_no:02d}.jpg",
                            write_caption=False, bg_seed=name)
            company = bc.real_company(job.get("company_name") or job.get("business_name"))
            tag = bc.handle_for(company)
            short = re.sub(r"^https?://(www\.)?", "", job.get("url") or "")
            entry = [f"{bc.keycap(slide_no)} {job.get('job_title') or ''}"]
            if tag:
                entry.append(f"🏢 @{tag}")
            elif company:
                entry.append(f"🏢 {company}")
            entry.append(f"🔗 {short}")
            links.append("\n".join(entry))

        pt.build_endcard(category, out_dir, account_handle=bc.ACCOUNT_HANDLE,
                         filename=f"slide_{len(chunk) + 2:02d}_end.jpg", seed=name)

        lead = category if len(chunks) == 1 else f"{category} (part {part})"
        kind = "roles" if n_grad else ("internships" if len(chunk) != 1 else "internship")
        rule = "━" * 13
        caption = "\n".join([
            f"📍 {len(chunk)} {lead} {kind} open in Sydney right now", "",
            "👉 Swipe through, then comment ACCESS and I'll send you the full list",
            "", rule, "", "\n\n".join(links), "", rule, "",
            "🔔 New roles every week — follow so you don't miss one", "",
            "💬 comment ACCESS for every Sydney internship, not just these ones",
            "", HASHTAGS[category],
        ]) + "\n"
        with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
            f.write(caption)
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"category": category, "part": part, "day": day,
                       "side": True, "source": os.path.relpath(path, REPO),
                       "job_ids": [str(j.get("job_id")) for j in chunk]}, f, indent=2)

        n_logo = 0
        for j in chunk:
            if bc._has_logo(j):
                n_logo += 1
            else:
                tiles.append((bc.real_company(j.get("company_name")
                                              or j.get("business_name")),
                              j.get("job_title")))
        print(f"  {name}/  {len(chunk)} jobs, {n_logo} with a real logo")
        built.append(name)
    return built


def main():
    # STEP 1: search online for logos FIRST (same as find_logos.py does for
    # the main categories). Without this, unknown companies get initials.
    try:
        import find_side_logos
        find_side_logos.find()
    except Exception as e:        # no internet etc. -- warn, don't crash
        print(f"!! logo search failed ({e}) -- slides may show initials")

    teach_poster_template_the_new_categories()
    os.makedirs(OUT_ROOT, exist_ok=True)
    tiles = []
    for category in SIDE:
        print(f"\n{category}")
        build_category(category, tiles)

    # Loud list of anything still on an initials tile, so it's never silent.
    if tiles:
        print(f"\n!! {len(tiles)} slide(s) still show INITIALS, no logo found online:")
        for who, title in tiles:
            print(f"     {who or '(no company name)'}  --  {title}")
        print("   If you know the website:  python3 pipeline_scripts/find_logos.py "
              "--set \"Company\" company.com.au   then rebuild.")
    print(f"\nSlides in: {OUT_ROOT}")
    print("Architecture posts Wednesday, Medicine & Health posts Sunday.")
    print("See them:  python3 pipeline_scripts/dashboard.py")


if __name__ == "__main__":
    main()
