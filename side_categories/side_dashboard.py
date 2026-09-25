#!/usr/bin/env python3
"""
side_categories/side_dashboard.py -- a quick look at what the side scraper found.

    python3 side_categories/side_dashboard.py           build it and open it
    python3 side_categories/side_dashboard.py --quiet   build it, don't open

It reads the NEWEST architecture.jsonl and medicine.jsonl in
output/side_spider/ and makes one HTML page: side_categories/side_dashboard.html

Like the main dashboard.py it only READS. It doesn't post, doesn't touch the
main queue, and the main dashboard doesn't know it exists.
"""

import argparse
import glob
import html
import json
import os
import webbrowser
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUNS = os.path.join(REPO, "output", "side_spider")
OUT = os.path.join(HERE, "side_dashboard.html")

# category -> (file name, planned posting day)
CATEGORIES = {
    "Architecture": ("architecture.jsonl", "Wednesday"),
    "Medicine & Health": ("medicine.jsonl", "Sunday"),
}
MIN_JOBS_FOR_A_POST = 3


def newest(file_name):
    """Path of the most recent run folder that has this file, or None.

    Run folders are named by timestamp (20260925_074706), so sorting the
    names alphabetically also sorts them by time -- the last one is newest.
    """
    paths = sorted(glob.glob(os.path.join(RUNS, "*", file_name)))
    return paths[-1] if paths else None


def load(path):
    """Read a .jsonl file: one JSON job per line -> list of dicts.
    (Like reading a CSV row by row in C with fgets, one record per line.)"""
    jobs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                jobs.append(json.loads(line))
    # newest posting first
    jobs.sort(key=lambda j: str(j.get("posted_date", "")), reverse=True)
    return jobs


def card(j):
    e = lambda s: html.escape(str(s or ""))       # make text safe for HTML
    company = j.get("company_name") or j.get("business_name") or "Company not listed"
    extra = " · ".join(x for x in (j.get("suburb"), j.get("work_type"),
                                    j.get("pay_range")) if x)
    return f"""
      <a class="job" href="{e(j.get('url'))}" target="_blank" rel="noopener">
        <div class="t">{e(j.get('job_title'))}</div>
        <div class="c">{e(company)}</div>
        <div class="m">{e(extra)}</div>
        <div class="d">posted {e(str(j.get('posted_date', ''))[:10])}</div>
      </a>"""


def section(name, file_name, day):
    path = newest(file_name)
    if not path:
        return f"<section><h2>{name}</h2><p class='empty'>No run yet.</p></section>"
    jobs = load(path)
    ok = len(jobs) >= MIN_JOBS_FOR_A_POST
    run = os.path.basename(os.path.dirname(path))
    verdict = ("enough for a post" if ok else "too thin to post")
    return f"""
    <section>
      <div class="head">
        <h2>{html.escape(name)}</h2>
        <span class="day">{day}</span>
      </div>
      <div class="big {'good' if ok else 'bad'}">{len(jobs)}
        <small>job{'s' if len(jobs) != 1 else ''} · {verdict}</small></div>
      <div class="run">from run {run}</div>
      <div class="list">{''.join(card(j) for j in jobs)}</div>
    </section>"""


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Side categories</title><style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--mute:#77726a;--line:#e6e1d7;
--good:#2f7d4f;--bad:#b4462f;--accent:#7a3cc4}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;
--ink:#efece6;--mute:#9a958c;--line:#34312c;--good:#5cc28a;--bad:#ea7c62;
--accent:#b58af0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:28px 20px 8px;max-width:1100px;margin:auto}
h1{margin:0;font-size:24px}header p{margin:4px 0 0;color:var(--mute)}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
gap:20px;padding:16px 20px 40px;max-width:1100px;margin:auto}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:18px}
.head{display:flex;justify-content:space-between;align-items:center}
h2{margin:0;font-size:18px}.day{font-size:12px;font-weight:600;color:var(--accent);
border:1px solid var(--accent);border-radius:99px;padding:2px 10px}
.big{font-size:44px;font-weight:700;margin-top:10px}.big small{font-size:14px;
font-weight:500;color:var(--mute);margin-left:6px}.good{color:var(--good)}
.bad{color:var(--bad)}.run{font-size:12px;color:var(--mute);margin-bottom:12px}
.job{display:block;text-decoration:none;color:inherit;border-top:1px solid var(--line);
padding:10px 2px}.job:hover .t{color:var(--accent)}
.t{font-weight:600}.c{font-size:14px}.m,.d{font-size:12px;color:var(--mute)}
.empty{color:var(--mute)}
</style></head><body>
<header><h1>Side categories: Architecture &amp; Medicine</h1>
<p>Testing only. Nothing here posts. Built {built}.</p></header>
<main>{sections}</main></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="don't open a browser")
    args = ap.parse_args()

    sections = "".join(section(n, f, d) for n, (f, d) in CATEGORIES.items())
    page = (PAGE.replace("{built}", datetime.now().strftime("%a %d %b, %I:%M %p"))
                .replace("{sections}", sections))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Side dashboard written to:\n  {OUT}")
    if not args.quiet:
        webbrowser.open("file://" + OUT)


if __name__ == "__main__":
    main()
